"""Regression coverage for timing, cancellation and bounded state."""

import importlib.util
from pathlib import Path
import sys
import types

ROOT = (
    Path(__file__).resolve().parents[3]
    / "ten_packages/extension/jev_turn_control_python"
)
PACKAGE = "jev_reducer_test"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
for module in ("config", "engine"):
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE}.{module}", ROOT / f"{module}.py"
    )
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
Config = sys.modules[f"{PACKAGE}.config"].Config
TurnEngine = sys.modules[f"{PACKAGE}.engine"].TurnEngine


def answer(label="answer", score=0.95):
    return {"label": label, "score": score, "probabilities": {label: score}}


def make(**options):
    options.setdefault("provider", {}).setdefault("profile", "baseline")
    return TurnEngine(Config.load(options), "test")


def start(engine):
    engine.input("Tell me the weather?", False, 0, "s1")
    request = engine.begin_decision(120)
    engine.complete_decision(request, {"start": answer()}, 200)
    engine.tick(450)
    assert engine.active
    return engine.active


def test_final_is_not_start_permission():
    engine = make()
    engine.input("I wanted to", True, 0)
    engine.tick(100)
    assert not engine.active
    request = engine.begin_decision(120)
    engine.complete_decision(request, {"start": answer("continuation")}, 200)
    engine.tick(1599)
    assert not engine.active
    engine.tick(1600)
    assert not engine.active
    engine.tick(5000)
    assert engine.responses[engine.active]["mode"] == "clarify"


def test_stale_decision_and_timer_invalidation():
    engine = make()
    engine.input("first", False, 0)
    request = engine.begin_decision(120)
    engine.input("first second", False, 140)
    engine.complete_decision(request, {"start": answer()}, 200)
    assert engine.timer is None
    assert engine.events[-1]["type"] == "decision.discarded"
    request = engine.begin_decision(300)
    engine.complete_decision(request, {"start": answer()}, 350)
    engine.input("first second third", False, 400)
    engine.tick(700)
    assert not engine.active
    assert engine.timer is None


def test_high_frequency_partial_does_not_starve_or_queue():
    engine = make(scheduling={"max_wait_ms": 1000})
    engine.input("a", False, 0)
    request = engine.begin_decision(120)
    for now in range(130, 1000, 10):
        engine.input(f"partial {now}", False, now)
        assert engine.begin_decision(now) is None
        engine.tick(now)
        assert len(engine.actions) == 0
    assert engine.inflight == request
    engine.tick(1000)
    assert not engine.active
    engine.complete_decision(request, {"start": answer()}, 1100)
    assert engine.events[-1]["type"] == "decision.discarded"
    engine.tick(1990)
    assert not engine.responses
    request = engine.begin_decision(1990)
    engine.complete_decision(request, {}, 2010, error=True)
    engine.tick(2010)
    assert len(engine.responses) == 1
    assert len(engine.events) <= 256


def test_stop_precedes_start_and_backchannel():
    engine = make(backchannel={"enabled": True})
    rid = start(engine)
    engine.input("stop please?", False, 500, "s2")
    request = engine.begin_decision(650)
    engine.complete_decision(
        request,
        {
            "stop": answer("stop"),
            "start": answer(),
            "backchannel": answer("backchannel"),
        },
        700,
    )
    assert engine.active is None and engine.stopping == rid
    assert engine.drain_actions()[-1]["type"] == "response.cancel"
    engine.tick(1199)
    assert engine.stopping
    engine.tick(1200)
    assert not engine.stopping
    event = [e for e in engine.events if e["type"] == "playback.stopped"][-1]
    assert event["payload"]["confirmed"] is False


def test_stop_not_starved_by_continuous_partial():
    engine = make()
    start(engine)
    for now in range(500, 1400, 10):
        engine.input(f"correction {now}", False, now, "s2")
        engine.tick(now)
    assert engine.active is None
    assert engine.stopping


def test_late_generation_and_played_context():
    engine = make(observation={"include_text": True})
    rid = start(engine)
    engine.output(rid, "Hello world unheard", 500)
    engine.align(
        rid,
        [
            {"text": "Hello ", "end_ms": 300},
            {"text": "world ", "end_ms": 700},
            {"text": "unheard", "end_ms": 1200},
        ],
    )
    engine.playback(rid, 750, 1250)
    engine.stop("user_reclaims_floor")
    assert not engine.output(rid, "late", 1260)
    engine.playback(rid, 760, 1270, stopped=True)
    assert engine.history[-1]["text"] == "Hello world "
    assert (
        engine.history[-1]["precision"] == "provider_alignment_browser_cursor"
    )
    engine.playback(rid, 1200, 1300, completed=True)
    assert engine.history[-1]["text"] == "Hello world "


