"""Mode, profile, wire contract and fail-closed regression coverage."""

import asyncio
from copy import deepcopy
import importlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from test_engine import Config, TurnEngine, PACKAGE

provider_module = importlib.import_module(f"{PACKAGE}.provider")
profiles = importlib.import_module(f"{PACKAGE}.profiles")
DecisionProvider = provider_module.DecisionProvider


def response_for(config, kinds, label=None):
    answers = {}
    for kind in kinds:
        choices = profiles.question_for(config, kind)["criteria"]
        selected = label if label in choices else next(iter(choices))
        answers[kind] = {
            "choice": selected,
            "probabilities": {key: float(key == selected) for key in choices},
        }
    return {"answers": answers}


class Client:
    """Exercise post context management, auth and reuse without paid requests."""

    def __init__(self, responses, delay=0):
        self.responses = list(responses)
        self.calls = []
        self.delay = delay
        self.closed = False
        self.exited = 0

    def post(self, url, **kwargs):
        self.calls.append((url, deepcopy(kwargs)))
        client = self
        data = self.responses.pop(0)

        class Response:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                client.exited += 1

            async def json(self):
                await asyncio.sleep(client.delay)
                return data

        return Response()

    async def close(self):
        self.closed = True


@pytest.mark.parametrize("mode", ["jev", "sd", "sd_jev"])
def test_modes_send_complete_selected_questions_and_reuse_client(
    mode, monkeypatch
):
    async def run():
        monkeypatch.setenv("JEV_API_KEY", "test-jev")
        monkeypatch.setenv("SCALEDOWN_API_KEY", "test-sd")
        config = Config.load({"provider": {"name": mode}})
        provider = DecisionProvider(config)
        kinds = [
            "start",
            "stop",
            "backchannel",
            "compression",
            "route",
            "support",
        ]
        result = response_for(config, kinds)
        responses = [result, result]
        if mode == "sd_jev":
            responses = [
                {"results": {"compressed_prompt": "compressed facts"}},
                result,
            ] * 2
        client = Client(responses)
        provider.client = client
        state = {"input_text": "Please wait until I finish.", "asr_final": True}
        request = {"state": state, "kinds": kinds}
        for _ in range(2):
            answers = await provider.decide(request)
            assert all(a["score"] == 1 for a in answers.values())
        assert provider.client is client
        final_url, call = client.calls[-1]
        body = call["json"]
        for kind in kinds:
            frozen = profiles.profile_for(mode)[kind]
            assert body["questions"][kind] == {
                k: frozen[k] for k in ("type", "instructions", "criteria")
            }
        assert call["allow_redirects"] is False
        if mode == "sd":
            assert final_url.endswith("/v1/scaledown")
            assert body["model"] == "classify-1"
            assert json.loads(body["state"]["text"]) == state
            assert call["headers"] == {"x-api-key": "test-sd"}
        else:
            assert final_url.endswith("/v1/systemone")
            assert body["model"] == "jev-1.13.0"
            assert call["headers"] == {"Authorization": "Bearer test-jev"}
            assert body["state"] == (
                state
                if mode == "jev"
                else {"compressed_state_text": "compressed facts"}
            )
        if mode == "sd_jev":
            compression = client.calls[0][1]
            assert json.loads(compression["json"]["context"]) == state
            assert compression["headers"] == {"x-api-key": "test-sd"}
            assert "user prefix" in compression["json"]["prompt"]
        assert request["state"] == state
        await provider.close()
        assert client.closed

    asyncio.run(run())


def test_defaults_baseline_overrides_and_label_validation():
    config = Config.load()
    assert config["provider"]["name"] == "jev"
    assert config["start"]["threshold"] == 0.47
    assert config["start"]["score_mode"] == "top"
    assert not config["compression"]["enabled"]
    assert not config["backchannel"]["enabled"]
    assert (
        Config.load({"start": {"prompt": ""}})["start"]["prompt"]
        == config["start"]["prompt"]
    )
    baseline = Config.load({"provider": {"profile": "baseline"}})
    assert baseline["start"]["threshold"] == 0.6
    assert baseline["start"]["score_mode"] == "legacy_reply"
    assert (
        profiles.question_for(baseline, "start") == profiles.BASELINE["start"]
    )
    criteria = {k: "Custom " + k for k in config["start"]["criteria"]}
    custom = Config.load(
        {
            "start": {
                "prompt": "Custom instructions",
                "criteria": criteria,
                "threshold": 0.9,
            }
        }
    )
    assert profiles.question_for(custom, "start")["criteria"] == criteria
    assert (
        profiles.question_for(custom, "start")["instructions"]
        == "Custom instructions"
    )
    assert custom["start"]["threshold"] == 0.9
    for raw in [
        {"provider": {"name": "other"}},
        {"provider": {"profile": "other"}},
        {"start": {"criteria": {"execute": "wrong label"}}},
        {"support": {"threshold": float("nan")}},
        {"start": {"score_mode": "sum_everything"}},
    ]:
        with pytest.raises(ValueError):
            Config.load(raw)


