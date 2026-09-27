"""Clock-injected controller replay. Synthetic output/ACK timings are explicit."""

import concurrent.futures
import importlib
import math
import sys
import types
from pathlib import Path
from remote import Collector


def engine_class(path, name):
    package = types.ModuleType(name)
    package.__path__ = [str(path)]
    sys.modules[name] = package
    return (
        importlib.import_module(name + ".engine").TurnEngine,
        importlib.import_module(name + ".config").Config,
    )


class Replay:
    def __init__(self, collector, sources, prompts):
        self.collector = collector
        self.sources = sources
        self.prompts = prompts

    def run(self, spec):
        seq = spec["sequence"]
        Engine, Config = self.sources[spec["engine"]]
        config = Config.load(
            {
                "start": {"threshold": spec["threshold"], "score_mode": "top"},
                "observation": {"include_text": True, "buffer_limit": 4096},
            }
        )
        engine = Engine(config, session_id=seq["id"])
        history = [
            {"role": h["role"], "text": h.get("content", h.get("text", ""))}
            for h in seq["history"]
        ]
        engine.history = [dict(h) for h in history]
        finish = {}
        original_rid = None
        if seq["initial_assistant_speaking"]:
            engine.start("answer")
            original_rid = engine.active
            engine.history = history.copy()
            self.audio_fixture(engine, original_rid, seq["assistant_end_ms"])
            finish[original_rid] = seq["assistant_end_ms"]
            engine.drain_actions()
            engine.events.clear()
        events = sorted(seq["events"], key=lambda e: e["at_ms"])
        index, now = 0, 0
        due = {}
        refs, output_events = [], []
        last_seq = engine.seq
        probed_revisions = set()
        horizon = seq["horizon_ms"]
        # A 20 ms controller tick is a declared replay assumption, not observed.
        while now <= horizon:
            while index < len(events) and events[index]["at_ms"] <= now:
                event = events[index]
                engine.input(
                    event["text"],
                    event["final"],
                    event["at_ms"],
                    event.get("segment_id", "focal"),
                )
                index += 1
            for rid, end in list(finish.items()):
                if end <= now:
                    if rid == engine.active:
                        engine.playback(
                            rid,
                            engine.responses[rid]["audio_ms"],
                            now,
                            completed=True,
                        )
                    finish.pop(rid)
            if engine.stopping:
                # Immediate next tick stop ACK, no network/audio latency claim.
                rid = engine.stopping
                engine.playback(rid, 0, now, stopped=True)
                finish.pop(rid, None)
            if due and due["at_ms"] <= now:
                engine.complete_decision(
                    due["request"], due["answers"], now, error=due["error"]
                )
                due = {}
            engine.tick(now)
            interval = spec.get("silence_recheck_ms")
            if (
                interval
                and engine.pending
                and not engine.active
                and not engine.stopping
                and not engine.inflight
                and engine.revision not in probed_revisions
                and now - engine.last_input >= interval
                and not (
                    engine.timer
                    and engine.timer["label"] in ("answer", "clarify")
                )
            ):
                engine.last_decided = -1
                probed_revisions.add(engine.revision)
            request = engine.begin_decision(now)
            if request:
                questions = {
                    kind: self.prompts[spec["prompt"]][kind]
                    for kind in request["kinds"]
                }
                rows = {}
                providers = ["jev", "scaledown"]
                if request["request_id"] % 2:
                    providers.reverse()
                for provider in providers:
                    rows[provider] = self.collector.request(
                        provider, request["state"], questions
                    )
                row = rows[spec["provider"]]
                error = row["error"] or (
                    "runtime_timeout" if row["runtime_timeout_800ms"] else None
                )
                answers = {}
                if not error:
                    answers = {
                        kind: {
                            "label": a["choice"],
                            "score": a["probabilities"][a["choice"]],
                            "probabilities": a["probabilities"],
                        }
                        for kind, a in row["response"]["answers"].items()
                    }
                due = {
                    "at_ms": now + min(800, math.ceil(row["latency_ms"])),
                    "request": request,
                    "answers": answers,
                    "error": error,
                }
                refs.append(
                    {
                        "at_ms": now,
                        "request": request,
                        "refs": {p: r["cache_key"] for p, r in rows.items()},
                        "completion_ms": due["at_ms"],
                        "error": error,
                    }
                )
            for action in engine.drain_actions():
                if action["type"] == "response.start":
                    rid = action["response_id"]
                    # No generated words or acoustic output are invented.
                    self.audio_fixture(engine, rid, 1200)
                    finish[rid] = now + 1200
            fresh = [e for e in engine.events if e["seq"] > last_seq]
            output_events.extend(fresh)
            if fresh:
                last_seq = fresh[-1]["seq"]
            # Preserve exact ASR times even between 20 ms ticks.
            next_event = (
                events[index]["at_ms"] if index < len(events) else horizon + 1
            )
            now = min(now + 20, next_event) if next_event > now else now + 20
        starts = [
            e
            for e in output_events
            if e["type"] == "response.started"
            and e["response_id"] != original_rid
        ]
        opportunity = seq["opportunity_ms"]
        early = [
            e
            for e in starts
            if opportunity is None or e["relative_time_ms"] < opportunity
        ]
        timely = [
            e
            for e in starts
            if opportunity is not None and e["relative_time_ms"] >= opportunity
        ]
        result = {
            "record_type": "sequence",
            "id": seq["id"],
            "family": seq["family"],
            "split": seq["split"],
            "scenario": seq["scenario"],
            "source_type": seq["source_type"],
            "engine": spec["engine"],
            "provider": spec["provider"],
            "arm": spec["arm"],
            "threshold": spec["threshold"],
            "silence_recheck_ms": interval,
            "opportunity_ms": opportunity,
            "missed": opportunity is not None and not timely,
            "early_starts": len(early),
            "starts": [
                {"at_ms": e["relative_time_ms"], "mode": e["payload"]["mode"]}
                for e in starts
            ],
            "delay_ms": (
                timely[0]["relative_time_ms"] - opportunity if timely else None
            ),
            "horizon_ms": horizon,
            "stale": sum(
                e["type"] == "decision.discarded" for e in output_events
            ),
            "provider_failures": sum(bool(r["error"]) for r in refs),
            "requests": refs,
            "events": output_events,
        }
        self.collector.emit(result)
        return result

    @staticmethod
    def audio_fixture(engine, rid, duration):
        engine.output(rid, "", engine.now, final=True)
        engine.audio(rid, duration)
        engine.audio(rid, 0, completed=True, expected_ms=duration)


def main(payload):
    root = Path("/work/replay")
    for name, content in payload["files"].items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    sources = {
        name: engine_class(root / name, "eval_" + name)
        for name in ("base", "fixed")
    }
    collector = Collector(payload.pop("keys"))
    runner = Replay(collector, sources, payload["prompts"])
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(runner.run, payload["specs"]))