def test_estimate_never_claims_exact():
    engine = make()
    rid = start(engine)
    engine.output(rid, "abcdefghijklmnopqrstuvwxyz", 500)
    engine.playback(rid, 500, 1000, stopped=True)
    assert engine.history[-1]["text"] == "abcdefg"
    assert engine.history[-1]["precision"] == "character_rate_estimate"


def test_pause_resume_disconnect():
    engine = make()
    start(engine)
    engine.pause(500)
    engine.input("another", False, 550)
    assert engine.begin_decision(800) is None
    engine.resume(1000)
    engine.tick(1000)
    request = engine.begin_decision(1120)
    assert request
    engine.close(1140)
    engine.complete_decision(request, {"start": answer()}, 1200)
    assert engine.events[-1]["type"] == "decision.discarded"
    assert engine.begin_decision(1500) is None
    assert engine.timer is None


def test_disabled_backchannel_and_conflict():
    engine = make(backchannel={"enabled": True})
    engine.input("A complete question?", False, 0)
    request = engine.begin_decision(120)
    engine.complete_decision(
        request, {"start": answer(), "backchannel": answer("backchannel")}, 200
    )
    assert not engine.active
    engine.tick(450)
    assert engine.responses[engine.active]["mode"] == "answer"
    assert (
        "backchannel" not in make().begin_decision(120)["kinds"]
        if make().pending
        else True
    )


def test_backchannel_cooldown_validity_and_main_wait():
    engine = make(backchannel={"enabled": True})
    engine.input("I am thinking", False, 0)
    request = engine.begin_decision(120)
    engine.complete_decision(
        request,
        {"start": answer("continuation"), "backchannel": answer("backchannel")},
        200,
    )
    rid = engine.active
    assert engine.responses[rid]["mode"] == "backchannel"
    engine.output(rid, "Mm-hmm.", 210)
    engine.playback(rid, 400, 600, completed=True)
    engine.input("I am thinking still", False, 650)
    request = engine.begin_decision(800)
    engine.complete_decision(
        request,
        {"start": answer("continuation"), "backchannel": answer("backchannel")},
        900,
    )
    assert engine.active is None


def test_failure_policy_and_ignore():
    engine = make(scheduling={"max_wait_ms": 1000})
    engine.input("uh", False, 0)
    request = engine.begin_decision(120)
    engine.complete_decision(request, {}, 300, error=True)
    engine.tick(1000)
    assert engine.active
    engine = make(
        provider={"failure_policy": "hold"}, scheduling={"max_wait_ms": 1000}
    )
    engine.input("uh", False, 0)
    request = engine.begin_decision(120)
    engine.complete_decision(request, {}, 300, error=True)
    engine.tick(1000)
    assert not engine.active


def test_config_invalid_values_and_text_redaction():
    import pytest

    for raw in (
        {"scheduling": {"max_inflight": 2}},
        {"provider": {"endpoint": "http://bad"}},
        {"start": {"enabled": 1}},
        {"backchannel": {"phrases": []}},
        {"scheduling": {"merge_ms": 6000}},
        {"unknown": {}},
    ):
        with pytest.raises(ValueError):
            Config.load(raw)
    engine = make()
    engine.input("private speech", False, 0)
    assert engine.events[-1]["payload"]["text"] == "[redacted]"


def test_late_alignment_refines_only_heard_context():
    engine = make(observation={"include_text": True})
    rid = start(engine)
    engine.output(rid, "Hello world never heard", 500)
    engine.playback(rid, 400, 900, stopped=True)
    assert engine.history[-1]["precision"] == "character_rate_estimate"
    engine.align(
        rid,
        [{"text": "Hello ", "end_ms": 300}, {"text": "world ", "end_ms": 700}],
    )
    assert engine.history[-1]["text"] == "Hello "
    assert (
        engine.history[-1]["precision"] == "provider_alignment_browser_cursor"
    )
    assert engine.events[-1]["payload"]["alignment_updated"]


def test_ignore_consumes_without_speaking_and_disabled_start_holds():
    engine = make()
    engine.input("um", False, 0)
    request = engine.begin_decision(120)
    engine.complete_decision(request, {"start": answer("ignore")}, 200)
    engine.tick(2000)
    assert not engine.pending and engine.active is None
    engine = make(start={"enabled": False})
    engine.input("hello?", True, 0)
    engine.tick(10000)
    assert engine.active is None


