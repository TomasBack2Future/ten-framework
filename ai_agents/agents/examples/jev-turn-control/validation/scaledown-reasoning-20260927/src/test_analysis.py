"""Regressions for selected-label gating and deadline-aware accuracy accounting."""

from analyze import gate, grade
from audit import main as audit


def test_full_paired_wire_evidence():
    audit()


def test_sum_cannot_promote_a_continuation_choice():
    profile = {
        "start": {"threshold": 0.47, "score_mode": "answer_plus_clarify"}
    }
    answer = {
        "choice": "continuation",
        "probabilities": {"continuation": 0.4, "answer": 0.35, "clarify": 0.25},
    }
    assert not gate(answer, "start", profile)
    answer["choice"] = "answer"
    assert gate(answer, "start", profile)


def test_late_success_not_counted_as_runtime_success():
    profile = {
        "start": {"threshold": 0.47, "score_mode": "answer_plus_clarify"}
    }
    case = {"gold_type": "floor_binary", "gold": {"start": True}}
    row = {
        "error": None,
        "lane": "controlled",
        "arm": "sd",
        "over_800ms": True,
        "answers": {
            "start": {
                "choice": "answer",
                "probabilities": {"answer": 0.9, "clarify": 0.1},
            }
        },
    }
    score = grade(row, case, {"jev": profile})
    assert score["binary_semantic_correct"] == 1
    assert score["binary_gate_correct"] == 1
    assert score["binary_deadline_correct"] == 0


def test_provider_failure_not_credited_as_correct_negative():
    case = {"gold_type": "floor_binary", "gold": {"start": False}}
    score = grade({"error": "HTTP_500"}, case, {})
    assert score["binary_n"] == 1
    assert score["binary_deadline_correct"] == 0
