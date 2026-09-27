"""Fixed-output event regressions; synthetic text unless explicitly attributed."""

import pytest

from test_engine import answer, make, start


def decide(engine, now, label, score=0.95, kind="start"):
    """Complete one real reducer request, without a provider or wall clock."""
    request = engine.begin_decision(now)
    assert request is not None and kind in request["kinds"]
    engine.complete_decision(request, {kind: answer(label, score)}, now + 10)
    return request


def generated(engine, rid):
    """Synthetic aligned response with independently known duration."""
    engine.output(rid, "A complete answer.", engine.now, final=True)
    engine.audio(rid, 1810, completed=True, expected_ms=1810)
    engine.align(
        rid,
        [
            {"text": "A ", "end_ms": 200},
            {"text": "complete ", "end_ms": 1000},
            {"text": "answer.", "end_ms": 1810},
        ],
    )


def test_interrupted_guidance_new_question_regains_fallback():
    # 49c0d169 timing / visible question / score. Earlier redacted text is
    # deliberately synthetic: this is a state regression, not a transcript.
    engine = make(provider={"profile": "tuned"})
    engine.input("synthetic unfinished input", True, 171605, "prior")
    decide(engine, 171800, "continuation")
    engine.tick(176605)
    rid = engine.active
    assert rid and engine.guidance_sent
    engine.now = 177620
    engine.stop("manual_stop")
    engine.playback(rid, 221, 177620, stopped=True)
    engine.input("How many digits are there?", True, 178254, "question")
    assert not engine.guidance_sent
    decide(engine, 178500, "answer", 0.42)
    assert engine.timer is None
    engine.tick(183253)
    assert not engine.active
    engine.tick(183254)
    assert engine.active and engine.active != rid


def test_asr_revisions_and_repeated_final_do_not_renew_budget():
    engine = make()
    for now in range(0, 6000, 250):
        engine.input(f"synthetic partial {now}", False, now, "s1")
        decide(engine, now + 120, "continuation")
        engine.tick(now + 200)
        assert not engine.active
    engine.tick(10750)
    rid = engine.active
    assert rid
    revision = engine.revision
    engine.input("synthetic partial 5750", True, 10800, "s1")
    assert not engine.pending and engine.revision == revision
    assert engine.guidance_sent
    engine.playback(rid, 100, 10900, completed=True)
    engine.tick(30000)
    assert not engine.active and len(engine.finished) == 1


@pytest.mark.parametrize("label", ["explicit_wait", "ignore"])
def test_consumed_hold_does_not_prefix_next_input(label):
    engine = make()
    engine.input("Stop", True, 0, "s1")
    decide(engine, 120, label)
    engine.tick(5000)
    assert not engine.pending and not engine.active and engine.timer is None
    engine.input("Stop", True, 5100, "s1")
    assert not engine.pending
    engine.input("Go ahead", True, 5300, "s2")
    request = decide(engine, 5420, "answer")
    assert request["state"]["input_text"] == "Go ahead"
    engine.tick(6000)
    assert engine.active
    assert engine.history[0]["text"] == "Go ahead"


@pytest.mark.parametrize("reason", ["manual_stop", "buffer_limit"])
def test_control_stop_clears_pending_and_fences_inflight(reason):
    engine = make()
    rid = start(engine)
    engine.input("synthetic old input", True, 500, "s2")
    request = engine.begin_decision(650)
    engine.now = 700
    engine.stop(reason)
    engine.playback(rid, 100, 720, stopped=True)
    engine.complete_decision(request, {"stop": answer("continue")}, 800)
    engine.tick(20000)
    assert not engine.active and not engine.pending and not engine.timer
    assert any(e["type"] == "decision.discarded" for e in engine.events)
    engine.input("New question?", True, 20100, "s3")
    decide(engine, 20220, "answer")
    engine.tick(21000)
    assert engine.active and engine.text == "New question?"


@pytest.mark.parametrize("label", ["ignore", "answer", "explicit_wait"])
def test_playback_release_classifies_pending_before_expired_timer(label):
    engine = make()
    rid = start(engine)
    utterance = "Yes, and what is the price?" if label == "answer" else "Yes"
    engine.input(utterance, True, 500, "s2")
    decide(engine, 650, "continue", 0.98, "stop")
    engine.tick(7000)
    assert engine.active == rid
    engine.playback(rid, 6000, 7000, completed=True)
    engine.tick(7003)  # Real batch ordering: tick precedes the next request.
    assert not engine.active and engine.pending
    request = engine.begin_decision(7003)
    engine.tick(7900)  # In-flight start must also beat the old max-wait.
    assert not engine.active
    engine.complete_decision(request, {"start": answer(label)}, 7901)
    engine.tick(7902)
    assert bool(engine.active) == (label == "answer")
    assert not engine.pending
    if label == "answer":
        assert engine.history[-1]["text"] == utterance


