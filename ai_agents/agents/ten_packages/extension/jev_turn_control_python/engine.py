"""Clock-injected turn reducer. All methods run on one event-loop thread."""

from collections import deque
from copy import deepcopy
import math

from .config import Config


class TurnEngine:
    """Bounded input mailbox, revision fences, timers and heard-only memory."""

    def __init__(self, config=None, session_id="demo"):
        self.config = config or Config.load()
        self.session_id = session_id
        self.events = deque(maxlen=self.config["observation"]["buffer_limit"])
        self.actions = []
        self.seq = 0
        self.now = 0
        self.revision = 0
        self.epoch = 0
        self.text = ""
        self.segment = ""
        self.committed = ""
        self.final = False
        self.pending = False
        self.first_input = 0
        self.last_input = 0
        self.last_request = -100000
        self.inflight = None
        self.request_seq = 0
        self.last_decided = -1
        self.last_decided_speaking = None
        self.timer = None
        self.timer_seq = 0
        self.active = None
        self.stopping = None
        self.responses = {}
        self.finished = {}
        self.history = []
        self.context_revision = 0
        self.summary = ""
        self.compression_request = None
        self.compression_attempt = -100000
        self.capacity_reached = False
        self.consumed_segment = None
        self.consumed_text = ""
        self.last_backchannel = -100000
        self.closed = False
        self.paused = False
        self.paused_timer = None
        self.failed = False
        self.guidance_sent = False

    def emit(self, kind, payload=None, response_id=None):
        self.seq += 1
        data = deepcopy(payload or {})
        if not self.config["observation"]["include_text"]:
            for key in (
                "text",
                "heard_text",
                "input_text",
                "context",
                "phrase",
            ):
                if key in data:
                    data[key] = "[redacted]"
        event = {
            "version": 1,
            "event_id": f"{self.session_id}:{self.seq}",
            "seq": self.seq,
            "session_id": self.session_id,
            "relative_time_ms": self.now,
            "type": kind,
            "input_revision": self.revision,
            "response_id": response_id,
            "payload": data,
        }
        if self.config["observation"]["enabled"]:
            self.events.append(event)
        return event

    def action(self, kind, **payload):
        self.actions.append({"type": kind, **payload})

    def drain_actions(self):
        actions, self.actions = self.actions, []
        return actions

    def snapshot(self):
        state = {
            "phase": (
                "closed"
                if self.closed
                else (
                    "paused"
                    if self.paused
                    else (
                        "stopping"
                        if self.stopping
                        else "speaking" if self.active else "listening"
                    )
                )
            ),
            "pending": self.pending,
            "text": self.text,
            "response_epoch": self.epoch,
            "active_response_id": self.active,
            "stopping_response_id": self.stopping,
            "timer": deepcopy(self.timer),
            "inflight": self.inflight is not None,
            "context": deepcopy(self.history),
            "context_summary": self.summary,
            "context_revision": self.context_revision,
            "context_capacity_reached": self.capacity_reached,
            "mode": self.config["provider"]["name"],
            "playback_precision": "browser_cursor_estimate",
        }
        return self.emit("state.snapshot", state, self.active)

    def input(self, text, final, now, segment_id="default"):
        if self.closed or not text.strip():
            return
        self.now = now
        text = " ".join(text[:12000].split())
        # A repeated final for the partial already used to answer is not a new turn.
        if segment_id == self.consumed_segment and text == self.consumed_text:
            return
        if segment_id != self.segment:
            if self.segment:
                self.committed = self.text
            self.segment = segment_id
        combined = (self.committed + " " + text).strip()[-16000:]
        if combined == self.text and final == self.final:
            return
        if not self.pending:
            self.first_input = now
        self.pending = True
        self.text, self.final = combined, final
        self.revision += 1
        self.last_input = now
        self.failed = False
        self.cancel_timer("new_input")
        self.emit(
            "asr.updated",
            {
                "text": self.text,
                "final": final,
                "segment_id": segment_id,
                "characters": len(self.text),
            },
        )

    def cancel_timer(self, reason):
        if self.timer:
            self.emit("timer.cancelled", {**self.timer, "reason": reason})
            self.timer = None

    def schedule(self, label, immediate=False):
        self.cancel_timer("replaced")
        self.timer_seq += 1
        delay = 0 if immediate else self.config["wait"][label + "_ms"]
        # A continuation is a hold, not a request to clarify. Only sustained
        # silence can exhaust it; ongoing ASR must never exhaust a turn budget.
        if label == "continuation":
            delay = max(
                0,
                self.last_input
                + self.config["scheduling"]["max_wait_ms"]
                - self.now,
            )
        self.timer = {
            "timer_id": self.timer_seq,
            "label": label,
            "due_ms": min(
                self.now + delay,
                self.last_input + self.config["scheduling"]["max_wait_ms"],
            ),
            "input_revision": self.revision,
            "epoch": self.epoch,
        }
        self.emit("timer.scheduled", self.timer)

    def begin_decision(self, now):
        self.now = now
        if (
            self.closed
            or self.paused
            or not self.pending
            or self.inflight
            or self.stopping
        ):
            return None
        cfg = self.config["scheduling"]
        speaking = bool(self.active)
        if (
            self.revision == self.last_decided
            and speaking == self.last_decided_speaking
        ) or now - self.last_request < cfg["min_interval_ms"]:
            return None
        quiet_ms = now - self.last_input
        if speaking:
            # Stop decisions retain the bounded debounce: continuous speech
            # cannot starve interruption. No speculative start request is needed
            # until playback releases the floor.
            elapsed = now - max(self.first_input, self.last_request)
            if (
                quiet_ms < cfg["merge_ms"]
                and elapsed < cfg["min_interval_ms"] + cfg["merge_ms"]
            ):
                return None
        elif quiet_ms < max(cfg["merge_ms"], cfg["min_interval_ms"]):
            # Listening can wait for a stable partial. The previous hard bound
            # sent requests immediately after fresh speech whenever the prior
            # request was old, wasting calls on rapidly changing prefixes.
            return None
        if not self.config["turn"]["enabled"]:
            return None
        candidates = ("start", "backchannel")
        if speaking:
            candidates = (
                ("stop", "start")
                if self.responses[self.active]["mode"] == "backchannel"
                else ("stop",)
            )
        kinds = [k for k in candidates if self.config[k]["enabled"]]
        if not kinds:
            return None
        self.request_seq += 1
        request = {
            "request_id": self.request_seq,
            "revision": self.revision,
            "epoch": self.epoch,
            "started_ms": now,
            "kinds": kinds,
            "state": {
                "input_text": self.text,
                "asr_final": self.final,
                "assistant_speaking": bool(self.active),
                "heard_context": deepcopy(self.history),
                "older_context_summary": self.summary,
                "silence_ms": now - self.last_input,
            },
        }
        self.inflight = request
        self.last_request = now
        for kind in kinds:
            self.emit(
                "decision.started",
                {
                    "decision_kind": kind,
                    "provider": self.config["provider"]["name"],
                    "input_text": self.text,
                    "input_characters": len(self.text),
                    "context_responses": len(self.history),
                },
            )
        return deepcopy(request)

    def complete_decision(self, request, answers, now, error=None):
        self.now = now
        if (
            self.inflight is None
            or request.get("request_id") != self.inflight["request_id"]
        ):
            return
        self.inflight = None
        stale = (
            self.closed
            or request["revision"] != self.revision
            or request["epoch"] != self.epoch
        )
        reason = (
            "closed"
            if self.closed
            else (
                "input_revision"
                if request["revision"] != self.revision
                else "response_epoch"
            )
        )
        for kind in request["kinds"]:
            answer = answers.get(kind, {})
            self.emit(
                "decision.discarded" if stale else "decision.completed",
                {
                    "decision_kind": kind,
                    "provider": self.config["provider"]["name"],
                    "label": answer.get("label", "error"),
                    "score": answer.get("score"),
                    "probabilities": answer.get("probabilities", {}),
                    "duration_ms": now - request["started_ms"],
                    "applied": False,
                    "discard_reason": (
                        reason if stale else "provider_error" if error else ""
                    ),
                },
                self.active,
            )
        if stale:
            return
        self.last_decided = self.revision
        self.last_decided_speaking = request["state"]["assistant_speaking"]
        if error:
            self.failed = True
            self.emit(
                "error", {"code": "provider_unavailable", "recoverable": True}
            )
            return
        stop = answers.get("stop", {})
        if (
            self.active
            and stop.get("label") == "stop"
            and stop.get("score", 0) >= self.config["stop"]["threshold"]
        ):
            self.mark_applied("stop")
            self.stop("user_reclaims_floor")
            self.schedule("continuation")
            return
        start = answers.get("start", {})
        label = start.get("label")
        score = start.get("score", 0)
        # Answer and clarify both grant the assistant the floor. For a stable
        # final segment, uncertainty between those two must not turn a complete
        # short answer into a five-second hold. Final alone grants nothing.
        probabilities = start.get("probabilities", {})
        reply_score = probabilities.get("answer", 0) + probabilities.get(
            "clarify", 0
        )
        if (
            self.final
            and label not in ("explicit_wait", "ignore")
            and score < self.config["start"]["threshold"]
            and reply_score >= self.config["start"]["threshold"]
        ):
            label = (
                "answer"
                if probabilities.get("answer", 0)
                > probabilities.get("clarify", 0)
                else "clarify"
            )
            score = reply_score
        if label in (
            "answer",
            "clarify",
            "continuation",
            "explicit_wait",
            "ignore",
        ):
            if score >= self.config["start"]["threshold"] or label in (
                "explicit_wait",
                "ignore",
            ):
                self.mark_applied(
                    "start", effective_label=label, effective_score=score
                )
                self.schedule(label)
        bc = answers.get("backchannel", {})
        if (
            not self.active
            and not self.stopping
            and label == "continuation"
            and bc.get("label") == "backchannel"
            and bc.get("score", 0) >= self.config["backchannel"]["threshold"]
            and now - request["started_ms"]
            <= self.config["backchannel"]["valid_ms"]
            and now - self.last_backchannel
            >= self.config["backchannel"]["cooldown_ms"]
        ):
            self.mark_applied("backchannel")
            self.last_backchannel = now
            self.start("backchannel")

    def mark_applied(self, kind, **details):
        for event in reversed(self.events):
            if (
                event["type"] == "decision.completed"
                and event["input_revision"] == self.revision
                and event["payload"]["decision_kind"] == kind
            ):
                event["payload"]["applied"] = True
                event["payload"].update(details)
                break

    def tick(self, now):
        self.now = now
        if self.closed or self.paused:
            return
        if (
            self.active
            and self.responses[self.active]["mode"] == "backchannel"
            and self.pending
            and self.config["start"]["enabled"]
            and self.timer
            and now >= self.timer["due_ms"]
            and self.timer["label"] in ("answer", "clarify")
        ):
            label = self.timer["label"]
            self.stop("main_response_priority")
            self.schedule(label, immediate=True)
        if self.stopping:
            response = self.responses[self.stopping]
            if now >= response["stop_deadline"]:
                self.playback(
                    self.stopping,
                    response["played_ms"],
                    now,
                    stopped=True,
                    confirmed=False,
                )
        if (
            self.pending
            and self.active
            and self.config["stop"]["enabled"]
            and now >= self.first_input + self.config["stop"]["max_wait_ms"]
            and self.last_decided != self.revision
        ):
            self.stop("stop_maximum_wait")
            self.schedule("continuation")
        if (
            not self.pending
            or self.active
            or self.stopping
            or not self.config["start"]["enabled"]
        ):
            return
        if self.failed and self.config["provider"]["failure_policy"] == "hold":
            return
        maximum = (
            now >= self.last_input + self.config["scheduling"]["max_wait_ms"]
        )
        due = self.timer and now >= self.timer["due_ms"]
        if not maximum and not due:
            return
        label = self.timer["label"] if self.timer else "clarify"
        guidance = label == "continuation" or (maximum and not due)
        if guidance and self.guidance_sent:
            return
        if due:
            self.emit("timer.fired", self.timer)
        else:
            self.emit(
                "timer.fired",
                {
                    "label": "maximum_wait",
                    "due_ms": self.last_input
                    + self.config["scheduling"]["max_wait_ms"],
                },
            )
        self.timer = None
        if label in ("ignore", "explicit_wait"):
            self.pending = False
            return
        if guidance:
            self.guidance_sent = True
        else:
            self.guidance_sent = False
        self.start("answer" if label == "answer" else "clarify")

    def start(self, mode):
        if self.active or self.stopping or self.closed:
            return
        cfg = self.config["compression"]
        if mode != "backchannel" and (
            self.context_size() + len(self.text) + 24000 > cfg["max_chars"]
            or len(self.history) + 2 > cfg["max_messages"]
        ):
            if not self.capacity_reached:
                self.emit(
                    "context.capacity",
                    {"reason": "history_limit", "recoverable": False},
                )
            self.capacity_reached = True
            self.pending = False
            return
        self.epoch += 1
        rid = f"{self.session_id}-r{self.epoch}"
        self.active = rid
        self.responses[rid] = {
            "text": "",
            "played_ms": 0,
            "alignment": [],
            "pending_alignment": [],
            "audio_origin_ms": None,
            "mode": mode,
            "precision": "unknown",
            "generation_done": False,
            "audio_done": False,
            "audio_end_received": False,
            "audio_failed": False,
            "expected_audio_ms": None,
            "unverified_completion": False,
            "audio_ms": 0,
            "audio_chunk_floor_ms": 0,
            "fully_played": False,
        }
        if mode != "backchannel":
            self.pending = False
            self.consumed_segment = self.segment
            self.consumed_text = self.text[len(self.committed) :].strip()
            self.committed = ""
            self.segment = ""
            self.cancel_timer("response_started")
        self.emit(
            "response.started",
            {
                "mode": mode,
                "reason": "timer_or_decision",
                "input_text": self.text,
            },
            rid,
        )
        self.action(
            "response.start",
            session_id=self.session_id,
            input_revision=self.revision,
            response_id=rid,
            mode=mode,
            input_text=self.text,
            context=deepcopy(self.history),
            summary=self.summary,
            context_revision=self.context_revision,
            phrase=(
                self.config["backchannel"]["phrases"][0]
                if mode == "backchannel"
                else ""
            ),
        )

        if mode != "backchannel":
            self.history.append({"role": "user", "text": self.text})
            self.context_revision += 1

    def stop(self, reason):
        if not self.active:
            return
        rid, self.active = self.active, None
        self.epoch += 1
        self.stopping = rid
        self.responses[rid]["stop_deadline"] = (
            self.now + self.config["playback"]["stop_ack_timeout_ms"]
        )
        self.cancel_timer("stop_priority")
        self.emit(
            "response.cancelled",
            {"reason": reason, "awaiting_playback_ack": True},
            rid,
        )
        self.action("response.cancel", response_id=rid, reason=reason)

    def output(self, rid, text, now, final=False):
        self.now = now
        if rid != self.active or self.closed:
            self.emit("response.discarded", {"reason": "response_epoch"}, rid)
            return False
        response = self.responses[rid]
        response["text"] = (response["text"] + text)[:24000]
        response["generation_done"] = final
        self.emit(
            "response.text", {"text": response["text"], "final": final}, rid
        )
        return True

    def audio(
        self,
        rid,
        duration_ms=0,
        completed=False,
        timestamp=None,
        expected_ms=None,
        normal=True,
    ):
        response = self.responses.get(rid)
        if response is not None:
            if timestamp is not None and response["audio_origin_ms"] is None:
                response["audio_origin_ms"] = timestamp - response["audio_ms"]
            response["audio_ms"] += duration_ms
            # Cartesia/TEN reports the sum of integer-truncated chunk durations.
            response["audio_chunk_floor_ms"] += int(duration_ms)
            if completed:
                valid = (
                    normal
                    and isinstance(expected_ms, (int, float))
                    and not isinstance(expected_ms, bool)
                    and math.isfinite(expected_ms)
                    and 0 < expected_ms <= 3600000
                )
                if response["audio_end_received"]:
                    valid = (
                        valid
                        and response["audio_done"]
                        and expected_ms == response["expected_audio_ms"]
                    )
                response["audio_done"] = valid
                response["audio_end_received"] = True
                response["audio_failed"] = (
                    response["audio_failed"] or not normal
                )
                response["expected_audio_ms"] = expected_ms if valid else None
            if (
                response["pending_alignment"]
                and response["audio_origin_ms"] is not None
            ):
                words, response["pending_alignment"] = (
                    response["pending_alignment"],
                    [],
                )
                self.align(rid, words)

    def heard(self, response):
        if response["fully_played"]:
            return response["text"], "browser_completed_estimate"
        words = response["alignment"]
        if words:
            return (
                "".join(
                    w["text"]
                    for w in words
                    if w["end_ms"] <= response["played_ms"]
                ),
                "provider_alignment_browser_cursor",
            )
        if response["audio_failed"] or response["unverified_completion"]:
            return "", "unverified_completion"
        count = int(
            response["played_ms"]
            / 1000
            * self.config["playback"]["chars_per_second"]
        )
        return response["text"][:count], "character_rate_estimate"

    def align(self, rid, words):
        response = self.responses.get(rid) or self.finished.get(rid)
        if response is None:
            return
        valid = []
        for word in words:
            end = word.get("end_ms")
            if not isinstance(word.get("text"), str) or not isinstance(
                end, (int, float)
            ):
                continue
            # Cartesia's TEN adapter emits epoch milliseconds for both audio and
            # words. Browser cursors are relative PCM duration, never epoch time.
            if end > 3600000:
                origin = response["audio_origin_ms"]
                if origin is None:
                    response["pending_alignment"] = (
                        response["pending_alignment"] + [word]
                    )[-5000:]
                    continue
                end -= origin
            if 0 <= end <= 3600000:
                valid.append({"text": word["text"], "end_ms": end})
        self.emit(
            "playback.alignment",
            {
                "received_words": len(words),
                "normalized_words": len(valid),
                "pending_words": len(response["pending_alignment"]),
            },
            rid,
        )
        response["alignment"] = sorted(
            response["alignment"] + valid, key=lambda w: w["end_ms"]
        )[:5000]
        if rid in self.finished:
            heard, precision = self.heard(response)
            for item in self.history:
                if item.get("response_id") == rid:
                    if item["text"] != heard or item["precision"] != precision:
                        item.update(text=heard, precision=precision)
                        self.context_revision += 1
            self.emit(
                "playback.progress",
                {
                    "played_ms": response["played_ms"],
                    "heard_text": heard,
                    "precision": precision,
                    "alignment_updated": True,
                },
                rid,
            )

    def playback(
        self,
        rid,
        played_ms,
        now,
        stopped=False,
        completed=False,
        confirmed=True,
    ):
        self.now = now
        if rid in self.finished and stopped:
            response = self.finished[rid]
            if response["fully_played"]:
                return
            response["played_ms"] = min(
                max(0, played_ms), response["audio_ms"] or 3600000
            )
            heard, precision = self.heard(response)
            for item in self.history:
                if item.get("response_id") == rid:
                    item.update(
                        text=heard, precision=precision, confirmed=confirmed
                    )
                    self.context_revision += 1
            self.emit(
                "playback.stopped",
                {
                    "played_ms": response["played_ms"],
                    "heard_text": heard,
                    "precision": precision,
                    "confirmed": confirmed,
                    "late_ack": True,
                },
                rid,
            )
            return
        if rid not in self.responses or rid not in (self.active, self.stopping):
            return
        response = self.responses[rid]
        cursor = min(max(0, played_ms), response["audio_ms"] or 3600000)
        response["played_ms"] = (
            cursor
            if confirmed and (stopped or completed)
            else max(response["played_ms"], cursor)
        )
        response["fully_played"] = bool(
            completed
            and not stopped
            and confirmed
            and response["generation_done"]
            and response["audio_done"]
            and response["audio_ms"] > 0
            # Accept either a rounded total or the exact sum of per-chunk
            # integer durations used by Cartesia. Do not widen the tolerance:
            # missing/duplicated chunks must also change this independent sum.
            and response["expected_audio_ms"] is not None
            and (
                abs(response["audio_ms"] - response["expected_audio_ms"]) <= 2
                or response["expected_audio_ms"]
                == response["audio_chunk_floor_ms"]
            )
            and response["played_ms"] >= response["audio_ms"] - 30
        )
        response["unverified_completion"] = (
            completed and not response["fully_played"]
        )
        heard, precision = self.heard(response)
        response["precision"] = precision
        self.emit(
            "playback.stopped" if stopped else "playback.progress",
            {
                "played_ms": response["played_ms"],
                "heard_text": heard,
                "precision": precision,
                "confirmed": confirmed,
                "completed": completed,
            },
            rid,
        )
        if stopped or completed:
            if response["mode"] != "backchannel":
                self.history.append(
                    {
                        "role": "assistant",
                        "text": heard,
                        "response_id": rid,
                        "precision": precision,
                        "confirmed": confirmed,
                        "fully_played": response["fully_played"],
                    }
                )
                self.context_revision += 1
            if self.active == rid:
                self.active = None
            if self.stopping == rid:
                self.stopping = None
            self.finished[rid] = response
            while (
                len(self.finished)
                > self.config["playback"]["context_responses"]
            ):
                del self.finished[next(iter(self.finished))]
            del self.responses[rid]

    def context_size(self):
        return len(self.summary) + sum(
            len(item["text"]) for item in self.history
        )

    def begin_compression(self, now):
        cfg = self.config["compression"]
        if (
            not cfg["enabled"]
            or self.closed
            or self.compression_request
            or self.active
            or self.stopping
            or self.pending
            or now - self.compression_attempt < cfg["cooldown_ms"]
            or self.context_size() < cfg["trigger_chars"]
        ):
            return None
        starts = [
            i for i, item in enumerate(self.history) if item["role"] == "user"
        ]
        if len(starts) <= cfg["keep_turns"]:
            return None
        cutoff = starts[-cfg["keep_turns"]]
        # Interrupted assistant text is deliberately excluded: alignment may arrive
        # later. Only full browser-confirmed playback is eligible for summaries.
        source = [
            deepcopy(item)
            for item in self.history[:cutoff]
            if item["role"] == "user" or item.get("fully_played")
        ]
        request = {
            "context_revision": self.context_revision,
            "cutoff": cutoff,
            "source": source,
            "summary": self.summary,
            "kinds": ["compression"],
            "state": {
                "previous_summary": self.summary,
                "confirmed_context": source,
                "context_characters": self.context_size(),
                "retained_turns": cfg["keep_turns"],
            },
        }
        self.compression_request = request
        self.compression_attempt = now
        self.emit(
            "context.decision",
            {
                "phase": "started",
                "context_revision": self.context_revision,
                "characters": self.context_size(),
            },
        )
        return deepcopy(request)

    def compression_current(self, request):
        return (
            not self.closed
            and self.compression_request == request
            and request["context_revision"] == self.context_revision
        )

    def complete_compression(self, request, summary=None, error=None):
        if self.compression_request != request:
            return
        current = self.compression_current(request)
        self.compression_request = None
        if not current:
            self.emit(
                "context.stale",
                {"context_revision": request["context_revision"]},
            )
            return
        if error:
            self.emit(
                "context.failed", {"reason": error, "original_retained": True}
            )
            return
        if summary is None:
            return
        cfg = self.config["compression"]
        old_chars = len(self.summary) + sum(
            len(i["text"]) for i in self.history[: request["cutoff"]]
        )
        if (
            not summary.strip()
            or len(summary) > cfg["max_summary_chars"]
            or len(summary) >= old_chars
        ):
            self.emit(
                "context.failed",
                {"reason": "invalid_summary", "original_retained": True},
            )
            return
        self.summary = summary
        self.history = self.history[request["cutoff"] :]
        self.context_revision += 1
        self.capacity_reached = False
        self.emit(
            "context.applied",
            {
                "context_revision": self.context_revision,
                "summary_characters": len(summary),
                "removed_messages": request["cutoff"],
                "retained_messages": len(self.history),
            },
        )

    def pause(self, now):
        self.now = now
        if self.paused:
            return
        self.paused_timer = deepcopy(self.timer)
        if self.paused_timer:
            self.paused_timer["remaining_ms"] = max(
                0, self.paused_timer["due_ms"] - now
            )
        self.paused = True
        self.epoch += 1
        self.cancel_timer("paused")
        self.stop("paused")
        self.snapshot()

    def resume(self, now):
        self.now = now
        if not self.paused:
            return
        self.paused = False
        self.last_input = now
        self.first_input = now
        if (
            self.paused_timer
            and self.paused_timer["input_revision"] == self.revision
        ):
            self.timer_seq += 1
            self.timer = {
                **self.paused_timer,
                "timer_id": self.timer_seq,
                "due_ms": now + self.paused_timer["remaining_ms"],
                "epoch": self.epoch,
            }
            del self.timer["remaining_ms"]
            self.emit("timer.scheduled", self.timer)
        else:
            self.last_decided = -1
        self.paused_timer = None
        self.snapshot()

    def close(self, now):
        self.now = now
        self.stop("disconnect")
        self.cancel_timer("disconnect")
        self.closed = True
        self.epoch += 1
        self.pending = False
        self.snapshot()