@pytest.mark.parametrize(
    "compressed",
    [
        {},
        {"compressed_prompt": ""},
        {"compressed_prompt": 42},
        {"results": None},
    ],
)
def test_bad_compression_never_calls_jev(compressed, monkeypatch):
    async def run():
        monkeypatch.setenv("SCALEDOWN_API_KEY", "test-sd")
        provider = DecisionProvider(
            Config.load({"provider": {"name": "sd_jev"}})
        )
        provider.client = Client([compressed])
        with pytest.raises(ValueError):
            await provider.decide({"state": {}, "kinds": ["start"]})
        assert len(provider.client.calls) == 1

    asyncio.run(run())


def test_total_chain_timeout_cancels_inflight_response(monkeypatch):
    async def run():
        monkeypatch.setenv("JEV_API_KEY", "test-jev")
        monkeypatch.setenv("SCALEDOWN_API_KEY", "test-sd")
        config = Config.load(
            {"provider": {"name": "sd_jev", "timeout_ms": 100}}
        )
        provider = DecisionProvider(config)
        client = Client(
            [{"compressed_prompt": "facts"}, response_for(config, ["start"])],
            delay=0.07,
        )
        provider.client = client
        with pytest.raises(asyncio.TimeoutError):
            await provider.decide({"state": {}, "kinds": ["start"]})
        assert len(client.calls) == client.exited == 2

    asyncio.run(run())


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, 2, True])
def test_invalid_probabilities_never_admit_decisions(bad, monkeypatch):
    async def run():
        monkeypatch.setenv("JEV_API_KEY", "test-jev")
        config = Config.load()
        provider = DecisionProvider(config)
        response = response_for(config, ["start"])
        response["answers"]["start"]["probabilities"]["answer"] = bad
        provider.client = Client([response])
        with pytest.raises(ValueError):
            await provider.decide({"state": {}, "kinds": ["start"]})

    asyncio.run(run())


@pytest.mark.parametrize(
    "mode,threshold", [("jev", 0.47), ("sd", 0.95), ("sd_jev", 0.54)]
)
def test_selected_start_gate_and_subcategory(mode, threshold):
    def apply(label, probs):
        engine = TurnEngine(Config.load({"provider": {"name": mode}}))
        engine.input("Could you help?", True, 0)
        request = engine.begin_decision(120)
        engine.complete_decision(
            request,
            {
                "start": {
                    "label": label,
                    "score": probs[label],
                    "probabilities": probs,
                }
            },
            190,
        )
        return engine

    assert (
        Config.load({"provider": {"name": mode}})["start"]["threshold"]
        == threshold
    )
    yes = apply("clarify", {"clarify": threshold, "answer": 0})
    assert yes.timer["label"] == "clarify"
    no = apply("clarify", {"clarify": threshold - 0.01, "answer": 0})
    assert not no.timer
    split = apply("clarify", {"clarify": threshold - 0.1, "answer": 0.15})
    assert bool(split.timer) == (mode != "jev")
    continuation = apply(
        "continuation", {"continuation": 0.35, "answer": 0.32, "clarify": 0.33}
    )
    assert not continuation.timer  # Combined reply mass never steals the floor.


def test_route_and_support_are_independent_gates_and_whitelist_input():
    async def run():
        config = Config.load()
        provider = DecisionProvider(config)
        result = {
            "route": {
                "label": "execute",
                "score": 0.74,
                "probabilities": {"execute": 0.74},
            },
            "support": {
                "label": "supported",
                "score": 0.60,
                "probabilities": {"supported": 0.60},
            },
        }
        provider.decide = AsyncMock(return_value=result)
        state = {
            "text": "Build a table",
            "gold": "execute",
            "private_goal": "secret",
            "stable": True,
        }
        decision = await provider.route(state)
        assert decision["route"] == decision["support"] == "wait"
        visible = provider.decide.call_args.args[0]["state"]
        assert set(visible) == {
            "text",
            "history",
            "active_tasks",
            "capabilities",
            "stable",
        }
        result["route"]["score"] = 0.75
        result["support"]["score"] = 0.61
        decision = await provider.route(state)
        assert (
            decision["route"] == "execute"
            and decision["support"] == "supported"
        )
        result["route"].update(label="task_control", score=0.74)
        assert (await provider.route(state))["route"] == "wait"
        result["route"]["score"] = 0.75
        assert (await provider.route(state))["route"] == "task_control"
        assert (await provider.route({**state, "stable": False}))[
            "route"
        ] == "wait"
        provider.decide.side_effect = asyncio.TimeoutError
        with pytest.raises(asyncio.TimeoutError):
            await provider.route(state)

    asyncio.run(run())


