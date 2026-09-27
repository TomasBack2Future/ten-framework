"""Session isolation, ordering, stale commits and private HTTP lifecycle."""

import asyncio
import json
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from aiohttp.test_utils import TestClient, TestServer

from executor.call_session import CallSessions, SessionBackend
from executor.config import ExecutorConfig
from executor.service import create_app


def plan(text):
    return {
        "summary": text,
        "notify_user": True,
        "update_artifacts": True,
        "files": [{"name": "notes.txt", "content": text}],
    }


class Backend:
    def __init__(self, *_args):
        self.inputs = []
        self.gates = asyncio.Queue()
        self.closed = False

    async def run(self, item):
        self.inputs.append(item)
        result = await self.gates.get()
        if isinstance(result, Exception):
            raise result
        return result

    async def close(self):
        self.closed = True


class CallSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = CallSessions(
            ExecutorConfig(enabled=True, work_dir=Path(self.temp.name)), Backend
        )

    async def asyncTearDown(self):
        for sid in list(self.manager.calls):
            await self.manager.close(sid)
        self.temp.cleanup()

    async def settle(self):
        for _ in range(12):
            await asyncio.sleep(0)

    def submit(self, sid, revision, text):
        return self.manager.submit(
            sid, {"input_revision": revision, "text": text, "context": "[]"}
        )

    async def test_disabled_never_constructs_backend(self):
        manager = CallSessions(
            backend_factory=lambda *_: self.fail("backend created")
        )
        with self.assertRaises(PermissionError):
            manager.create()
        self.assertEqual(manager.calls, {})

    async def test_one_call_reuses_backend_and_serializes_inputs(self):
        sid = self.manager.create()["session_id"]
        call = self.manager.calls[sid]
        self.submit(sid, 1, "Make a plan")
        await self.settle()
        self.submit(sid, 2, "Use museums")
        self.assertEqual(len(call.backend.inputs), 1)
        call.backend.gates.put_nowait(plan("old"))
        await self.settle()
        self.assertEqual(
            [i["input_revision"] for i in call.backend.inputs], [1, 2]
        )
        self.assertFalse((call.directory / "notes.txt").exists())
        call.backend.gates.put_nowait(plan("museums"))
        await self.settle()
        self.assertEqual((call.directory / "notes.txt").read_text(), "museums")
        self.assertEqual(call.snapshot()["status"], "completed")
        self.submit(sid, 2, "Use museums")
        self.assertEqual(len(call.backend.inputs), 2)
        with self.assertRaises(ValueError):
            self.submit(sid, 2, "conflicting replay")

    async def test_two_calls_never_share_context_or_artifacts(self):
        a, b = [self.manager.create()["session_id"] for _ in range(2)]
        self.submit(a, 1, "Alice")
        self.submit(b, 1, "Bob")
        await self.settle()
        self.assertEqual(
            self.manager.calls[a].backend.inputs[0]["text"], "Alice"
        )
        self.assertEqual(self.manager.calls[b].backend.inputs[0]["text"], "Bob")
        self.assertNotEqual(
            self.manager.calls[a].directory, self.manager.calls[b].directory
        )

    async def test_close_fences_active_work_and_rejects_recreation(self):
        sid = self.manager.create()["session_id"]
        call = self.manager.calls[sid]
        self.submit(sid, 1, "work")
        await self.settle()
        await self.manager.close(sid)
        self.assertTrue(call.backend.closed)
        self.assertFalse(call.directory.exists())
        with self.assertRaises(KeyError):
            self.submit(sid, 2, "continue")

    async def test_failure_is_sanitized_and_never_replaces_thread(self):
        sid = self.manager.create()["session_id"]
        call = self.manager.calls[sid]
        self.submit(sid, 1, "work")
        call.backend.gates.put_nowait(RuntimeError("private-provider-body"))
        await self.settle()
        self.assertEqual(call.snapshot()["code"], "executor_failed")
        self.assertNotIn("private-provider-body", json.dumps(call.snapshot()))
        with self.assertRaises(ValueError):
            self.submit(sid, 2, "retry")

    async def test_queue_limit_does_not_ack_dropped_input(self):
        sid = self.manager.create()["session_id"]
        for i in range(1, 9):
            self.submit(sid, i, "work")
        with self.assertRaises(OverflowError):
            self.submit(sid, 9, "overflow")
        self.assertEqual(self.manager.calls[sid].revision, 8)

    async def test_http_auth_off_submit_poll_close_and_restart(self):
        token = "fake-service-token-not-a-key-123456789"
        async with TestClient(
            TestServer(create_app(self.manager, token))
        ) as client:
            self.assertEqual((await client.post("/sessions")).status, 401)
            headers = {"Authorization": "Bearer " + token}
            response = await client.post("/sessions", headers=headers)
            sid = (await response.json())["session_id"]
            response = await client.post(
                f"/sessions/{sid}/inputs",
                headers=headers,
                json={"input_revision": 1, "text": "work", "context": "[]"},
            )
            self.assertEqual(response.status, 202)
            self.assertIn(
                (await response.json())["status"], ("queued", "running")
            )
            self.manager.calls[sid].backend.gates.put_nowait(plan("done"))
            await self.settle()
            response = await client.get(f"/sessions/{sid}", headers=headers)
            self.assertEqual((await response.json())["status"], "completed")
            await client.delete(f"/sessions/{sid}", headers=headers)
            self.assertEqual(
                (await client.get(f"/sessions/{sid}", headers=headers)).status,
                404,
            )

    @unittest.skipUnless(
        importlib.util.find_spec("openai_codex"),
        "optional SDK installed only in SDK test environment",
    )
    async def test_real_sdk_interface_uses_one_thread_across_turns(self):
        # Inject SDK transport, not a fake replacement for the session backend.
        handle = SimpleNamespace(
            run=AsyncMock(
                return_value=SimpleNamespace(
                    status="completed", final_response=json.dumps(plan("done"))
                )
            ),
            interrupt=AsyncMock(),
        )
        thread = SimpleNamespace(
            id="one-thread", turn=AsyncMock(return_value=handle)
        )
        client = SimpleNamespace(
            __aenter__=AsyncMock(),
            __aexit__=AsyncMock(),
            thread_start=AsyncMock(return_value=thread),
        )
        backend = SessionBackend(
            Path(self.temp.name), self.manager.config, lambda: client
        )
        (backend.directory / "safe.txt").write_text("safe")
        (backend.directory / "private.txt").symlink_to("safe.txt")
        (backend.directory / "oversized.txt").write_text("x" * 65537)
        for text in ("first", "second"):
            await backend.run({"text": text})
        self.assertEqual(client.thread_start.await_count, 1)
        self.assertEqual(thread.turn.await_count, 2)
        self.assertEqual(
            json.loads(thread.turn.call_args_list[1].args[0])["text"], "second"
        )
        payload = json.loads(thread.turn.call_args_list[1].args[0])
        self.assertEqual(payload["current_artifacts"], {"safe.txt": "safe"})
        await backend.close()
        client.__aexit__.assert_awaited_once()
