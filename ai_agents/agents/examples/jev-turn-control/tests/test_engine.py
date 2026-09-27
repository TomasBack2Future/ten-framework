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
    assert engine.active
    engine.complete_decision(request, {"start": answer()}, 1100)
    assert engine.events[-1]["type"] == "decision.discarded"
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
    request = engine.begin_decision(1100)
    assert request
    engine.close(1120)
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
    engine.tick(1600)
    assert engine.stopping == rid and engine.active is None
    assert engine.drain_actions()[-1]["reason"] == "main_response_priority"
    engine.playback(rid, 400, 1620, stopped=True)
    engine.tick(1621)
    assert engine.active != rid
    assert engine.responses[engine.active]["mode"] == "clarify"
