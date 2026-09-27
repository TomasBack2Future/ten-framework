"""Regression reproductions for the independent PR2 lifecycle review."""

import asyncio
import gc
from pathlib import Path
import tempfile
import unittest

from executor.adapter import Executor, FakeBackend, Request
from executor.config import ExecutorConfig


class ReviewLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.get_running_loop()
        self.previous_handler = self.loop.get_exception_handler()
        self.unhandled = []
        self.loop.set_exception_handler(
            lambda _loop, context: self.unhandled.append(context)
        )
        self.temp = tempfile.TemporaryDirectory()
        self.executor = Executor(
            FakeBackend(delay=0.01),
            ExecutorConfig(enabled=True, work_dir=Path(self.temp.name)),
        )
        self.request = Request("review", "turn", 1, "initial")

    async def asyncTearDown(self):
        await self.executor.close()
        self.temp.cleanup()
        await asyncio.sleep(0)
        gc.collect()
        await asyncio.sleep(0)
        self.loop.set_exception_handler(self.previous_handler)
        self.assertEqual(
            self.unhandled, [], "backend cleanup exceptions must be drained"
        )

    def terminal_events(self):
        events = []
        while not self.executor.events.empty():
            event = self.executor.events.get_nowait()
            if event["type"] in (
                "task.completed",
                "task.cancelled",
                "task.error",
            ):
                events.append(event)
        return events

    async def test_cancel_does_not_consume_public_revision(self):
        task = self.executor.submit(self.request)
        await asyncio.sleep(0)
        await self.executor.cancel("review", task)
        await self.executor.adjust("review", task, 2, "valid next revision")
        await self.executor.records[task].runner
        self.assertEqual(self.executor.records[task].request.input_revision, 2)
        self.assertEqual(self.executor.records[task].status, "completed")

    async def test_cleanup_error_cannot_replace_cancel_or_duplicate_terminal(
        self,
    ):
        entered = asyncio.Event()

        class Backend:
            async def run(self, *_args):
                entered.set()
                try:
                    await asyncio.sleep(100)
                except asyncio.CancelledError:
                    raise RuntimeError("cleanup failure") from None

        self.executor.backend = Backend()
        task = self.executor.submit(self.request)
        await entered.wait()
        self.assertEqual(
            await self.executor.cancel("review", task), "cancelled"
        )
        await self.executor.cancel("review", task)
        terminal = self.terminal_events()
        self.assertEqual([e["type"] for e in terminal], ["task.cancelled"])
        self.assertEqual(terminal[0]["payload"]["status"], "cancelled")
        self.assertFalse(list(Path(self.temp.name).rglob("*.html")))

    async def concurrent_adjustments(self, revisions):
        entered, stopping, release = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )

        class Backend:
            async def run(self, record, *_args):
                text = record.request.text
                if text == "initial":
                    entered.set()
                    try:
                        await asyncio.sleep(100)
                    except asyncio.CancelledError:
                        stopping.set()
                        await release.wait()
                        raise
                await asyncio.sleep(0.001)
                return {"files": [{"name": "index.html", "content": text}]}

        self.executor.backend = Backend()
        task = self.executor.submit(self.request)
        await entered.wait()
        first = asyncio.create_task(
            self.executor.adjust(
                "review", task, revisions[0], str(revisions[0])
            )
        )
        await stopping.wait()
        second = asyncio.create_task(
            self.executor.adjust(
                "review", task, revisions[1], str(revisions[1])
            )
        )
        await asyncio.sleep(0.02)
        release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        await self.executor.records[task].runner
        self.assertEqual(self.executor.records[task].request.input_revision, 4)
        self.assertEqual(
            next(Path(self.temp.name).rglob("index.html")).read_text(), "4"
        )
        completions = [
            e["payload"]["input_revision"]
            for e in self.terminal_events()
            if e["type"] == "task.completed"
        ]
        self.assertEqual(completions, sorted(completions))
        return results

    async def test_overlapping_adjust_never_regresses_revision(self):
        await self.concurrent_adjustments((3, 4))

    async def test_lower_revision_waiter_is_rejected_after_newer_adjust(self):
        results = await self.concurrent_adjustments((4, 3))
        self.assertIsInstance(results[1], ValueError)

    async def test_snapshot_replaces_omitted_artifacts(self):
        task = self.executor.submit(self.request)
        await self.executor.records[task].runner
        self.executor.backend.plan = {
            "files": [{"name": "notes.txt", "content": "new"}]
        }
        await self.executor.adjust("review", task, 2, "Replace page with notes")
        await self.executor.records[task].runner
        self.assertFalse(list(Path(self.temp.name).rglob("index.html")))
        self.assertEqual(
            next(Path(self.temp.name).rglob("notes.txt")).read_text(), "new"
        )
        self.assertEqual(
            [a["name"] for a in self.executor.records[task].artifacts],
            ["notes.txt"],
        )
        self.executor.backend.plan = {"files": []}
        await self.executor.adjust("review", task, 3, "Remove all artifacts")
        await self.executor.records[task].runner
        self.assertFalse(list(Path(self.temp.name).rglob("notes.txt")))
        self.assertEqual(self.executor.records[task].artifacts, [])
