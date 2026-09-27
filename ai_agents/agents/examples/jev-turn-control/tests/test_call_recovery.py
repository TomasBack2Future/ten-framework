"""6fb2d21e regressions with fixed provider outputs, not model accuracy tests."""

import asyncio
from copy import deepcopy
import importlib

from test_engine import answer, make, start, Config, PACKAGE


def test_continue_then_new_ack_gets_a_fresh_stop_budget():
    engine = make()
    rid = start(engine)
    engine.input("Mm-hm.", True, 126490, "ack1")
    request = engine.begin_decision(126572)
    engine.complete_decision(
        request, {"stop": answer("continue", 0.76)}, 126723
    )
    engine.input("Ok", False, 130418, "ack2")
    engine.tick(130421)
    assert engine.active == rid
    engine.input("Okay.", True, 130593, "ack2")
    request = engine.begin_decision(130700)
    engine.complete_decision(
        request, {"stop": answer("continue", 0.88)}, 130800
    )
    engine.tick(140000)
    assert engine.active == rid


def test_unresolved_partial_storm_still_has_bounded_stop():
    engine = make()
    rid = start(engine)
    for now in range(500, 1301, 100):
        engine.input(f"Stop {now}", False, now, "new")
        engine.tick(now)
    assert engine.active is None and engine.stopping == rid


def test_same_segment_terminal_punctuation_does_not_interrupt():
    engine = make()
    engine.input("Can you hear me", False, 0, "greeting")
    engine.start("answer")
    rid, rev = engine.active, engine.revision
    engine.input("Can you hear me?", True, 500, "greeting")
    engine.tick(5000)
    assert engine.active == rid and engine.revision == rev
    engine.input("Can you hear me? Stop", True, 5100, "greeting")
    assert engine.pending and engine.revision == rev + 1


def test_applied_decision_has_immutable_persistable_evidence():
    engine = make()
    saved = []
    engine.event_sink = lambda kind, data, rid: saved.append(deepcopy(data))
    start(engine)
    applied = [e for e in saved if e["type"] == "decision.applied"]
    assert (
        len(applied) == 1 and applied[0]["payload"]["decision_kind"] == "start"
    )
    completed = next(e for e in saved if e["type"] == "decision.completed")
    assert applied[0]["payload"]["decision_seq"] == completed["seq"]


def test_provider_applies_ready_result_before_timeout_wrapper_wakes_caller(
    monkeypatch,
):
    provider_module = importlib.import_module(f"{PACKAGE}.provider")

    async def run():
        engine = make()
        rid = start(engine)
        engine.input("Mm-hm.", True, 500, "ack")
        request = engine.begin_decision(650)
        provider = provider_module.DecisionProvider(Config.load())
        provider.config["provider"]["name"] = "jev"

        monkeypatch.setenv("JEV_API_KEY", "synthetic-test-key")

        class Response:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                # Both HTTP cleanup and wait_for may let the clock run first.
                await asyncio.sleep(0)

            async def json(self):
                asyncio.get_running_loop().call_soon(engine.tick, 1301)
                return {
                    "answers": {
                        "stop": {
                            "choice": "continue",
                            "probabilities": {"continue": 0.88, "stop": 0.12},
                        }
                    }
                }

        class Client:
            def post(self, *_args, **_kwargs):
                return Response()

        provider.client = Client()
        await provider.decide(
            request,
            on_result=lambda result: engine.complete_decision(
                request, result, 1200
            ),
        )
        assert engine.active == rid

    asyncio.run(run())


def test_fast_stop_error_preserves_safety_deadline():
    engine = make()
    rid = start(engine)
    engine.input("Stop!", True, 500, "barge")
    request = engine.begin_decision(650)
    engine.complete_decision(request, {}, 700, error=True)
    engine.tick(1299)
    assert engine.active == rid
    engine.tick(1300)
    assert engine.active is None and engine.stopping == rid


def test_same_segment_final_retains_meaningful_symbols():
    for partial, final in (
        ("50", "50%"),
        ("50", "50 %"),
        ("3", "3#"),
        ("James", "James'"),
    ):
        engine = make()
        engine.input(partial, False, 0, "same")
        engine.start("answer")
        revision = engine.revision
        engine.input(final, True, 500, "same")
        assert engine.pending and engine.revision == revision + 1
        assert engine.text == final
