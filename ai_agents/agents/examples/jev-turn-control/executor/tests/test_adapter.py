"""Lifecycle regression tests; all assertions inspect state or real files."""

import asyncio
from dataclasses import replace
import tempfile
import unittest
from pathlib import Path

from executor.adapter import Executor, FakeBackend, Request
from executor.config import ExecutorConfig
from executor.routing import model_input


class ExecutorTests(unittest.IsolatedAsyncioTestCase):
    """No TEN or paid provider required."""

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = FakeBackend()
        self.config = ExecutorConfig(
            enabled=True, work_dir=Path(self.temp.name)
        )
        self.executor = Executor(self.backend, self.config)
        self.request = Request("session", "turn", 1, "Create a demo")

    async def asyncTearDown(self):
        await self.executor.close()
        self.temp.cleanup()

    async def finish(self, task_id):
        await self.executor.records[task_id].runner
        return self.executor.records[task_id]

    async def test_disabled_partial_unsupported(self):
        disabled = Executor(self.backend)
        self.assertIsNone(disabled.submit(self.request))
        for req in (
            replace(self.request, stable=False),
            replace(self.request, support="unsupported"),
            replace(self.request, route="conversation"),
            replace(self.request, support="missing_parameters"),
            replace(self.request, capability="purchase"),
        ):
            self.assertIsNone(self.executor.submit(req))
        self.assertEqual(self.backend.starts, 0)

    async def test_duplicates_one_real_commit(self):
        task_id = self.executor.submit(self.request)
        self.assertEqual(task_id, self.executor.submit(self.request))
        self.assertEqual(
            task_id,
            self.executor.submit(replace(self.request, input_revision=2)),
        )
        record = await self.finish(task_id)
        self.assertEqual(record.status, "completed")
        self.assertEqual(self.backend.starts, 1)
        self.assertEqual(
            next(Path(self.temp.name).rglob("index.html")).read_text(),
            "<h1>Demo</h1>",
        )

    async def test_cancel_before_start_and_cross_session(self):
        task_id = self.executor.submit(self.request)
        with self.assertRaises(ValueError):
            await self.executor.cancel("other", task_id)
        await self.executor.cancel("session", task_id)
        self.assertEqual(self.executor.records[task_id].status, "cancelled")
        self.assertEqual(list(Path(self.temp.name).rglob("*.html")), [])

    async def test_cancel_inflight_and_no_rollback(self):
        self.backend.delay = 0.2
        task_id = self.executor.submit(self.request)
        await asyncio.sleep(0.01)
        await self.executor.cancel("session", task_id)
        self.assertEqual(list(Path(self.temp.name).rglob("*.html")), [])
        other = self.executor.submit(replace(self.request, turn_id="other"))
        await self.finish(other)
        await self.executor.cancel("session", other)
        self.assertEqual(self.executor.records[other].status, "completed")
        self.assertEqual(len(list(Path(self.temp.name).rglob("*.html"))), 1)

    async def test_chitchat_and_speech_stop_do_not_cancel(self):
        task_id = self.executor.submit(self.request)
        for text in ("别念了", "谢谢"):
            self.executor.submit(
                replace(
                    self.request, turn_id=text, text=text, route="conversation"
                )
            )
        self.assertEqual((await self.finish(task_id)).status, "completed")

    async def test_adjust_fences_old_write(self):
        self.backend.delay = 0.2
        task_id = self.executor.submit(self.request)
        await asyncio.sleep(0.01)
        self.backend.plan = {
            "files": [{"name": "index.html", "content": "New"}]
        }
        await self.executor.adjust("session", task_id, 3, "New title")
        record = await self.finish(task_id)
        self.assertEqual(record.request.input_revision, 3)
        self.assertEqual(
            next(Path(self.temp.name).rglob("index.html")).read_text(), "New"
        )
        with self.assertRaises(ValueError):
            await self.executor.adjust("session", task_id, 2, "stale")

    async def test_timeout_and_task_cap(self):
        self.executor.config = replace(
            self.config, timeout=0.001, max_tasks_per_session=1
        )
        task_id = self.executor.submit(self.request)
        self.assertEqual((await self.finish(task_id)).status, "error")
        with self.assertRaises(ValueError):
            self.executor.submit(replace(self.request, turn_id="another"))
        self.assertFalse(list(Path(self.temp.name).rglob("*.html")))

    async def test_invalid_plan_does_not_commit_partial_files(self):
        self.backend.plan = {
            "files": [
                {"name": "good.html", "content": "good"},
                {"name": "../outside.txt", "content": "bad"},
            ]
        }
        task_id = self.executor.submit(self.request)
        self.assertEqual((await self.finish(task_id)).status, "error")
        self.assertFalse(list(Path(self.temp.name).rglob("*.html")))

    async def test_ignore_backend_that_swallows_cancel(self):
        class Uncooperative:
            """Simulate provider completing after cancellation."""

            async def run(self, *_args):
                try:
                    await asyncio.sleep(1)
                except asyncio.CancelledError:
                    return {"files": [{"name": "late.txt", "content": "late"}]}

        self.executor.backend = Uncooperative()
        task_id = self.executor.submit(self.request)
        await asyncio.sleep(0.01)
        await self.executor.cancel("session", task_id)
        self.assertFalse(list(Path(self.temp.name).rglob("*.txt")))

    def test_no_future_gold_or_private_state(self):
        sample = {
            "input": {
                "text": "hello",
                "gold": "execute",
                "future": "buy",
                "initial_config": {"secret": "no"},
            },
            "gold": {"route": "execute"},
        }
        self.assertEqual(
            set(model_input(sample)),
            {"text", "history", "active_tasks", "capabilities", "stable"},
        )

    async def test_completed_adjust_replaces_existing_artifact(self):
        task_id = self.executor.submit(self.request)
        await self.finish(task_id)
        self.backend.plan = {
            "files": [{"name": "index.html", "content": "Updated"}]
        }
        await self.executor.adjust("session", task_id, 2, "Update the heading")
        await self.finish(task_id)
        self.assertEqual(
            next(Path(self.temp.name).rglob("index.html")).read_text(),
            "Updated",
        )
        self.assertEqual(len(list(Path(self.temp.name).rglob("*.html"))), 1)

    async def test_bridge_explicit_session_control(self):
        from executor.bridge import Bridge

        bridge = Bridge(self.executor)
        task_id = await bridge.accept(self.request)
        control = replace(self.request, route="task_control")
        self.assertEqual(
            (await bridge.accept(control, action="status", task_id=task_id))[
                "task_id"
            ],
            task_id,
        )
        self.assertIsNone(
            await bridge.accept(
                replace(control, stable=False), action="cancel", task_id=task_id
            )
        )
        self.assertNotEqual(self.executor.records[task_id].status, "cancelled")
        self.assertEqual(
            await bridge.accept(control, action="cancel", task_id=task_id),
            "cancelled",
        )
