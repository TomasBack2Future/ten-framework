"""Multi-turn regression: retained facts, playback boundaries and stale summaries."""

from copy import deepcopy
import importlib
import sys
import types
from unittest.mock import AsyncMock

from test_engine import Config, TurnEngine, ROOT, PACKAGE

memory = importlib.import_module(f"{PACKAGE}.memory")


def exchange(engine, user, reply="Acknowledged.", interrupted=False):
    engine.input(user, True, engine.now + 1000, f"segment-{engine.revision}")
    engine.start("answer")
    action = engine.drain_actions()[-1]
    rid = engine.active
    engine.output(rid, reply, engine.now, final=True)
    engine.audio(rid, 1000, completed=True, timestamp=1700000000000)
    engine.playback(
        rid,
        1000,
        engine.now + 1000,
        stopped=interrupted,
        completed=not interrupted,
    )
    return action, rid


def test_name_and_destination_survive_cancelled_clarifications():
    engine = TurnEngine()
    exchange(
        engine, "My name is Maya. I am flying from Shanghai to San Francisco."
    )
    for fragment in (
        "And",
        "To, uh",
        "Saturday?",
        "Morning",
        "Actually",
        "And then",
        "Yes",
    ):
        exchange(engine, fragment, "Which city?", interrupted=True)
    engine.input("What is my name and destination?", True, 20000, "last")
    engine.start("answer")
    request = memory.voice_request(engine.drain_actions()[-1], engine.config)
    assert "Maya" in request["messages"][0]["content"]
    assert "San Francisco" in request["messages"][0]["content"]
    assert len(request["messages"]) > 12
    assert sum(m["role"] == "system" for m in request["messages"]) == 0
    assert (
        "TEN" in request["prompt"]
        and "executor is disabled" in request["prompt"]
    )


def test_completed_long_reply_is_not_character_rate_truncated():
    engine = TurnEngine()
    text = "Which day of the weekend would you like to fly?"
    _, rid = exchange(engine, "This weekend.", text)
    assert engine.history[-1]["text"] == text
    assert engine.history[-1]["precision"] == "browser_completed_estimate"
    engine.align(rid, [{"text": "Which", "end_ms": 200}])
    assert engine.history[-1]["text"] == text


def test_completion_without_audio_does_not_commit_full_text():
    engine = TurnEngine()
    engine.text = "hello"
    engine.start("answer")
    engine.output(engine.active, "never delivered", 1, final=True)
    engine.playback(engine.active, 0, 2, completed=True)
    assert engine.history[-1]["text"] == ""
    assert not engine.history[-1]["fully_played"]


def test_cartesia_epoch_alignment_before_audio_and_late_correction():
    engine = TurnEngine()
    engine.text = "Hello"
    engine.start("answer")
    rid = engine.active
    engine.output(rid, "Hello world unheard", 10, final=True)
    origin = 1700000000000
    engine.align(
        rid,
        [
            {"text": "Hello ", "end_ms": origin + 300},
            {"text": "world ", "end_ms": origin + 700},
        ],
    )
    assert not engine.responses[rid]["alignment"]
    engine.audio(rid, 2000, timestamp=origin)
    engine.playback(rid, 400, 1000, stopped=True)
    assert engine.history[-1]["text"] == "Hello "
    assert (
        engine.history[-1]["precision"] == "provider_alignment_browser_cursor"
    )
    revision = engine.context_revision
    engine.align(rid, [{"text": "there ", "end_ms": origin + 350}])
    assert engine.context_revision == revision + 1
    assert engine.history[-1]["text"] == "Hello there "
    assert "world" not in engine.history[-1]["text"]


def test_backchannel_and_duplicate_final_do_not_pollute_history():
    engine = TurnEngine()
    engine.input("My name is Maya", False, 0, "s1")
    engine.start("answer")
    engine.input("My name is Maya", True, 50, "s1")
    assert not engine.pending
    engine.playback(engine.active, 0, 60, stopped=True)
    before = deepcopy(engine.history)
    engine.start("backchannel")
    engine.output(engine.active, "Mm-hmm.", 70, final=True)
    engine.audio(engine.active, 400, completed=True)
    engine.playback(engine.active, 400, 500, completed=True)
    assert engine.history == before
    engine.input("My name is Maya", True, 600, "s2")
    assert engine.pending  # Same words in a genuinely new segment remain valid.


