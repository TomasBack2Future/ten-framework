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

    async def test_sdk_interrupt_failures_preserve_adapter_cancel(self):
        from unittest.mock import patch
        from executor.adapter import Executor
        import tempfile

        for failure in ("timeout", "rpc_error", "context_error"):
            with self.subTest(failure=failure):
                entered = asyncio.Event()

                class Handle:
                    async def run(self):
                        entered.set()
                        await asyncio.sleep(100)

                    async def interrupt(self):
                        if failure == "timeout":
                            await asyncio.sleep(100)
                        if failure == "rpc_error":
                            raise RuntimeError("provider cleanup rejected")

                class Thread:
                    id = "sdk-review-thread"

                    async def turn(self, *_args, **_kwargs):
                        return Handle()

                class Client:
                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *_args):
                        if failure == "context_error":
                            raise RuntimeError("close failed")

                    async def thread_start(self, **_kwargs):
                        return Thread()

                with tempfile.TemporaryDirectory() as directory, patch(
                    "executor.sdk_backend.INTERRUPT_TIMEOUT_SECONDS", 0.01
                ):
                    executor = Executor(
                        CodexBackend(Client),
                        ExecutorConfig(enabled=True, work_dir=Path(directory)),
                    )
                    task = executor.submit(
                        Request("session", "turn", 1, "make x.txt")
                    )
                    await entered.wait()
                    self.assertEqual(
                        await executor.cancel("session", task), "cancelled"
                    )
                    events = []
                    while not executor.events.empty():
                        events.append(executor.events.get_nowait())
                    terminals = [
                        e for e in events if e["type"] != "task.started"
                    ]
                    self.assertEqual(
                        [e["type"] for e in terminals], ["task.cancelled"]
                    )
                    self.assertEqual(
                        terminals[0]["payload"]["status"], "cancelled"
                    )
                    self.assertEqual(executor.records[task].status, "cancelled")
                    self.assertEqual(list(Path(directory).rglob("*.txt")), [])
                    await executor.close()
