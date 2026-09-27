"""Voice continues independently; executor results never create fake user turns."""

import importlib
import os
from unittest.mock import patch

from test_engine import Config, TurnEngine, PACKAGE

client_module = importlib.import_module(f"{PACKAGE}.executor_client")
memory = importlib.import_module(f"{PACKAGE}.memory")


def test_disabled_mailbox_has_no_network_or_worker():
    with patch.dict(os.environ, {}, clear=True):
        client = client_module.ExecutorClient(lambda *_: None, enabled=True)
        client.start()
        client.submit(1, "create file", [])
        assert client.worker is None
        assert client.queue.empty()
        assert client.state["status"] == "disabled"


def test_foreground_generation_does_not_wait_for_executor():
    with patch.dict(os.environ, {"JEV_CODEX_ENABLED": "true"}):
        client = client_module.ExecutorClient(lambda *_: None, enabled=True)
        client.submit(1, "Create a plan", [])
        engine = TurnEngine()
        engine.input("Create a plan", True, 0, "one")
        engine.start("answer")
        action = engine.drain_actions()[0]
        request = memory.voice_request(action, engine.config, client.state)
        assert engine.active
        assert client.queue.qsize() == 1
        assert "never wait for its completion" in request["prompt"]
        assert "executor is disabled" not in request["prompt"]
        engine.stop("manual_stop")
        assert client.queue.qsize() == 1


def test_background_reply_keeps_user_history_and_input_intact():
    engine = TurnEngine()
    engine.input("make a plan", True, 1, "one")
    before = (
        list(engine.history),
        engine.text,
        engine.revision,
        engine.pending,
    )
    engine.start("executor_result")
    after = (list(engine.history), engine.text, engine.revision, engine.pending)
    assert before == after
    action = engine.drain_actions()[0]
    request = memory.voice_request(
        action,
        engine.config,
        {"status": "completed", "current": True, "summary": "done"},
    )
    assert request["messages"] == []
    assert "Briefly relay" in request["prompt"]


def test_duplicate_final_does_not_enqueue_twice_and_overflow_is_explicit():
    with patch.dict(os.environ, {"JEV_CODEX_ENABLED": "true"}):
        events = []
        client = client_module.ExecutorClient(
            lambda *args: events.append(args), enabled=True
        )
        for _ in range(2):
            client.submit(1, "first", [])
        assert client.queue.qsize() == 1
        for revision in range(2, 10):
            client.submit(revision, "later", [])
        assert not client.failed
        assert events[-1][0] == "task.error"
        assert client.queue.qsize() == 8


def test_new_session_default_off_and_no_sdk_import_required():
    assert Config.load()["executor"]["enabled"] is False
    assert (
        Config.load({"executor": {"enabled": True}})["executor"]["enabled"]
        is True
    )


def test_voice_mailbox_to_http_session_handles_followup_without_blocking():
    import asyncio
    from pathlib import Path
    import sys
    import tempfile
    from aiohttp.test_utils import TestServer

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from executor.call_session import CallSessions
    from executor.config import ExecutorConfig
    from executor.service import create_app

    class Delayed:
        def __init__(self, *_):
            self.gates = asyncio.Queue()
            self.inputs = []

        async def run(self, item):
            self.inputs.append(item)
            return await self.gates.get()

        async def close(self):
            pass

    async def until(predicate):
        for _ in range(200):
            if predicate():
                return
            await asyncio.sleep(0.01)
        raise AssertionError("condition did not settle")

    async def check():
        with tempfile.TemporaryDirectory() as directory:
            manager = CallSessions(
                ExecutorConfig(enabled=True, work_dir=Path(directory)), Delayed
            )
            token = "test-service-token-12345678901234567890"
            async with TestServer(create_app(manager, token)) as server:
                events = []
                with patch.dict(
                    os.environ,
                    {
                        "JEV_CODEX_ENABLED": "true",
                        "JEV_EXECUTOR_URL": str(server.make_url("")),
                        "JEV_EXECUTOR_TOKEN": token,
                    },
                ):
                    client = client_module.ExecutorClient(
                        lambda *args: events.append(args), enabled=True
                    )
                    client.start()
                    try:
                        client.submit(1, "make a plan", [])
                        await until(
                            lambda: bool(manager.calls)
                            and len(
                                next(
                                    iter(manager.calls.values())
                                ).backend.inputs
                            )
                            == 1
                        )
                        call = next(iter(manager.calls.values()))
                        original_id = call.id
                        client.submit(2, "include museums", [])
                        await until(lambda: call.revision == 2)
                        result = {
                            "files": [],
                            "summary": "done",
                            "update_artifacts": False,
                            "notify_user": True,
                        }
                        call.backend.gates.put_nowait(result)
                        await until(lambda: len(call.backend.inputs) == 2)
                        call.backend.gates.put_nowait(result)
                        await until(
                            lambda: client.state.get("status") == "completed"
                        )
                        assert client.sid == original_id
                        assert client.state["input_revision"] == 2
                        assert client.state["current"] is True
                        assert any(
                            kind == "task.completed" for kind, _ in events
                        )
                        client.submit(3, "😀" * 16000, ["😀" * 16000])
                        await until(lambda: len(call.backend.inputs) == 3)
                        assert len(call.backend.inputs[-1]["text"]) == 12000
                        assert not client.failed
                        call.backend.gates.put_nowait(result)
                        await until(
                            lambda: client.state.get("status") == "completed"
                            and client.state.get("input_revision") == 3
                        )
                    finally:
                        await client.close()
                    assert not manager.calls

    asyncio.run(check())


