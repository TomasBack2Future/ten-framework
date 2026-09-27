"""Lossless disk evidence bypasses reducer retention without credentials."""

import importlib.util
import json
import os
from pathlib import Path
import tarfile

from test_engine import Config, TurnEngine, ROOT

SPEC = importlib.util.spec_from_file_location(
    "evidence_test", ROOT / "evidence.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
Evidence = MODULE.Evidence


def test_full_events_audio_and_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("JEV_EVENT_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("JEV_REVISION", "test-revision")
    monkeypatch.setenv("GROQ_API_KEY", "private-test-credential")
    sink = Evidence("session")
    engine = TurnEngine(
        Config.load({"observation": {"include_text": False}}),
        "session",
        sink.write,
    )
    text = "业务正文" * 7000
    for index in range(350):
        engine.emit("asr.updated", {"text": text, "index": index})
    sink.write(
        "llm.request",
        {
            "messages": [{"content": "private-test-credential 业务正文"}],
            "api_key": "secret",
        },
        "r1",
    )
    sink.audio(b"\x01\x02", {"sample_rate": 16000}, "r1")
    sink.audio(b"\x03\x04", {"sample_rate": 16000}, "r2")
    sink.close()
    rows = [
        json.loads(line)
        for line in (tmp_path / "session/graph.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 353
    assert rows[349]["payload"]["payload"]["text"] == text
    assert engine.events[-1]["payload"]["text"] == "[redacted]"
    assert rows[-1]["payload"]["offset"] == 2
    assert (tmp_path / "session/tts.pcm").read_bytes() == b"\x01\x02\x03\x04"
    assert all(
        row["wall_time_ns"]
        and row["monotonic_ns"]
        and row["revision"] == "test-revision"
        for row in rows
    )
    assert "private-test-credential" not in json.dumps(rows)
    assert rows[350]["payload"]["messages"][0]["content"].endswith("业务正文")
    assert os.stat(tmp_path / "session/graph.jsonl").st_mode & 0o777 == 0o600


def test_export_keeps_audio_and_source_untouched(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "export_evidence_test",
        Path(__file__).parents[1] / "scripts/export_evidence.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    folder = tmp_path / "abc"
    folder.mkdir()
    (folder / "user.pcm").write_bytes(b"\x01\x02")
    result = module.export_session(tmp_path, "abc", tmp_path / "evidence.tgz")
    assert result["files"][0]["bytes"] == 2
    with tarfile.open(tmp_path / "evidence.tgz") as archive:
        assert archive.extractfile("abc/user.pcm").read() == b"\x01\x02"
    assert (folder / "user.pcm").read_bytes() == b"\x01\x02"


async def check_actual_llm_payload():
    import importlib
    import sys
    import types
    from unittest.mock import AsyncMock, Mock
    from ten_ai_base.struct import LLMRequest
    from openai.types.chat import ChatCompletionChunk

    package = types.ModuleType("llm_evidence_test")
    package.__path__ = [str(ROOT.parent / "openai_llm2_python")]
    sys.modules["llm_evidence_test"] = package
    provider = importlib.import_module("llm_evidence_test.openai")
    config = provider.OpenAILLM2Config.model_validate(
        {
            "api_key": "unused-test",
            "emit_evidence": True,
            "prompt": "fallback",
            "model": "test-model",
        }
    )
    env = Mock()
    recorded = []

    async def capture(data):
        raw, _ = data.get_property_to_json(None)
        recorded.append(json.loads(raw))

    env.send_data = AsyncMock(side_effect=capture)
    client = provider.OpenAIChatGPT.__new__(provider.OpenAIChatGPT)
    client.config = config
    client.ten_env = env
    chunk = ChatCompletionChunk(
        id="wire-id",
        choices=[],
        created=1,
        model="test-model",
        object="chat.completion.chunk",
    )

    async def chunks():
        yield chunk

    client.client = types.SimpleNamespace(
        chat=types.SimpleNamespace(
            completions=types.SimpleNamespace(
                create=AsyncMock(return_value=chunks())
            )
        )
    )
    request = LLMRequest.model_validate(
        {
            "request_id": "r1",
            "messages": [{"role": "user", "content": "原文"}],
            "prompt": "actual prompt",
            "streaming": True,
        }
    )
    _results = [item async for item in client.get_chat_completions(request)]
    assert (
        recorded[0]["body"]
        == client.client.chat.completions.create.call_args.kwargs
    )
    assert recorded[0]["body"]["messages"][0] == {
        "role": "system",
        "content": "actual prompt",
    }
    assert recorded[1]["body"]["choices"] == []
    assert recorded[0]["request_id"] == "r1"
    assert "api_key" not in recorded[0]["body"]
    config.emit_evidence = False
    await client.observe("request", "r2", {})
    assert len(recorded) == 2


def test_actual_llm_payload_and_unparsed_empty_choice_are_captured():
    import asyncio

    asyncio.run(check_actual_llm_payload())


def test_storage_collision_is_visible_and_never_overwrites(
    tmp_path, monkeypatch
):
    import pytest

    monkeypatch.setenv("JEV_EVENT_LOG_DIR", str(tmp_path))
    folder = tmp_path / "existing"
    folder.mkdir()
    (folder / "graph.jsonl").write_text("original evidence\n")
    sink = Evidence("existing")
    sink.write("new", {})
    with pytest.raises(RuntimeError, match="evidence storage failed"):
        sink.close()
    assert (folder / "graph.jsonl").read_text() == "original evidence\n"