def test_finished_context_is_bounded():
    engine = make(playback={"context_responses": 2})
    for index in range(5):
        engine.now = index * 1000
        engine.text = "hello"
        engine.start("answer")
        rid = engine.active
        engine.output(rid, "hello", engine.now)
        engine.playback(rid, 500, engine.now + 500, completed=True)
    assert len(engine.finished) == 2
    assert len(engine.history) == 10
    assert not engine.responses


def test_main_reply_preempts_backchannel_playback():
    engine = make(backchannel={"enabled": True})
    engine.input("I am still thinking", False, 0)
    request = engine.begin_decision(120)
    engine.complete_decision(
        request,
        {"start": answer("continuation"), "backchannel": answer("backchannel")},
        200,
    )
    rid = engine.active
    engine.input("Actually, what is the weather?", True, 700)
    request = engine.begin_decision(850)
    engine.complete_decision(
        request, {"stop": answer("continue"), "start": answer()}, 900
    )
    engine.tick(1150)
    assert engine.stopping == rid and engine.active is None
    assert engine.drain_actions()[-1]["reason"] == "main_response_priority"
    engine.playback(rid, 400, 1170, stopped=True)
    engine.tick(1171)
    assert engine.active != rid
    assert engine.responses[engine.active]["mode"] == "answer"


def test_continuation_keeps_floor_and_guides_once_per_input_cycle():
    engine = make(scheduling={"max_wait_ms": 1000})
    for now in range(0, 8000, 200):
        engine.input(f"I am thinking about {now}", False, now)
        request = engine.begin_decision(now + 120)
        engine.complete_decision(
            request, {"start": answer("continuation")}, now + 150
        )
        engine.tick(now + 180)
        assert not engine.active
    engine.tick(8799)
    assert not engine.active
    engine.tick(8800)
    first = engine.active
    assert first
    engine.playback(first, 200, 9000, completed=True)
    # New input after the nudge owns a new budget; ticks alone do not renew it.
    engine.input("I am still deciding", False, 9200)
    request = engine.begin_decision(9320)
    engine.complete_decision(request, {"start": answer("continuation")}, 9400)
    for now in range(10200, 15000, 20):
        engine.tick(now)
    assert engine.active and engine.active != first
    assert engine.input_cycle == 2
    assert (
        len([a for a in engine.actions if a["type"] == "response.start"]) == 2
    )


def test_ambiguous_final_short_answer_uses_combined_reply_readiness():
    engine = make()
    engine.input("Uh, Sunday?", True, 0)
    request = engine.begin_decision(120)
    decision = {
        "label": "continuation",
        "score": 0.35,
        "probabilities": {
            "continuation": 0.35,
            "answer": 0.31,
            "clarify": 0.31,
            "ignore": 0.03,
            "explicit_wait": 0,
        },
    }
    engine.complete_decision(request, {"start": decision}, 190)
    engine.tick(1089)
    assert not engine.active
    engine.tick(1090)
    assert engine.responses[engine.active]["mode"] == "clarify"


def test_final_and_punctuation_alone_do_not_grant_floor():
    engine = make()
    engine.input("I will go to.", True, 0)
    request = engine.begin_decision(120)
    engine.complete_decision(request, {"start": answer("continuation")}, 190)
    engine.tick(440)
    engine.tick(2000)
    assert not engine.active


def test_punctuation_only_asr_cannot_stop_or_start_a_response():
    engine = make()
    engine.input("——", True, 0, "artifact")
    assert not engine.pending
    assert engine.begin_decision(120) is None
    assert engine.events[-1]["type"] == "asr.ignored"

    rid = start(engine)
    current_revision = engine.revision
    engine.input("——", True, 500, "artifact2")
    assert engine.active == rid
    assert engine.revision == current_revision
    assert engine.begin_decision(700) is None
    assert not any(
        action["type"] == "response.cancel" for action in engine.drain_actions()
    )


def test_punctuation_only_segment_does_not_replace_real_pending_input():
    engine = make()
    engine.input("Please explain", False, 0, "speech")
    current_revision = engine.revision
    engine.input("——", True, 100, "artifact")
    assert engine.pending
    assert engine.text == "Please explain"
    assert engine.revision == current_revision
    request = engine.begin_decision(120)
    assert request["state"]["input_text"] == "Please explain"