def compression_engine():
    engine = TurnEngine(
        Config.load(
            {
                "compression": {
                    "enabled": True,
                    "trigger_chars": 1000,
                    "keep_turns": 2,
                }
            }
        )
    )
    exchange(
        engine,
        "My name is Maya; I cannot eat peanuts. Help plan dinner; no restaurant selected.",
    )
    for i in range(6):
        exchange(
            engine,
            f"Weather question {i}: " + "weather " * 40,
            "Weather answer. " * 15,
        )
    return engine


def test_compression_applies_summary_retains_recent_turns_and_facts():
    engine = compression_engine()
    request = engine.begin_compression(engine.now)
    assert request
    original = deepcopy(engine.history)
    engine.complete_compression(
        request,
        "Maya cannot eat peanuts. Dinner planning pending; no restaurant selected.",
    )
    assert engine.history == original[-4:]
    assert engine.summary.startswith("Maya")
    engine.input(
        "What should we plan for me?", True, engine.now + 1000, "followup"
    )
    engine.start("answer")
    outgoing = memory.voice_request(engine.drain_actions()[-1], engine.config)
    assert "cannot eat peanuts" in outgoing["prompt"]
    assert len(outgoing["messages"]) == 5


def test_compression_stale_failure_and_rejected_results_keep_original():
    for mode in ("input", "alignment", "failure", "oversized", "close"):
        engine = compression_engine()
        request = engine.begin_compression(engine.now)
        original = deepcopy(engine.history)
        if mode == "input":
            # Starting a new response does not wait for compression.
            engine.input("New fact", True, engine.now + 1000, "new")
            engine.start("answer")
            assert engine.active
        elif mode == "alignment":
            engine.context_revision += 1
        elif mode == "close":
            engine.close(engine.now + 1)
        engine.complete_compression(
            request,
            summary="x" * 9000 if mode == "oversized" else "summary",
            error="provider_failure" if mode == "failure" else None,
        )
        assert engine.history[: len(original)] == original
        assert not engine.summary
        assert engine.compression_request is None
        assert engine.events[-1]["type"] in ("context.stale", "context.failed")


def test_interrupted_assistant_is_never_summarized_and_capacity_does_not_evict():
    engine = compression_engine()
    engine.history[1].update(
        text="UNHEARD invented booking", fully_played=False
    )
    request = engine.begin_compression(engine.now)
    assert "UNHEARD" not in str(request["source"])
    engine.complete_compression(request, error="offline")
    engine.config.values["compression"]["enabled"] = False
    while not engine.capacity_reached:
        engine.text = "x" * 1000
        engine.start("answer")
        if engine.active:
            engine.output(engine.active, "y" * 1000, 1, final=True)
            engine.audio(engine.active, 1000, completed=True)
            engine.playback(engine.active, 1000, 2, completed=True)
    assert "Maya" in engine.history[0]["text"]
    assert engine.context_size() <= engine.config["compression"]["max_chars"]


def test_official_adapter_final_http_messages_keep_history(monkeypatch):
    import asyncio
    from ten_ai_base.struct import LLMRequest

    package = types.ModuleType("memory_adapter_test")
    package.__path__ = [str(ROOT.parent / "openai_llm2_python")]
    sys.modules["memory_adapter_test"] = package
    adapter = importlib.import_module("memory_adapter_test.openai")
    logs = []
    env = types.SimpleNamespace(
        log_info=logs.append, log_debug=logs.append, log_warn=logs.append
    )

    async def empty_stream():
        for item in []:
            yield item

    create = AsyncMock(return_value=empty_stream())
    monkeypatch.setattr(
        adapter,
        "AsyncOpenAI",
        lambda **_kw: types.SimpleNamespace(
            chat=types.SimpleNamespace(
                completions=types.SimpleNamespace(create=create)
            )
        ),
    )
    config = adapter.OpenAILLM2Config.model_validate_json(
        '{"api_key":"private-test-key","prompt":"unused fallback"}'
    )
    client = adapter.OpenAIChatGPT(env, config)
    engine = TurnEngine()
    exchange(engine, "My name is Maya.", "Hello Maya.")
    engine.input("What is my name?", True, 5000, "new")
    engine.start("answer")
    payload = memory.voice_request(engine.drain_actions()[-1], engine.config)

    async def run():
        async for _ in client.get_chat_completions(
            LLMRequest.model_validate(payload)
        ):
            pass

    asyncio.run(run())
    wire = create.call_args.kwargs["messages"]
    assert [m["role"] for m in wire] == ["system", "user", "assistant", "user"]
    assert wire[1]["content"] == "My name is Maya."
    assert wire[2]["content"] == "Hello Maya."
    assert "private-test-key" not in " ".join(logs)


