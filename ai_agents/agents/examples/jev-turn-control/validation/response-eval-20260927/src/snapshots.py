"""Frozen-score checkpoints; metadata and future gold never enter model state."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def build():
    prompts = {
        p: json.loads(
            (ROOT / "manifests" / f"prompt-{p}.json").read_text(
                encoding="utf-8"
            )
        )
        for p in ("A", "B")
    }
    sequences = [
        json.loads(line)
        for line in (ROOT / "data/new-sequences.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    jobs = []
    for seq in sequences:
        events = seq["events"]
        final = events[-1]
        checkpoints = [(final, 120, "primary")]
        checkpoints += [
            (final, gap, "silence") for gap in (300, 500, 1000, 2000)
        ]
        # Every stable prefix is measured; sequence replay uses original times.
        checkpoints += [
            (event, 120, "prefix")
            for event, after in zip(events, events[1:])
            if after["at_ms"] - event["at_ms"] > 120
        ]
        history = [
            {"role": h["role"], "text": h.get("content", h.get("text", ""))}
            for h in seq["history"]
        ]
        for event, gap, checkpoint in checkpoints:
            state = {
                "input_text": event["text"],
                "asr_final": event["final"],
                "assistant_speaking": False,
                "heard_context": history,
                "older_context_summary": "",
                "silence_ms": gap,
            }
            for prompt, questions in prompts.items():
                jobs.append(
                    {
                        "id": f"{seq['id']}/{event['at_ms']}/{gap}/{prompt}/start",
                        "sequence_id": seq["id"],
                        "family": seq["family"],
                        "split": seq["split"],
                        "scenario": seq["scenario"],
                        "source_type": seq["source_type"],
                        "prompt": prompt,
                        "kind": "start",
                        "checkpoint": checkpoint,
                        "at_ms": event["at_ms"] + gap,
                        "gold_reply": seq["opportunity_ms"] is not None
                        and event["at_ms"] + gap >= seq["opportunity_ms"],
                        "state": state,
                        "questions": {"start": questions["start"]},
                    }
                )
        if seq["initial_assistant_speaking"]:
            state = {
                "input_text": final["text"],
                "asr_final": final["final"],
                "assistant_speaking": True,
                "heard_context": history,
                "older_context_summary": "",
                "silence_ms": 120,
            }
            jobs.append(
                {
                    "id": seq["id"] + "/stop",
                    "sequence_id": seq["id"],
                    "family": seq["family"],
                    "split": seq["split"],
                    "scenario": seq["scenario"],
                    "source_type": seq["source_type"],
                    "prompt": "A=B",
                    "kind": "stop",
                    "checkpoint": "primary",
                    "gold_stop": seq["stop_expected"],
                    "state": state,
                    "questions": {"stop": prompts["A"]["stop"]},
                }
            )
    dest = ROOT / "data/snapshots.jsonl"
    blob = "\n".join(canonical(j) for j in jobs) + "\n"
    if dest.exists():
        assert dest.read_text(encoding="utf-8") == blob
    else:
        dest.write_text(blob)
    print(
        json.dumps(
            {
                "jobs": len(jobs),
                "sha256": hashlib.sha256(blob.encode()).hexdigest(),
                "split_jobs": {
                    s: sum(j["split"] == s for j in jobs)
                    for s in ("development", "validation", "holdout")
                },
            }
        )
    )


if __name__ == "__main__":
    build()