def test_graph_mode_validation_and_mock_isolation():
    file = Path(__file__).parents[1] / "scripts/run_graph.py"
    spec = importlib.util.spec_from_file_location("graph_mode_test", file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for mode in ("jev", "sd", "sd_jev"):
        graph = module.graph_for("live", {"provider.name": mode})
        settings = graph["ten"]["predefined_graphs"][0]["graph"]["nodes"][0][
            "property"
        ]
        assert Config.load(settings)["provider"]["name"] == mode
        graph = module.graph_for("mock", {"provider.name": mode})
        assert (
            graph["ten"]["predefined_graphs"][0]["graph"]["nodes"][0][
                "property"
            ]["provider"]["name"]
            == "mock"
        )
    with pytest.raises(ValueError):
        module.graph_for("live", {"provider.name": "http://untrusted"})


@pytest.mark.parametrize("mode", ["jev", "sd", "sd_jev"])
def test_stop_and_backchannel_thresholds_gate_real_reducer(mode):
    for admitted in (False, True):
        config = Config.load(
            {"provider": {"name": mode}, "backchannel": {"enabled": True}}
        )
        engine = TurnEngine(config)
        engine.input("Tell me about the garden.", True, 0)
        engine.start("answer")
        engine.input("Stop!", True, 100, "second")
        request = engine.begin_decision(220)
        engine.complete_decision(
            request,
            {
                "stop": {
                    "label": "stop",
                    "score": config["stop"]["threshold"]
                    - (0 if admitted else 0.01),
                }
            },
            250,
        )
        assert bool(engine.stopping) == admitted
        engine = TurnEngine(config)
        engine.input("And then I continued the story", False, 0)
        request = engine.begin_decision(120)
        engine.complete_decision(
            request,
            {
                "start": {"label": "continuation", "score": 1},
                "backchannel": {
                    "label": "backchannel",
                    "score": config["backchannel"]["threshold"]
                    - (0 if admitted else 0.01),
                },
            },
            190,
        )
        assert bool(engine.active) == admitted
        if admitted:
            assert engine.responses[engine.active]["mode"] == "backchannel"


def test_compression_threshold_controls_summary_call(monkeypatch):
    from test_memory import compression_engine

    extension = importlib.import_module(f"{PACKAGE}.extension")

    async def run(mode, admitted):
        engine = compression_engine()
        engine.config.values["provider"]["name"] = mode
        threshold = Config.load({"provider": {"name": mode}})["compression"][
            "threshold"
        ]
        engine.config.values["compression"]["threshold"] = threshold
        adapter = extension.JevTurnControlExtension("threshold_test")
        adapter.engine = engine
        adapter.pump = AsyncMock()
        adapter.provider = DecisionProvider(engine.config)
        adapter.provider.decide = AsyncMock(
            return_value={
                "compression": {
                    "label": "compress",
                    "score": threshold - (0 if admitted else 0.01),
                }
            }
        )
        summary = AsyncMock(return_value="Confirmed older facts.")
        monkeypatch.setattr(extension, "summarize", summary)
        await adapter.compress(engine.begin_compression(engine.now))
        assert summary.await_count == int(admitted)

    for mode in ("jev", "sd", "sd_jev"):
        for admitted in (False, True):
            asyncio.run(run(mode, admitted))


@pytest.mark.parametrize("mode", ["jev", "sd", "sd_jev"])
def test_provider_errors_preserve_hold_policy(mode):
    extension = importlib.import_module(f"{PACKAGE}.extension")

    async def run():
        adapter = extension.JevTurnControlExtension("mode_failure")
        adapter.engine = TurnEngine(
            Config.load({"provider": {"name": mode, "failure_policy": "hold"}})
        )
        adapter.provider = DecisionProvider(adapter.engine.config)
        adapter.provider.decide = AsyncMock(side_effect=asyncio.TimeoutError)
        adapter.pump = AsyncMock()
        engine = adapter.engine
        engine.input("Please answer.", True, 0)
        adapter.now = lambda: 190
        await adapter.classify(engine.begin_decision(120))
        engine.tick(10000)
        assert not engine.active and engine.inflight is None
        assert any(
            e["type"] == "error"
            and e["payload"]["code"] == "provider_unavailable"
            for e in engine.events
        )

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["jev", "sd", "sd_jev"])
def test_baseline_support_gate_rejects_low_confidence(mode):
    async def run():
        config = Config.load(
            {"provider": {"name": mode, "profile": "baseline"}}
        )
        assert config["support"]["threshold"] == 0.75
        provider = DecisionProvider(config)
        for route in ("execute", "task_control"):
            for score in (0, 0.01, 0.74, 0.75):
                provider.decide = AsyncMock(
                    return_value={
                        "route": {
                            "label": route,
                            "score": 0.75,
                            "probabilities": {route: 0.75},
                        },
                        "support": {
                            "label": "supported",
                            "score": score,
                            "probabilities": {"supported": score},
                        },
                    }
                )
                result = await provider.route(
                    {"text": "Create a report", "stable": True}
                )
                assert result["route"] == route
                assert result["support"] == (
                    "supported" if score >= 0.75 else "wait"
                )
        with pytest.raises(ValueError, match="positive"):
            Config.load(
                {
                    "provider": {"profile": "baseline"},
                    "support": {"threshold": 0},
                }
            )

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["jev", "sd", "sd_jev"])
@pytest.mark.parametrize("profile", ["baseline", "tuned"])
def test_call_session_remains_independent_of_provider_and_profile(
    mode, profile, monkeypatch
):
    extension = importlib.import_module(f"{PACKAGE}.extension")
    executor_module = importlib.import_module(f"{PACKAGE}.executor_client")
    memory = importlib.import_module(f"{PACKAGE}.memory")
    monkeypatch.setenv("JEV_CODEX_ENABLED", "true")

    async def run(fails):
        config = Config.load(
            {
                "provider": {
                    "name": mode,
                    "profile": profile,
                    "failure_policy": "hold",
                },
                "executor": {"enabled": True},
            }
        )
        adapter = extension.JevTurnControlExtension("mode_session")
        engine = adapter.engine = TurnEngine(config)
        adapter.now = lambda: 0
        adapter.executor = executor_module.ExecutorClient(
            engine.emit, config["executor"]["enabled"]
        )
        adapter.executor.sid = "one-call"
        adapter.provider = DecisionProvider(config)
        adapter.provider.decide = AsyncMock(
            side_effect=asyncio.TimeoutError if fails else None,
            return_value={"start": {"label": "continuation", "score": 1}},
        )
        adapter.provider.route = AsyncMock(
            side_effect=AssertionError("P1 does not use RuntimeRouter")
        )
        adapter.pump = AsyncMock()
        partial = {
            "text": "Create",
            "final": False,
            "start_ms": 0,
            "duration_ms": 50,
        }
        final = {
            "text": "Create a report",
            "final": True,
            "start_ms": 0,
            "duration_ms": 100,
        }
        adapter.handle_data("asr_result", partial)
        assert adapter.executor.queue.empty()
        adapter.handle_data("asr_result", final)
        adapter.handle_data("asr_result", final)
        assert adapter.executor.queue.qsize() == 1
        adapter.now = lambda: 190
        await adapter.classify(engine.begin_decision(120))
        assert adapter.executor.queue.qsize() == 1
        adapter.provider.route.assert_not_called()
        engine.start("answer")
        request = memory.voice_request(
            engine.drain_actions()[-1], config, adapter.executor.state
        )
        assert "never wait for its completion" in request["prompt"]
        provider_text = {
            "jev": "Jev classifies the structured state directly.",
            "sd": "ScaleDown classifies the structured state directly.",
            "sd_jev": "ScaleDown compresses the state, then Jev classifies it.",
        }[mode]
        assert provider_text in request["prompt"]
        engine.stop("manual_stop")
        assert (
            adapter.executor.sid == "one-call" and not adapter.executor.failed
        )
        assert adapter.executor.queue.qsize() == 1
        adapter.executor.queue.get_nowait()
        adapter.executor.state = {
            "status": "completed",
            "current": True,
            "notify_user": True,
            "version": 1,
            "input_revision": adapter.executor.latest_revision,
        }
        engine.pending = False
        engine.stopping = None
        before = deepcopy(engine.history)
        adapter.now = lambda: 2000
        adapter.notify_executor()
        assert engine.responses[engine.active]["mode"] == "executor_result"
        assert engine.history == before
        assert adapter.executor.sid == "one-call"

    for fails in (False, True):
        asyncio.run(run(fails))
