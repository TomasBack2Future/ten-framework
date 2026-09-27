"""SDK boundary contract and cancellation tests against installed public types."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest

from executor.adapter import Record, Request
from executor.config import ExecutorConfig
from executor.sdk_backend import CodexBackend, PLAN_SCHEMA


class SdkTests(unittest.IsolatedAsyncioTestCase):
    """Injected transport does not contact a model or use credentials."""

    async def test_official_call_contract(self):
        calls = {}

        class Handle:
            async def run(self):
                return SimpleNamespace(
                    final_response='{"files":[{"name":"x.txt","content":"ok"}]}',
                    usage=None,
                    status="completed",
                )

        class Thread:
            id = "sdk-thread"

            async def turn(self, prompt, **kwargs):
                calls["turn"] = kwargs
                calls["prompt"] = prompt
                return Handle()

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def thread_start(self, **kwargs):
                calls["thread"] = kwargs
                return Thread()

        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            record = Record("task", Request("session", "turn", 1, "make x.txt"))
            result = await CodexBackend(Client).run(
                record, Path(directory), ExecutorConfig()
            )
        self.assertEqual(record.thread_id, "sdk-thread")
        self.assertEqual(result["files"][0]["name"], "x.txt")
        self.assertEqual(calls["thread"]["model"], "gpt-6-luna")
        self.assertEqual(calls["thread"]["approval_mode"].value, "deny_all")
        self.assertEqual(calls["thread"]["sandbox"].value, "read-only")
        self.assertFalse(calls["thread"]["config"]["features"]["shell_tool"])
        self.assertEqual(calls["turn"]["effort"], "low")
        self.assertEqual(calls["turn"]["output_schema"], PLAN_SCHEMA)

    async def test_cancel_interrupts_sdk_turn(self):
        entered, interrupted = asyncio.Event(), asyncio.Event()

        class Handle:
            async def run(self):
                entered.set()
                await asyncio.sleep(100)

            async def interrupt(self):
                interrupted.set()

        class Thread:
            id = "sdk-thread"

            async def turn(self, *_args, **_kwargs):
                return Handle()

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def thread_start(self, **_kwargs):
                return Thread()

        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            record = Record("task", Request("session", "turn", 1, "make x.txt"))
            running = asyncio.create_task(
                CodexBackend(Client).run(
                    record, Path(directory), ExecutorConfig()
                )
            )
            await entered.wait()
            running.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await running
        self.assertTrue(interrupted.is_set())
