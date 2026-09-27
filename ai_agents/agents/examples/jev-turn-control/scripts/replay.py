"""Deterministic JSONL replay, independent of TEN, network and provider keys.

Input records: {at_ms, type, ...}. Types: asr, decision, tick, output,
playback, pause, resume, disconnect. Decision records explicitly supply
answers; they are synthetic/replayed evidence, not live inference.
"""

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import types


def load_engine():
    root = (
        Path(__file__).resolve().parents[3]
        / "ten_packages/extension/jev_turn_control_python"
    )
    package = types.ModuleType("jev_replay")
    package.__path__ = [str(root)]
    sys.modules["jev_replay"] = package
    for name in ("config", "engine"):
        spec = importlib.util.spec_from_file_location(
            f"jev_replay.{name}", root / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return (
        sys.modules["jev_replay.engine"].TurnEngine,
        sys.modules["jev_replay.config"].Config,
    )


def replay(records):
    engine_type, config_type = load_engine()
    engine = engine_type(
        config_type.load({"observation": {"include_text": True}}),
        "replay-synthetic",
    )
    last_seq = 0
    request = None
    for record in records:
        now = record["at_ms"]
        if now < engine.now:
            raise ValueError("replay time must be monotonic")
        kind = record["type"]
        if kind == "asr":
            engine.input(
                record["text"],
                record.get("final", False),
                now,
                record.get("segment_id", "default"),
            )
        elif kind == "decision.started":
            request = engine.begin_decision(now)
            if request is None:
                raise ValueError("decision not eligible")
        elif kind == "decision.completed":
            engine.complete_decision(
                request, record["answers"], now, record.get("error")
            )
        elif kind == "tick":
            engine.tick(now)
        elif kind == "output":
            engine.output(
                engine.active, record["text"], now, record.get("final", False)
            )
        elif kind == "playback":
            engine.playback(
                record.get("response_id") or engine.active or engine.stopping,
                record["played_ms"],
                now,
                stopped=record.get("stopped", False),
                completed=record.get("completed", False),
            )
        elif kind in ("pause", "resume"):
            getattr(engine, kind)(now)
        elif kind == "disconnect":
            engine.close(now)
        else:
            raise ValueError("unsupported replay event")
        for event in engine.events:
            if event["seq"] > last_seq:
                yield event
                last_seq = event["seq"]
        engine.drain_actions()
    yield engine.snapshot()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    records = [
        json.loads(line)
        for line in args.input.read_text().splitlines()
        if line.strip()
    ]
    for event in replay(records):
        print(json.dumps(event, ensure_ascii=False))


if __name__ == "__main__":
    main()