def test_new_partial_fences_old_start_after_playback_release():
    engine = make()
    rid = start(engine)
    engine.input("Yes", True, 500, "s2")
    decide(engine, 650, "continue", kind="stop")
    engine.playback(rid, 5000, 6000, completed=True)
    request = engine.begin_decision(6000)
    engine.input("Yes and tell me more", True, 6050, "s2")
    engine.complete_decision(request, {"start": answer("ignore")}, 6100)
    engine.tick(12000)
    assert engine.pending and not engine.active
    decide(engine, 12000, "answer")
    engine.tick(12300)
    assert (
        engine.active and engine.history[-1]["text"] == "Yes and tell me more"
    )


@pytest.mark.parametrize(
    "policy,should_answer", [("hold", False), ("bounded_wait", True)]
)
def test_release_provider_failure_respects_existing_policy(
    policy, should_answer
):
    engine = make(provider={"failure_policy": policy})
    rid = start(engine)
    engine.input("synthetic pending input", True, 500, "s2")
    decide(engine, 650, "continue", kind="stop")
    engine.playback(rid, 5000, 6000, completed=True)
    engine.tick(6003)
    assert not engine.active
    request = engine.begin_decision(6010)
    engine.complete_decision(request, {}, 6810, error=True)
    engine.tick(6811)
    assert bool(engine.active) == should_answer


def test_short_completed_cursor_requires_stronger_evidence_and_is_idempotent():
    engine = make()
    rid = start(engine)
    generated(engine, rid)
    engine.playback(rid, 1720, 2400, completed=True)
    old = engine.history[-1]
    assert old["text"] == "A complete " and not old["fully_played"]
    revision = engine.context_revision
    engine.playback(rid, 1720, 2500, completed=True)
    assert engine.context_revision == revision
    engine.input("New question?", True, 2600, "s2")
    decide(engine, 2720, "answer")
    engine.tick(3100)
    newer = engine.active
    before = len(engine.history)
    engine.playback(rid, 1810, 3200, completed=True)
    assert old["text"] == "A complete answer." and old["fully_played"]
    assert engine.active == newer and len(engine.history) == before
    revision = engine.context_revision
    engine.playback(rid, 1810, 3300, completed=True)
    engine.playback(rid, 200, 3400, stopped=True)
    assert engine.context_revision == revision
    assert old["fully_played"] and engine.active == newer


def test_stop_request_wins_completed_race_and_duplicates_cannot_expand_memory():
    engine = make()
    rid = start(engine)
    generated(engine, rid)
    engine.now = 600
    engine.stop("user_reclaims_floor")
    engine.playback(rid, 1000, 700, completed=True)
    old = engine.history[-1]
    assert old["text"] == "A complete " and not old["fully_played"]
    revision = engine.context_revision
    engine.playback(rid, 1810, 800, completed=True)
    engine.playback(rid, 1810, 900, stopped=True)
    assert old["text"] == "A complete "
    assert engine.context_revision == revision


def test_timeout_can_accept_one_late_stop_but_never_completed_upgrade():
    engine = make()
    rid = start(engine)
    generated(engine, rid)
    engine.now = 600
    engine.stop("user_reclaims_floor")
    engine.tick(1100)
    old = engine.history[-1]
    assert not old["confirmed"] and not old["fully_played"]
    engine.playback(rid, 1810, 1200, completed=True)
    assert not old["confirmed"] and not old["fully_played"]
    engine.playback(rid, 1000, 1300, stopped=True)
    assert old["confirmed"] and old["text"] == "A complete "
    revision = engine.context_revision
    engine.playback(rid, 1500, 1400, stopped=True)
    assert engine.context_revision == revision and not old["fully_played"]


def test_repeated_control_stop_preserves_consumed_final_fence():
    engine = make()
    rid = start(engine)
    revision = engine.revision
    engine.now = 600
    engine.stop("manual_stop")
    engine.stop("manual_stop")
    engine.playback(rid, 100, 700, stopped=True)
    engine.input("Tell me the weather?", True, 800, "s1")
    assert not engine.pending and engine.revision == revision
    engine.tick(20000)
    assert not engine.active


def test_same_words_in_new_segment_are_a_new_input_cycle():
    engine = make()
    rid = start(engine)
    engine.playback(rid, 100, 700, completed=True)
    engine.input("Tell me the weather?", False, 800, "s2")
    assert engine.pending
    request = decide(engine, 920, "answer")
    assert request["state"]["input_text"] == "Tell me the weather?"
    engine.tick(1300)
    assert engine.active and engine.active != rid
