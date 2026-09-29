"""TEN adapter: reducer + bounded classifier + public LLM/TTS interfaces."""

import asyncio
import json
import math
import os
import struct
import time
import uuid

import aiohttp

from ten_runtime import (
    AsyncExtension,
    AsyncTenEnv,
    AudioFrame,
    Cmd,
    CmdResult,
    Data,
    Loc,
    StatusCode,
)

from .evidence import Evidence
from .executor_client import ExecutorClient
from .config import Config
from .engine import TurnEngine
from .provider import DecisionProvider
from .memory import summarize, voice_request


class EmptyGenerationError(RuntimeError):
    """The provider ended without usable text; safe to retry before output."""


class JevTurnControlExtension(AsyncExtension):
    def __init__(self, name):
        super().__init__(name)
        self.ten_env = None
        self.engine = None
        self.provider = None
        self.started = 0
        self.last_sent = 0
        self.tasks = set()
        self.classification_task = None
        self.generation = None
        self.pump_lock = asyncio.Lock()
        self.asr_segment = 0
        self.asr_final_end = -1
        self.audio_response = None
        self.executor = None
        self.executor_notified = 0
        self.evidence = None

    def record(self, kind, payload, response_id=None):
        if self.evidence:
            self.evidence.write(kind, payload, response_id)

    def now(self):
        return int((time.monotonic() - self.started) * 1000)

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def on_init(self, ten_env: AsyncTenEnv):
        self.ten_env = ten_env
        raw, error = await ten_env.get_property_to_json("")
        if error:
            raise ValueError("cannot read turn configuration")
        self.started = time.monotonic()
        session_id = os.environ.get("JEV_SESSION_ID") or uuid.uuid4().hex
        self.evidence = Evidence(session_id)
        self.engine = TurnEngine(
            Config.load(json.loads(raw or "{}")),
            session_id,
            event_sink=self.record,
        )
        self.record(
            "graph.started",
            {
                "config": self.engine.config.values,
                "engine_monotonic_origin": self.started,
            },
        )
        self.provider = DecisionProvider(self.engine.config, self.record)
        self.executor = ExecutorClient(
            self.engine.emit, self.engine.config["executor"]["enabled"]
        )
        self.engine.snapshot()

    async def on_start(self, ten_env: AsyncTenEnv):
        self.executor.start()
        self.spawn(self.run_clock())
        ten_env.log_info("JEV_EXTENSION_READY stage=decision_mvp")

    async def run_clock(self):
        while not self.engine.closed:
            self.engine.tick(self.now())
            request = self.engine.begin_decision(self.now())
            if request:
                request["response_id"] = self.engine.active
                self.classification_task = self.spawn(self.classify(request))
            compression = self.engine.begin_compression(self.now())
            if compression:
                self.spawn(self.compress(compression))
            self.notify_executor()
            await self.pump()
            await asyncio.sleep(0.02)

    def notify_executor(self):
        state = self.executor.state
        if (
            state.get("status") == "completed"
            and state.get("notify_user")
            and self.engine.config["start"]["enabled"]
            and state.get("current")
            and state.get("version", 0) > self.executor_notified
            and state.get("input_revision") == self.executor.latest_revision
            and not (
                self.engine.active
                or self.engine.stopping
                or self.engine.pending
                or self.engine.paused
                or self.engine.closed
            )
            and self.now() - self.engine.last_input >= 1000
        ):
            self.engine.start("executor_result", executor_state=state)
            if self.engine.active:
                self.executor_notified = state["version"]

    def retire_stale_decision(self):
        """Let a new ASR revision use the slot held by an obsolete start call."""
        request = self.engine.inflight
        if (
            request is None
            or request["revision"] == self.engine.revision
            or request["state"]["assistant_speaking"]
        ):
            return
        if self.classification_task and not self.classification_task.done():
            self.classification_task.cancel()
        self.engine.complete_decision(request, {}, self.now())

    async def classify(self, request):
        self.record("decision.request", request, request.get("response_id"))
        started = time.monotonic_ns()

        def apply_result(answers):
            self.engine.complete_decision(request, answers, self.now())
            self.record(
                "decision.result",
                {
                    "request_id": request["request_id"],
                    "answers": answers,
                    "duration_ns": time.monotonic_ns() - started,
                },
            )

        try:
            await self.provider.decide(request, on_result=apply_result)
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            ValueError,
            KeyError,
            TypeError,
        ) as exc:
            self.record(
                "decision.failure",
                {
                    "request_id": request["request_id"],
                    "error_type": type(exc).__name__,
                    "duration_ns": time.monotonic_ns() - started,
                },
            )
            self.engine.complete_decision(request, {}, self.now(), error=True)
        await self.pump()

    async def compress(self, request):
        try:
            await asyncio.wait_for(
                self.compress_work(request),
                self.engine.config["compression"]["timeout_ms"] / 1000,
            )
        except asyncio.CancelledError:
            self.engine.complete_compression(request, error="cancelled")
            raise
        except Exception:
            # Provider payloads/errors are untrusted; never log their contents.
            self.engine.complete_compression(
                request, error="provider_or_timeout"
            )
        finally:
            if self.engine.compression_request == request:
                self.engine.complete_compression(
                    request, error="incomplete_job"
                )
        await self.pump()

    async def compress_work(self, request):
        answers = await self.provider.decide(request)
        answer = answers["compression"]
        self.engine.emit("context.decision", {"phase": "completed", **answer})
        if not self.engine.compression_current(request):
            self.engine.complete_compression(request)
            return
        if (
            answer["label"] != "compress"
            or answer["score"] < self.engine.config["compression"]["threshold"]
        ):
            self.engine.complete_compression(request)
            return
        self.engine.emit(
            "context.summary", {"phase": "started", "provider": "groq"}
        )
        await self.pump()
        if self.engine.config["provider"]["name"] == "mock":
            summary = (
                "Synthetic memory: "
                + " ".join(item["text"][:80] for item in request["source"])[
                    :500
                ]
            )
        else:
            summary = await summarize(request, self.engine.config)
        self.engine.complete_compression(request, summary=summary)

    async def send_data(self, name, payload, destination):
        data = Data.create(name)
        data.set_property_from_json(None, json.dumps(payload))
        data.set_dests([Loc("", "", destination)])
        await self.ten_env.send_data(data)

    async def pump(self):
        async with self.pump_lock:
            if self.engine.config["transport"]["enabled"]:
                for event in list(self.engine.events):
                    if event["seq"] > self.last_sent:
                        self.last_sent = event["seq"]
                        await self.send_data(
                            "jev_event", event, "websocket_server"
                        )
            for action in self.engine.drain_actions():
                if action["type"] == "response.cancel":
                    if self.generation:
                        self.generation.cancel()
                    self.audio_response = None
                    if self.engine.config["provider"]["name"] != "mock":
                        self.spawn(self.abort(action["response_id"]))
                elif action["type"] == "response.start":
                    self.generation = self.spawn(self.generate(action))

    async def abort(self, rid):
        # TTS flush is sent before waiting for any LLM acknowledgment.
        await self.send_data("tts_flush", {"flush_id": rid}, "tts")
        command = Cmd.create("abort")
        command.set_dests([Loc("", "", "llm")])
        command.set_property_string("request_id", rid)
        await self.ten_env.send_cmd(command)

    async def generate(self, action):
        rid = action["response_id"]
        try:
            if self.engine.config["provider"]["name"] == "mock":
                text = action["phrase"] or (
                    "Could you finish that thought?"
                    if action["mode"] == "clarify"
                    else "This is a synthetic response for playback testing."
                )
                self.engine.output(rid, text, self.now(), final=True)
                if self.engine.config["transport"]["mock_audio"]:
                    for _ in range(
                        10 if action["mode"] == "backchannel" else 100
                    ):
                        if rid != self.engine.active:
                            break
                        await self.mock_audio(rid)
                        await asyncio.sleep(0.04)
                self.engine.audio(
                    rid,
                    completed=True,
                    expected_ms=self.engine.responses.get(rid, {}).get(
                        "audio_ms"
                    ),
                )
                self.engine.emit(
                    "response.audio_completed", {"synthetic": True}, rid
                )
                await self.pump()
                return
            if action["mode"] == "backchannel":
                self.engine.output(
                    rid, action["phrase"], self.now(), final=True
                )
                await self.tts(rid, action["phrase"], True)
                return
            for attempt in range(2):
                try:
                    await self.generate_live(action)
                    return
                except Exception as exc:
                    if rid != self.engine.active:
                        return
                    self.engine.emit(
                        "generation.failed",
                        {
                            "attempt": attempt + 1,
                            "code": (
                                "llm_empty_output"
                                if isinstance(exc, EmptyGenerationError)
                                else "llm_request_failed"
                            ),
                        },
                        rid,
                    )
                    if (
                        self.engine.responses[rid]["tts_submitted"]
                        or self.engine.responses[rid]["audio_ms"] > 0
                    ):
                        raise
                    # Discard only text that has never been handed to TTS.
                    self.engine.responses[rid]["text"] = ""
                    self.engine.output(rid, "", self.now())
                    if attempt == 0:
                        self.engine.emit(
                            "generation.retry",
                            {"attempt": 2, "tools_enabled": False},
                            rid,
                        )
                        continue
            text = "Sorry, I could not generate that reply. Please try again."
            self.engine.output(rid, text, self.now(), final=True)
            self.engine.emit(
                "generation.fallback", {"audible_if_tts_available": True}, rid
            )
            await self.tts(rid, text, True)
        except (
            Exception
        ):  # Vendor failures must not leak credentials or payloads.
            self.engine.emit(
                "error", {"code": "generation_failed", "recoverable": True}, rid
            )
            if rid == self.engine.active:
                self.engine.stop("generation_failed")
            await self.pump()

    async def generate_live(self, action):
        # Import lazily so the offline graph needs only the public runtime.
        from ten_ai_base.struct import (
            parse_llm_response,
            LLMResponseMessageDelta,
            LLMResponseMessageDone,
        )

        rid = action["response_id"]
        request = voice_request(
            action,
            self.engine.config,
            self.executor.state if self.executor else None,
        )
        self.engine.emit(
            "context.request",
            {
                "context_revision": action["context_revision"],
                "history_messages": len(request["messages"]) - 1,
                "history_characters": sum(
                    len(m["content"]) for m in request["messages"][:-1]
                ),
                "summary_characters": len(action.get("summary", "")),
            },
            rid,
        )
        self.record("llm.request", request, rid)
        command = Cmd.create("chat_completion")
        command.set_dests([Loc("", "", "llm")])
        command.set_property_from_json(None, json.dumps(request))
        fragment = ""
        generated = ""
        done = False
        async for result, error in self.ten_env.send_cmd_ex(command):
            if rid != self.engine.active:
                return
            if error or (result and result.get_status_code() != StatusCode.OK):
                raise RuntimeError("LLM failed")
            if result is None or result.is_final():
                continue
            raw, _ = result.get_property_to_json(None)
            self.record("llm.stream", json.loads(raw), rid)
            response = parse_llm_response(raw)
            if isinstance(response, LLMResponseMessageDelta):
                text = self.stream_suffix(
                    generated, response.content, response.delta
                )
                if not self.engine.output(rid, text, self.now()):
                    return
                generated += text
                fragment += text
                if fragment.strip() and (
                    any(
                        mark in fragment
                        for mark in (".", "?", "!", "。", "？", "！")
                    )
                    or len(fragment) >= 100
                ):
                    await self.tts(rid, fragment, False)
                    fragment = ""
            elif isinstance(response, LLMResponseMessageDone):
                text = self.stream_suffix(generated, response.content, "")
                if text:
                    if not self.engine.output(rid, text, self.now()):
                        return
                    generated += text
                    fragment += text
                if not generated.strip():
                    raise EmptyGenerationError("empty LLM response")
                done = True
                self.engine.output(rid, "", self.now(), final=True)
                await self.tts(rid, fragment, True)
                fragment = ""
        if not done:
            if not generated.strip():
                raise EmptyGenerationError("empty LLM stream")
            raise RuntimeError("incomplete LLM stream")
        # Agent EOS is never used as input turn completion.

    @staticmethod
    def stream_suffix(generated, content, delta):
        """Recover skipped deltas from cumulative content; ignore late prefixes."""
        if not content:
            return delta or ""
        if content.startswith(generated):
            return content[len(generated) :]
        if generated.startswith(content):
            return ""
        # A rewrite is not append-only: do not speak or memorize corrupt text.
        raise ValueError("non-prefix LLM stream revision")

    async def tts(self, rid, text, final):
        if rid == self.engine.active:
            if text.strip():
                self.engine.responses[rid]["tts_submitted"] = True
            self.record(
                "tts.input", {"text": text, "text_input_end": final}, rid
            )
            await self.send_data(
                "tts_text_input",
                {
                    "request_id": rid,
                    "text": text,
                    "text_input_end": final,
                    "metadata": {
                        "session_id": self.engine.session_id,
                        "response_id": rid,
                    },
                },
                "tts",
            )

    async def mock_audio(self, rid):
        # Recognizable synthetic test tone; not generated speech.
        frame = AudioFrame.create("pcm_frame")
        frame.set_sample_rate(16000)
        frame.set_number_of_channels(1)
        frame.set_bytes_per_sample(2)
        frame.set_samples_per_channel(640)
        frame.alloc_buf(1280)
        buf = frame.lock_buf()
        buf[:] = b"".join(
            struct.pack(
                "<h", int(500 * math.sin(2 * math.pi * 440 * i / 16000))
            )
            for i in range(640)
        )
        frame.unlock_buf(buf)
        frame.set_property_from_json(
            "metadata", json.dumps({"response_id": rid, "synthetic": True})
        )
        frame.set_dests([Loc("", "", "websocket_server")])
        self.engine.audio(rid, 40)
        await self.ten_env.send_audio_frame(frame)

    async def on_audio_frame(self, ten_env: AsyncTenEnv, frame: AudioFrame):
        metadata, error = frame.get_property_to_json("metadata")
        meta = json.loads(metadata) if not error and metadata else {}
        request_id, _ = frame.get_property_string("request_id")
        rid = meta.get("response_id") or request_id
        if self.evidence:
            buf = frame.lock_buf()
            pcm = bytes(buf)
            frame.unlock_buf(buf)
            self.evidence.audio(
                pcm,
                {
                    **meta,
                    "sample_rate": frame.get_sample_rate(),
                    "channels": frame.get_number_of_channels(),
                    "bytes_per_sample": frame.get_bytes_per_sample(),
                    "timestamp": frame.get_timestamp(),
                    "accepted": bool(rid and rid == self.engine.active),
                },
                rid,
            )
        if not rid or rid != self.engine.active:
            return
        self.engine.audio(
            rid,
            frame.get_samples_per_channel() / frame.get_sample_rate() * 1000,
            timestamp=frame.get_timestamp(),
        )
        meta["response_id"] = rid
        frame.set_property_from_json("metadata", json.dumps(meta))
        frame.set_dests([Loc("", "", "websocket_server")])
        await ten_env.send_audio_frame(frame)

    async def on_data(self, _ten_env: AsyncTenEnv, data: Data):
        raw, error = data.get_property_to_json(None)
        if error:
            return
        try:
            payload = json.loads(raw)
            if self.evidence:
                self.record(
                    "graph.input",
                    {"name": data.get_name(), "data": payload},
                    payload.get("response_id", payload.get("request_id")),
                )
            self.handle_data(data.get_name(), payload)
        except (ValueError, TypeError, KeyError):
            self.engine.emit(
                "error", {"code": "invalid_input", "recoverable": True}
            )
        await self.pump()

    def handle_data(self, name, payload):
        now = self.now()
        if name in ("asr_result", "jev_asr"):
            if (
                name == "jev_asr"
                and self.engine.config["provider"]["name"] != "mock"
            ):
                return
            text, final = payload["text"], payload.get(
                "final", payload.get("is_final", False)
            )
            if not isinstance(text, str) or not isinstance(final, bool):
                raise ValueError("invalid ASR")
            if name == "asr_result":
                start_ms, duration_ms = payload.get("start_ms"), payload.get(
                    "duration_ms"
                )
                if isinstance(start_ms, (int, float)) and isinstance(
                    duration_ms, (int, float)
                ):
                    end_ms = start_ms + duration_ms
                    if end_ms <= self.asr_final_end:
                        return
                    if final:
                        self.asr_final_end = end_ms
            segment = payload.get("segment_id", f"asr-{self.asr_segment}")
            self.engine.input(text, final, now, segment)
            self.retire_stale_decision()
            if final and self.executor and not self.engine.closed:
                self.executor.submit(
                    self.engine.revision, text, self.engine.history
                )
            if name == "asr_result" and final:
                self.asr_segment += 1
        elif name == "jev_playback":
            if not isinstance(payload.get("response_id"), str) or any(
                not isinstance(payload.get(flag, False), bool)
                for flag in ("stopped", "completed")
            ):
                raise ValueError("invalid playback feedback")
            cursor = payload["played_ms"]
            if not isinstance(cursor, (int, float)) or not math.isfinite(
                cursor
            ):
                raise ValueError("invalid playback cursor")
            self.engine.playback(
                payload["response_id"],
                cursor,
                now,
                stopped=payload.get("stopped", False),
                completed=payload.get("completed", False),
            )
        elif name == "jev_control":
            action = payload["action"]
            if action == "snapshot":
                self.engine.snapshot()
            elif action == "stop":
                rid = payload.get("response_id")
                reason = (
                    "buffer_limit"
                    if payload.get("reason") == "buffer_limit"
                    else "manual_stop"
                )
                if (reason == "buffer_limit" and not rid) or (
                    rid is not None and rid != self.engine.active
                ):
                    return
                self.engine.now = now
                self.engine.stop(reason)
            elif action == "pause":
                self.engine.pause(now)
            elif action == "resume":
                self.engine.resume(now)
            elif action == "disconnect":
                self.engine.close(now)
            else:
                raise ValueError("unsupported session control")
        elif name == "tts_audio_start":
            rid = payload.get("request_id")
            if rid == self.engine.active:
                self.audio_response = rid
        elif name == "tts_audio_end":
            rid = payload.get("request_id")
            if rid == self.engine.active:
                # TTSAudioEndReason.REQUEST_END=1; INTERRUPTED=2; ERROR=3.
                normal = payload.get("reason") == 1
                self.engine.audio(
                    rid,
                    completed=True,
                    expected_ms=payload.get("request_total_audio_duration_ms"),
                    normal=normal,
                )
                self.engine.emit(
                    "response.audio_completed",
                    {
                        "synthetic": False,
                        "normal_end": normal,
                        "expected_audio_ms": payload.get(
                            "request_total_audio_duration_ms"
                        ),
                    },
                    rid,
                )
        elif name == "tts_text_result":
            rid = payload.get("request_id")
            words = [
                {
                    "text": w.get("word", ""),
                    "end_ms": w.get("start_ms", 0) + w.get("duration_ms", 0),
                }
                for w in payload.get("words", [])
            ]
            self.engine.now = now
            self.engine.align(rid, words)

    async def on_cmd(self, ten_env: AsyncTenEnv, cmd: Cmd):
        name = cmd.get_name()
        result = CmdResult.create(StatusCode.OK, cmd)
        if name == "jev_ping":
            nonce, _ = cmd.get_property_string("nonce")
            result.set_property_string("nonce", nonce)
            result.set_property_string("stage", "decision_mvp")
        elif name == "jev_inspect":
            result.set_property_from_json(
                "snapshot", json.dumps(self.engine.snapshot())
            )
        elif name == "jev_input":
            raw, _ = cmd.get_property_to_json(None)
            self.handle_data("jev_asr", json.loads(raw))
            result.set_property_int("input_revision", self.engine.revision)
        else:
            result = CmdResult.create(StatusCode.ERROR, cmd)
        await ten_env.return_result(result)
        await self.pump()

    async def on_stop(self, ten_env: AsyncTenEnv):
        if self.engine:
            rid = self.engine.active or self.engine.stopping
            self.engine.close(self.now())
            if self.generation:
                self.generation.cancel()
            if rid and self.engine.config["provider"]["name"] != "mock":
                try:
                    await asyncio.wait_for(self.abort(rid), 1)
                except Exception:
                    ten_env.log_info("JEV_SHUTDOWN_ABORT_UNAVAILABLE")
            self.engine.drain_actions()
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
        if self.executor:
            await self.executor.close()
        if self.provider:
            await self.provider.close()
        if self.evidence:
            self.record("graph.closed", {})
            await asyncio.to_thread(self.evidence.close)
        ten_env.log_info("JEV_EXTENSION_STOPPED")
