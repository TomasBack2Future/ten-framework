"""Replay empty provider streams and fenced browser stops without network."""

import asyncio
import importlib
import types
from unittest.mock import AsyncMock

import pytest
from ten_ai_base.struct import LLMResponseMessageDone, LLMResponseMessageDelta
from ten_runtime import StatusCode
from test_engine import Config, TurnEngine, PACKAGE

extension = importlib.import_module(f"{PACKAGE}.extension")


def done(text):
    return LLMResponseMessageDone(
        response_id="provider-r", role="assistant", content=text, created=1
    )


def delta(text):
    return LLMResponseMessageDelta(
        response_id="provider-r",
        role="assistant",
        content=text,
        delta=text,
        created=1,
    )


def adapter_for(rounds, before=None):
    adapter = extension.JevTurnControlExtension("generation_recovery")
    adapter.engine = TurnEngine(Config.load({"provider": {"name": "jev"}}))
    adapter.engine.text = "Remember Maya."
    adapter.engine.start("answer")
    action = adapter.engine.drain_actions()[-1]
    calls = []

    async def stream(command):
        calls.append(command)
        if before:
            before(adapter)
        for response in rounds[min(len(calls) - 1, len(rounds) - 1)]:
            result = types.SimpleNamespace(
                get_status_code=lambda: StatusCode.OK,
                is_final=lambda: False,
                get_property_to_json=lambda _path, response=response: (
                    response.model_dump_json(),
                    None,
                ),
            )
            yield result, None

    adapter.ten_env = types.SimpleNamespace(send_cmd_ex=stream)
    adapter.tts = AsyncMock()
    adapter.pump = AsyncMock()
    return adapter, action, calls


@pytest.mark.parametrize(
    "empty", [[], [done("")], [delta(" " * 150), done(" " * 150)]]
)
def test_empty_generation_retries_once_then_fallback(empty):
    adapter, action, calls = adapter_for([empty])
    asyncio.run(adapter.generate(action))
    assert len(calls) == 2
    assert adapter.tts.await_count == 1
    assert adapter.tts.await_args.args[1].startswith("Sorry")
    failures = [
        e for e in adapter.engine.events if e["type"] == "generation.failed"
    ]
    assert [e["payload"]["code"] for e in failures] == [
        "llm_empty_output",
        "llm_empty_output",
    ]
    assert len([x for x in adapter.engine.history if x["role"] == "user"]) == 1


def test_empty_first_attempt_recovers_without_duplicate_tts():
    adapter, action, calls = adapter_for(
        [[done("")], [delta("Hello."), done("Hello.")]]
    )
    asyncio.run(adapter.generate(action))
    assert len(calls) == 2
    assert (
        "".join(call.args[1] for call in adapter.tts.await_args_list)
        == "Hello."
    )
    assert adapter.engine.responses[action["response_id"]]["text"] == "Hello."


def test_done_only_content_is_spoken_once():
    adapter, action, calls = adapter_for([[done("Hello Maya.")]])
    asyncio.run(adapter.generate(action))
    assert len(calls) == 1
    adapter.tts.assert_awaited_once_with(
        action["response_id"], "Hello Maya.", True
    )


def test_partial_stream_failure_does_not_retry_or_duplicate_heard_text():
    adapter, action, calls = adapter_for([[delta("Already sent.")]])
    asyncio.run(adapter.generate(action))
    assert len(calls) == 1
    assert adapter.tts.await_count == 1
    assert adapter.engine.active is None
    assert any(e["type"] == "error" for e in adapter.engine.events)


def test_cancellation_prevents_empty_retry():
    adapter, action, calls = adapter_for(
        [[done("")]], before=lambda a: a.engine.stop("manual_stop")
    )
    asyncio.run(adapter.generate(action))
    assert len(calls) == 1
    adapter.tts.assert_not_awaited()


def test_audio_without_text_prevents_retry():
    adapter, action, calls = adapter_for(
        [[done("")]], before=lambda a: a.engine.audio(a.engine.active, 100)
    )
    asyncio.run(adapter.generate(action))
    assert len(calls) == 1
    adapter.tts.assert_not_awaited()


def test_buffer_control_preserves_reason_and_fences_old_response():
    adapter, action, _calls = adapter_for([[]])
    rid = action["response_id"]
    adapter.handle_data(
        "jev_control",
        {"action": "stop", "reason": "buffer_limit", "response_id": "old"},
    )
    assert adapter.engine.active == rid
    adapter.handle_data(
        "jev_control",
        {"action": "stop", "reason": "buffer_limit", "response_id": rid},
    )
    cancel = [
        e for e in adapter.engine.events if e["type"] == "response.cancelled"
    ]
    assert len(cancel) == 1
    assert cancel[0]["payload"]["reason"] == "buffer_limit"
    adapter.handle_data(
        "jev_control",
        {"action": "stop", "reason": "buffer_limit", "response_id": rid},
    )
    assert (
        len(
            [
                e
                for e in adapter.engine.events
                if e["type"] == "response.cancelled"
            ]
        )
        == 1
    )