def test_late_stop_ack_repairs_old_context_without_touching_new_response():
    engine = TurnEngine()
    engine.text = "Fly to San Francisco"
    engine.start("answer")
    old = engine.active
    engine.output(old, "Confirmed destination. Unheard booking.", 1, final=True)
    engine.audio(old, 20000, timestamp=1700000000000)
    engine.align(
        old,
        [
            {"text": "Confirmed ", "end_ms": 3000},
            {"text": "destination. ", "end_ms": 12000},
            {"text": "Unheard booking.", "end_ms": 18000},
        ],
    )
    engine.stop("user_reclaims_floor")
    engine.playback(old, 4541, 600, stopped=True, confirmed=False)
    engine.text = "Saturday instead"
    engine.start("answer")
    current = engine.active
    engine.playback(old, 13059, 9000, stopped=True)
    assert engine.active == current and engine.stopping is None
    assert engine.history[1]["text"] == "Confirmed destination. "
    assert engine.history[1]["confirmed"]


def test_final_cursor_can_correct_an_earlier_overestimate():
    engine = TurnEngine()
    engine.text = "hello"
    engine.start("answer")
    rid = engine.active
    engine.output(rid, "heard unheard", 1, final=True)
    engine.align(
        rid,
        [{"text": "heard ", "end_ms": 100}, {"text": "unheard", "end_ms": 700}],
    )
    engine.playback(rid, 900, 2)
    engine.playback(rid, 200, 3, stopped=True)
    assert engine.history[-1]["text"] == "heard "


def test_asr_timed_duplicate_final_and_late_partial_are_not_new_turns():
    extension = importlib.import_module(f"{PACKAGE}.extension")
    adapter = extension.JevTurnControlExtension("test_asr")
    adapter.engine = TurnEngine()
    payload = {
        "text": "To San Francisco",
        "final": True,
        "start_ms": 57000,
        "duration_ms": 900,
    }
    adapter.handle_data("asr_result", payload)
    revision = adapter.engine.revision
    adapter.handle_data("asr_result", payload)
    adapter.handle_data(
        "asr_result",
        {**payload, "text": "To San", "final": False, "duration_ms": 400},
    )
    assert adapter.engine.revision == revision
    adapter.handle_data("asr_result", {**payload, "start_ms": 59000})
    assert adapter.engine.revision == revision + 1


def test_generation_retries_once_then_speaks_safe_failure_and_shutdown_aborts():
    import asyncio

    extension = importlib.import_module(f"{PACKAGE}.extension")
    adapter = extension.JevTurnControlExtension("test_failure")
    adapter.engine = TurnEngine(Config.load({"provider": {"name": "jev"}}))
    adapter.engine.text = "Search flights and book one."
    adapter.engine.start("answer")
    action = adapter.engine.drain_actions()[-1]
    adapter.generate_live = AsyncMock(
        side_effect=RuntimeError("tool choice is none")
    )
    adapter.tts = AsyncMock()
    adapter.pump = AsyncMock()
    adapter.abort = AsyncMock()
    env = types.SimpleNamespace(log_info=lambda *_args: None)

    async def run():
        await adapter.generate(action)
        assert adapter.generate_live.await_count == 2
        assert adapter.tts.await_args.args[1].startswith("Sorry")
        assert adapter.engine.responses[adapter.engine.active][
            "text"
        ].startswith("Sorry")
        await adapter.on_stop(env)
        adapter.abort.assert_awaited_once_with(action["response_id"])

    asyncio.run(run())