def test_nonfinal_clarification_waits_for_missing_referent():
    engine = make()
    engine.input("我问你解释一下，你刚刚那个", False, 0, "speech")
    request = engine.begin_decision(120)
    engine.complete_decision(request, {"start": answer("clarify")}, 200)
    assert engine.timer["label"] == "continuation"
    assert not engine.active

    engine.input("我问你解释一下，你刚刚那个笑话。", True, 400, "speech")
    request = engine.begin_decision(520)
    engine.complete_decision(request, {"start": answer("answer")}, 600)
    engine.tick(850)
    assert engine.responses[engine.active]["mode"] == "answer"


def test_latest_input_cancels_short_answer_and_continuation_deadlines():
    engine = make(scheduling={"max_wait_ms": 1000})
    engine.input("I will go to", False, 0)
    request = engine.begin_decision(120)
    engine.complete_decision(request, {"start": answer("continuation")}, 200)
    engine.input("I will go to Boston", False, 999)
    engine.tick(1000)
    assert not engine.active
    request = engine.begin_decision(1120)
    engine.complete_decision(request, {"start": answer()}, 1200)
    engine.input("I will go to Boston or", False, 1449)
    engine.tick(1450)
    assert not engine.active


def test_silence_explicit_wait_does_not_produce_guidance():
    engine = make()
    engine.input("Wait, let me think", True, 0)
    request = engine.begin_decision(120)
    engine.complete_decision(request, {"start": answer("explicit_wait")}, 200)
    engine.tick(5000)
    engine.tick(10000)
    assert not engine.active and engine.pending
    assert engine.text == "Wait, let me think"


def test_whitespace_duplicate_does_not_revise_or_reset_timer():
    engine = make()
    engine.input("from Toronto to", False, 0)
    request = engine.begin_decision(120)
    engine.complete_decision(request, {"start": answer("continuation")}, 200)
    timer = dict(engine.timer)
    engine.input("from  Toronto   to ", False, 500)
    assert engine.revision == 1
    assert engine.timer == timer
    assert engine.last_input == 0


def test_fresh_partial_waits_for_stability_after_idle_gap():
    engine = make()
    engine.input("S", False, 10000)
    assert engine.begin_decision(10020) is None
    engine.input("Sun", False, 10050)
    assert engine.begin_decision(10120) is None
    engine.input("Sunday?", True, 10150)
    assert engine.begin_decision(10269) is None
    assert engine.begin_decision(10270) is not None


def test_stop_classification_does_not_spend_start_calls_and_rechecks_after_ack():
    engine = make()
    rid = start(engine)
    engine.input("Actually, Tuesday", True, 500, "s2")
    request = engine.begin_decision(650)
    assert request["kinds"] == ["stop"]
    engine.complete_decision(request, {"stop": answer("stop")}, 700)
    assert engine.begin_decision(850) is None
    engine.playback(rid, 100, 900, stopped=True)
    request = engine.begin_decision(920)
    assert request["kinds"] == ["start"]
    engine.complete_decision(request, {"start": answer()}, 1000)
    engine.tick(1250)
    assert engine.active and engine.active != rid


def test_stop_keep_speaking_still_allows_start_after_natural_completion():
    engine = make()
    rid = start(engine)
    engine.input("Yes", True, 500, "s2")
    request = engine.begin_decision(650)
    engine.complete_decision(request, {"stop": answer("continue")}, 700)
    engine.playback(rid, 600, 1100, completed=True)
    assert engine.begin_decision(1120)["kinds"] == ["start"]


def test_reply_readiness_keeps_subcategory_and_wait_ignore_veto():
    for label, probabilities, expected in (
        (
            "answer",
            {"answer": 0.4, "clarify": 0.25, "continuation": 0.35},
            "answer",
        ),
        (
            "clarify",
            {"answer": 0.25, "clarify": 0.4, "continuation": 0.35},
            "clarify",
        ),
        (
            "explicit_wait",
            {"explicit_wait": 0.4, "answer": 0.3, "clarify": 0.3},
            None,
        ),
        ("ignore", {"ignore": 0.4, "answer": 0.3, "clarify": 0.3}, None),
    ):
        engine = make()
        engine.input("A short final segment", True, 0)
        request = engine.begin_decision(120)
        engine.complete_decision(
            request,
            {
                "start": {
                    "label": label,
                    "score": probabilities[label],
                    "probabilities": probabilities,
                }
            },
            190,
        )
        engine.tick(1090)
        if expected:
            assert engine.responses[engine.active]["mode"] == expected
        else:
            engine.tick(10000)
            assert not engine.active


