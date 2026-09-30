"""Regressions for leakage, selected-label gating, timing, and seen failure."""

import json
from pathlib import Path
from analyze import gate, wilson
from replay import Replay, engine_class
from seen_regression import case

ROOT = Path(__file__).resolve().parents[1]


def test_selected_label_not_argmax():
    call = {
        "error": None,
        "runtime_timeout_800ms": False,
        "response": {
            "answers": {
                "start": {
                    "choice": "answer",
                    "probabilities": {
                        "answer": 0.42,
                        "continuation": 0.43,
                        "clarify": 0.12,
                        "ignore": 0.02,
                        "explicit_wait": 0.01,
                    },
                }
            }
        },
    }
    assert gate(call, "start", 0.42)
    assert not gate(call, "start", 0.47)
    call["runtime_timeout_800ms"] = True
    assert not gate(call, "start", 0.42)


def test_family_split_and_no_gold_in_model_state():
    families = {}
    sequences = [
        json.loads(s)
        for s in (ROOT / "data/new-sequences.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(sequences) == 108
    for seq in sequences:
        assert (
            seq["family"] not in families
            or families[seq["family"]] == seq["split"]
        )
        families[seq["family"]] = seq["split"]
    for job in map(
        json.loads,
        (ROOT / "data/snapshots.jsonl")
        .read_text(encoding="utf-8")
        .splitlines(),
    ):
        assert set(job["state"]) == {
            "input_text",
            "asr_final",
            "assistant_speaking",
            "heard_context",
            "older_context_summary",
            "silence_ms",
        }
        assert job["split"] == families[job["family"]]


def test_zero_observations_does_not_imply_zero_risk():
    assert wilson(0, 0) is None
    lower, upper = wilson(0, 7)
    assert lower == 0 and 0.35 < upper < 0.36


def test_seen_failure_is_fixed_without_threshold_change():
    assert case("base")["starts"] == []
    fixed = case("fixed")["starts"]
    assert fixed == [{"at_ms": 183254, "mode": "clarify"}]
    assert case("base", 0.42)["starts"] == [{"at_ms": 178754, "mode": "answer"}]


class Stub:
    """No network: preserve supplied continuation choice and fixed 300ms delay."""

    def __init__(self):
        self.states = []

    def request(self, provider, state, questions):
        self.states.append((provider, dict(state)))
        return {
            "error": None,
            "runtime_timeout_800ms": False,
            "latency_ms": 300,
            "cache_key": "stub-only",
            "response": {
                "answers": {
                    k: {
                        "choice": "continuation",
                        "probabilities": {
                            label: float(label == "continuation")
                            for label in q["criteria"]
                        },
                    }
                    for k, q in questions.items()
                }
            },
        }

    def emit(self, row):
        pass


def test_asr_event_time_and_stale_result_preserved():
    seq = {
        "id": "clock-test",
        "family": "clock-test",
        "split": "development",
        "scenario": "hesitation",
        "source_type": "test-only",
        "history": [],
        "initial_assistant_speaking": False,
        "events": [
            {
                "at_ms": 203,
                "text": "And I",
                "final": False,
                "segment_id": "same",
            },
            {
                "at_ms": 453,
                "text": "And I want to",
                "final": True,
                "segment_id": "same",
            },
        ],
        "horizon_ms": 6100,
        "opportunity_ms": None,
    }
    stub = Stub()
    engine, config = engine_class(ROOT / "reference", "clock_test_base")
    prompt = json.loads(
        (ROOT / "manifests/prompt-A.json").read_text(encoding="utf-8")
    )
    runner = Replay(stub, {"base": (engine, config)}, {"A": prompt})
    result = runner.run(
        {
            "sequence": seq,
            "engine": "base",
            "provider": "jev",
            "prompt": "A",
            "arm": "A",
            "threshold": 0.47,
        }
    )
    inputs = [
        e["relative_time_ms"]
        for e in result["events"]
        if e["type"] == "asr.updated"
    ]
    assert inputs == [203, 453]
    assert result["stale"] >= 1
    assert result["starts"][0]["at_ms"] >= 5453
    assert [s for p, s in stub.states if p == "jev"] == [
        s for p, s in stub.states if p == "scaledown"
    ]