def test_result_notification_waits_for_voice_and_input_to_settle():
    import pytest
    from types import SimpleNamespace

    pytest.importorskip("ten_runtime")
    module = importlib.import_module(f"{PACKAGE}.extension")
    extension = module.JevTurnControlExtension("test")
    extension.engine = TurnEngine()
    extension.now = lambda: 2000
    extension.executor_notified = 0
    extension.engine.input("create file", True, 1, "one")
    extension.executor = SimpleNamespace(
        latest_revision=1,
        state={
            "status": "completed",
            "current": True,
            "input_revision": 1,
            "version": 3,
            "notify_user": True,
        },
    )
    extension.notify_executor()
    assert (
        extension.engine.active is None
    )  # Pending user response takes priority.
    extension.engine.pending = False
    extension.engine.config = Config.load({"start": {"enabled": False}})
    extension.notify_executor()
    assert (
        extension.engine.active is None
    )  # The speech-start switch also gates notifications.
    extension.engine.config = Config.load()
    extension.engine.start("answer")
    foreground = extension.engine.active
    extension.notify_executor()
    assert extension.engine.active == foreground
    extension.engine.stop("manual_stop")
    extension.notify_executor()
    assert (
        extension.engine.active is None
    )  # Wait for playback stop acknowledgement.
    extension.engine.stopping = None
    before = list(extension.engine.history)
    extension.notify_executor()
    assert (
        extension.engine.responses[extension.engine.active]["mode"]
        == "executor_result"
    )
    assert extension.engine.history == before
    extension.engine.active = None
    extension.notify_executor()
    assert extension.engine.active is None  # Announce at most once.
    extension.executor.state["version"] = 4
    extension.engine.input("correction", False, 2001, "two")
    extension.engine.pending = False
    extension.notify_executor()
    assert (
        extension.engine.active is None
    )  # Fresh partial cannot interrupt the settling window.
    extension.now = lambda: 4000
    extension.notify_executor()
    assert (
        extension.engine.active is not None
    )  # Abandoned partial is not a final fence.


def test_latest_final_result_remains_current_after_partial():
    engine = TurnEngine()
    engine.input("first", True, 0, "one")
    engine.input("correction", False, 1, "two")
    engine.start("answer")
    action = engine.drain_actions()[0]
    request = memory.voice_request(
        action,
        engine.config,
        {
            "status": "completed",
            "current": True,
            "input_revision": 1,
            "summary": "old",
        },
    )
    assert '"current": true' in request["prompt"]


def test_relay_uses_frozen_result_and_custom_prompt_keeps_contract():
    engine = TurnEngine()
    state = {
        "status": "completed",
        "current": True,
        "summary": "museum plan ready",
    }
    engine.start("executor_result", executor_state=state)
    action = engine.drain_actions()[0]
    state["summary"] = "mutated"
    request = memory.voice_request(
        action,
        Config.load({"voice": {"prompt": "Speak Chinese."}}),
        {"status": "queued"},
    )
    assert "museum plan ready" in request["prompt"]
    assert "mutated" not in request["prompt"]
    assert "never wait for its completion" in request["prompt"]


def test_remote_backpressure_preserves_session_and_retries_same_input():
    import asyncio
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    async def check():
        attempts, accepted, closed = [], [], []
        gate = asyncio.Event()

        async def create(_):
            return web.json_response({"session_id": "same-call"})

        async def submit(request):
            item = await request.json()
            attempts.append(item)
            if not gate.is_set():
                raise web.HTTPTooManyRequests()
            accepted.append(item)
            return web.json_response({"status": "queued"}, status=202)

        async def status(_):
            return web.json_response({"status": "running", "version": 1})

        async def close(_):
            closed.append(True)
            return web.json_response({"status": "closed"})

        app = web.Application()
        app.router.add_post("/sessions", create)
        app.router.add_post("/sessions/same-call/inputs", submit)
        app.router.add_get("/sessions/same-call", status)
        app.router.add_delete("/sessions/same-call", close)
        async with TestServer(app) as server:
            with patch.dict(
                os.environ,
                {
                    "JEV_CODEX_ENABLED": "true",
                    "JEV_EXECUTOR_URL": str(server.make_url("")),
                    "JEV_EXECUTOR_TOKEN": "x" * 32,
                },
            ):
                client = client_module.ExecutorClient(
                    lambda *_: None, enabled=True
                )
                client.start()
                client.submit(1, " first ", [])
                try:
                    for _ in range(100):
                        if len(attempts) >= 2:
                            break
                        await asyncio.sleep(0.02)
                    assert (
                        len(attempts) >= 2 and not closed and not client.failed
                    )
                    gate.set()
                    client.submit(2, "second", [])
                    for _ in range(100):
                        if len(accepted) == 2:
                            break
                        await asyncio.sleep(0.02)
                    assert [x["input_revision"] for x in accepted] == [1, 2]
                    assert accepted[0]["text"] == "first"
                    assert client.sid == "same-call"
                finally:
                    await client.close()
                assert closed == [True]

    asyncio.run(check())