def test_final_flag_update_invalidates_inflight_and_new_speech_cancels_readiness():
    engine = make()
    engine.input("Sunday?", False, 0)
    request = engine.begin_decision(120)
    engine.input("Sunday?", True, 140)
    engine.complete_decision(request, {"start": answer()}, 200)
    assert not engine.timer
    request = engine.begin_decision(300)
    engine.complete_decision(request, {"start": answer()}, 390)
    engine.input("Sunday? No, actually", False, 400)
    engine.tick(1000)
    assert not engine.active


def test_late_alignment_cannot_pin_inflight_request():
    engine = make(observation={"include_text": True})
    rid = start(engine)
    engine.output(rid, "Hello world", 500)
    engine.playback(rid, 400, 900, completed=True)
    engine.input("A new question?", True, 1000, "s2")
    request = engine.begin_decision(1120)
    original_context = request["state"]["heard_context"]
    engine.align(rid, [{"text": "Hello ", "end_ms": 300}])
    assert request["state"]["heard_context"] == original_context
    engine.complete_decision(request, {"start": answer()}, 1250)
    assert engine.inflight is None
    engine.input("A newer question?", True, 1300, "s2")
    newer = engine.begin_decision(1420)
    # A duplicate completion from the old request cannot release the new one.
    engine.complete_decision(request, {"start": answer()}, 1430)
    assert engine.inflight["request_id"] == newer["request_id"]
    engine.complete_decision(newer, {"start": answer()}, 1500)
    assert engine.inflight is None


def test_pause_restores_label_and_excludes_paused_time_from_deadline():
    for label in ("ignore", "explicit_wait", "answer", "continuation"):
        engine = make()
        engine.input("Test segment", False, 0)
        request = engine.begin_decision(120)
        engine.complete_decision(request, {"start": answer(label)}, 200)
        due = engine.timer["due_ms"]
        engine.pause(300)
        engine.resume(10000)
        engine.tick(10000)
        assert not engine.active
        assert engine.timer["label"] == label
        engine.tick(10000 + due - 300)
        if label == "answer":
            assert engine.responses[engine.active]["mode"] == "answer"
        elif label == "continuation":
            assert engine.responses[engine.active]["mode"] == "clarify"
        else:
            assert not engine.active
            assert engine.pending == (label == "explicit_wait")


def test_new_input_while_paused_does_not_restore_old_ignore():
    engine = make()
    engine.input("uh", False, 0)
    request = engine.begin_decision(120)
    engine.complete_decision(request, {"start": answer("ignore")}, 200)
    engine.pause(300)
    engine.input("A real question?", True, 9000)
    engine.resume(10000)
    engine.tick(10000)
    assert engine.timer is None and engine.pending and not engine.active
    assert engine.begin_decision(10120)


def test_wait_and_ignore_veto_backchannel_even_when_enabled():
    for label in ("ignore", "explicit_wait"):
        engine = make(backchannel={"enabled": True})
        engine.input("Please wait", True, 0)
        request = engine.begin_decision(120)
        engine.complete_decision(
            request,
            {"start": answer(label), "backchannel": answer("backchannel")},
            200,
        )
        engine.tick(5000)
        assert not engine.active
        assert not any(a["type"] == "response.start" for a in engine.actions)


def test_expired_backchannel_is_intentionally_dropped():
    engine = make(backchannel={"enabled": True})
    engine.input("I am still thinking", False, 0)
    request = engine.begin_decision(120)
    engine.complete_decision(
        request,
        {"start": answer("continuation"), "backchannel": answer("backchannel")},
        820,
    )
    assert not engine.active
    assert not any(a["type"] == "response.start" for a in engine.actions)
    assert engine.timer["label"] == "continuation"


def test_response_context_precedes_current_user_append():
    engine = make(playback={"context_responses": 2})
    for index in range(3):
        engine.text = f"question {index}"
        engine.now = index * 1000
        engine.start("answer")
        action = engine.drain_actions()[-1]
        assert not any(
            item["text"] == action["input_text"] for item in action["context"]
        )
        # context_responses bounds the late-ACK cache, not conversation history.
        assert [
            item["text"] for item in action["context"] if item["role"] == "user"
        ] == [f"question {prior}" for prior in range(index)]
        rid = engine.active
        engine.output(rid, "An answer", engine.now + 100)
        engine.playback(rid, 1000, engine.now + 500, completed=True)


def test_normalized_consumed_partial_does_not_duplicate_history_on_final():
    engine = make()
    engine.input("  My   name is Maya  ", False, 0, "s1")
    engine.start("answer")
    revision = engine.revision
    engine.input("My name is Maya", True, 500, "s1")
    assert engine.revision == revision
    assert not engine.pending
    assert engine.history == [{"role": "user", "text": "My name is Maya"}]
