"""Recorded debate regression and bounded wait lifecycle, with fixed outputs."""

import json
from pathlib import Path

import pytest

from test_engine import answer, make, start
from test_input_lifecycle import decide

RECORD = json.loads(
    (Path(__file__).parent / "fixtures/debate_wait.json").read_text()
)


def wait_input(engine, text="Wait until I say go."):
    engine.input(text, True, 0, "s1")
    decide(engine, 120, "explicit_wait")
    return engine.timer["due_ms"]


def recheck(engine, due):
    engine.tick(due)
    assert not engine.active and engine.pending
    request = engine.begin_decision(due)
    assert request and request["state"]["wait_recheck"]
    assert request["state"]["silence_ms"] >= due - engine.last_input
    return request


@pytest.mark.parametrize(
    "result",
    RECORD["silence_results"],
    ids=lambda r: f'{r["provider"]}-{r["repeat"]}',
)
def test_recorded_debate_retained_and_actual_recheck_results_are_bounded(
    result,
):
    engine = make(provider={"profile": "tuned", "name": result["provider"]})
    engine.history = RECORD["state"]["heard_context"].copy()
    text = RECORD["state"]["input_text"]
    engine.input(text, True, 0, "s1")
    request = engine.begin_decision(121)
    engine.complete_decision(request, RECORD["initial_answers"], 209)
    assert engine.timer["label"] == "explicit_wait"
    request = recheck(engine, 4210)
    assert request["state"]["input_text"] == text
    assert not any(i["text"] == text for i in engine.history)
    engine.complete_decision(request, result["parsed"], 4510)
    engine.tick(4510)
    engine.tick(5000)
    assert engine.active
    probabilities = result["parsed"]["start"]["probabilities"]
    effective = probabilities["answer"] + probabilities["clarify"]
    permitted = (
        result["parsed"]["start"]["label"] == "answer"
        and effective >= engine.config["start"]["threshold"]
    )
    expected = "answer" if permitted else "clarify"
    assert engine.responses[engine.active]["mode"] == expected
    assert sum(i["text"] == text for i in engine.history) == 1
    action = [a for a in engine.actions if a["type"] == "response.start"][-1]
    assert action["input_text"] == text
    assert "initiated multiple wars" in action["input_text"]


def test_persistent_wait_has_two_silence_checks_then_parks_with_content():
    engine = make()
    text = "Do not respond until I say go. My completed argument is final."
    due = wait_input(engine, text)
    for attempt in range(2):
        request = recheck(engine, due)
        assert engine.wait_rechecks == attempt + 1
        engine.complete_decision(
            request, {"start": answer("explicit_wait")}, due + 50
        )
        due += 4050
    requests = engine.request_seq
    for now in range(due, due + 60000, 20):
        engine.tick(now)
        assert engine.begin_decision(now) is None
    assert engine.request_seq == requests
    assert engine.pending and engine.text == text and not engine.active
    engine.input("Go, answer now.", True, due + 60100, "s2")
    request = decide(engine, due + 60220, "answer")
    assert request["state"]["input_text"] == text + " Go, answer now."
    engine.tick(due + 60600)
    assert engine.active
    assert len([i for i in engine.history if i["role"] == "user"]) == 1


@pytest.mark.parametrize("policy", ["hold", "bounded_wait"])
def test_recheck_errors_are_bounded_and_never_expire_explicit_wait(policy):
    engine = make(provider={"failure_policy": policy})
    due = wait_input(engine)
    for _ in range(2):
        request = recheck(engine, due)
        engine.complete_decision(request, {}, due + 50, error=True)
        due += 4050
    for now in (due, due + 10000, due + 100000):
        engine.tick(now)
        assert engine.begin_decision(now) is None
    assert engine.pending and not engine.active
    engine.input("Go, tell me now.", True, due + 100100, "s2")
    decide(engine, due + 100220, "answer")
    engine.tick(due + 100600)
    assert engine.active and not engine.failed


def test_new_input_cancels_old_wait_timer_and_fences_silence_result():
    engine = make()
    due = wait_input(engine, "Let me finish.")
    engine.input("Let me finish. The reason is", False, 1000, "s1")
    assert engine.timer is None
    decide(engine, 1120, "continuation")
    engine.tick(due)
    assert not engine.active
    # A new explicit wait gives a fresh, bounded recheck opportunity.
    engine.input("Let me finish. Another reason", False, 5000, "s1")
    decide(engine, 5120, "explicit_wait")
    request = recheck(engine, engine.timer["due_ms"])
    engine.input(
        "Now answer my completed question?", True, engine.now + 10, "s2"
    )
    engine.complete_decision(
        request, {"start": answer("explicit_wait")}, engine.now + 20
    )
    assert engine.events[-1]["type"] == "decision.discarded"
    decide(engine, engine.last_input + 200, "answer")
    engine.tick(engine.last_input + 700)
    assert engine.active


def test_duplicate_final_does_not_reset_checks_or_duplicate_history():
    engine = make()
    text = "Let me finish. A completed argument."
    due = wait_input(engine, text)
    request = recheck(engine, due)
    revision = engine.revision
    engine.input(text, True, due + 10, "s1")
    assert engine.revision == revision and engine.wait_rechecks == 1
    engine.complete_decision(request, {"start": answer()}, due + 50)
    engine.tick(due + 400)
    rid = engine.active
    assert rid
    engine.playback(rid, 100, due + 500, completed=True)
    engine.input("What happened?", True, due + 600, "s2")
    decide(engine, due + 800, "answer")
    engine.tick(due + 1200)
    action = [a for a in engine.actions if a["type"] == "response.start"][-1]
    assert sum(i["text"] == text for i in action["context"]) == 1
    assert action["input_text"] == "What happened?"


def test_stop_ack_then_wait_then_completed_statement_can_answer():
    engine = make()
    rid = start(engine)
    engine.input("Let me finish.", True, 500, "s2")
    decide(engine, 650, "stop", kind="stop")
    engine.playback(rid, 100, 900, stopped=True)
    decide(engine, 920, "explicit_wait")
    engine.input(RECORD["state"]["input_text"], True, 97128, "s2")
    decide(engine, 97340, "explicit_wait", 0.38)
    request = recheck(engine, engine.timer["due_ms"])
    engine.complete_decision(request, {"start": answer()}, engine.now + 100)
    engine.tick(engine.now + 500)
    assert engine.active and engine.active != rid
    assert engine.history[-1]["text"] == RECORD["state"]["input_text"]


def test_ignore_recheck_preserves_waiting_content_and_control_stop_clears_it():
    engine = make()
    due = wait_input(engine, "Let me finish. My argument is important.")
    request = recheck(engine, due)
    engine.complete_decision(request, {"start": answer("ignore")}, due + 50)
    assert engine.pending and engine.text
    engine.stop("manual_stop")
    assert not engine.pending and not engine.wait_hold and not engine.timer
    engine.tick(due + 100000)
    assert not engine.active and engine.begin_decision(due + 100000) is None


def test_recorded_live_prefixes_cannot_release_a_known_wait_on_high_answer():
    engine = make(provider={"profile": "tuned"})
    wait_input(engine, "Let me finish.")
    for recorded in RECORD["prefixes"]:
        now = recorded["started_ms"]
        state = recorded["state"]
        assert not state["asr_final"]
        engine.input(
            state["input_text"], False, now - state["silence_ms"], "s1"
        )
        request = engine.begin_decision(now)
        assert request
        # The real candidate produced answer .76/.77 on revision319. Apply
        # that unsafe result to every prefix to exercise the protective gate.
        engine.complete_decision(
            request, {"start": answer("answer", 0.77)}, now + 10
        )
        engine.tick(now + 300)
        assert not engine.active and engine.wait_hold
    recorded = RECORD["final_request"]
    now = recorded["started_ms"]
    engine.input(
        recorded["state"]["input_text"],
        True,
        now - recorded["state"]["silence_ms"],
        "s1",
    )
    request = engine.begin_decision(now)
    engine.complete_decision(
        request, {"start": answer("answer", 0.90)}, now + 10
    )
    engine.tick(now + 300)
    assert engine.active and not engine.wait_hold
    assert engine.history[-1]["text"] == recorded["state"]["input_text"]


def test_stable_nonfinal_wait_can_release_only_after_silence_recheck():
    engine = make()
    wait_input(engine, "Let me finish.")
    engine.input(
        "Let me finish. This is my complete position.", False, 1000, "s1"
    )
    decide(engine, 1120, "answer")
    engine.tick(2000)
    assert not engine.active and engine.wait_hold
    request = recheck(engine, engine.timer["due_ms"])
    engine.complete_decision(request, {"start": answer()}, engine.now + 10)
    engine.tick(engine.now + 300)
    assert engine.active
