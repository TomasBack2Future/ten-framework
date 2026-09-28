"""Transport contract tests; real RTC channel acceptance is separate."""

import asyncio
import importlib.util
from pathlib import Path
import unittest

FILE = Path(__file__).parents[1] / "extensions/jev_rtc_bridge/playout.py"
spec = importlib.util.spec_from_file_location("rtc_playout", FILE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PlayoutTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls = []
        self.now = 0

        async def command(name, payload):
            self.calls.append((name, payload))

        async def frame(rid, pcm):
            self.calls.append(("audio", rid, len(pcm)))

        async def feedback(rid, cursor, **flags):
            self.calls.append(("feedback", rid, cursor, flags))

        self.p = module.RTCPlayout(command, frame, feedback, lambda: self.now)

    async def test_chunks_are_paced_without_catchup_bursts(self):
        await self.p.start("r1")
        self.p.enqueue("r1", bytes(1280))
        await self.p.step()
        await self.p.step()
        self.assertEqual(sum(c[0] == "audio" for c in self.calls), 1)
        self.now = 10
        await self.p.step()
        await self.p.step()
        self.assertEqual(sum(c[0] == "audio" for c in self.calls), 2)
        self.assertTrue(all(c[2] == 320 for c in self.calls if c[0] == "audio"))

    async def test_send_overhead_does_not_accumulate_into_frame_schedule(self):
        async def slow_frame(rid, pcm):
            self.calls.append(("audio", rid, len(pcm)))
            self.now += 0.003

        self.p.send_frame = slow_frame
        await self.p.start("r1")
        self.p.enqueue("r1", bytes(320 * 4))
        for now in (0, 0.01, 0.02, 0.03):
            self.now = now
            await self.p.step()
        self.assertEqual(sum(c[0] == "audio" for c in self.calls), 4)

    async def test_late_scheduler_sends_only_one_frame_per_step(self):
        await self.p.start("r1")
        self.p.enqueue("r1", bytes(320 * 20))
        self.now = 1
        await self.p.step()
        await self.p.step()
        self.assertEqual(sum(c[0] == "audio" for c in self.calls), 1)
        self.assertLessEqual(self.p.next_at, self.now + 0.005)

    async def test_flush_unpublish_then_next_reply_publish(self):
        await self.p.start("r1")
        self.p.enqueue("r1", bytes(1280))
        await self.p.step()
        await self.p.stop("r1")
        self.assertFalse(self.p.enqueue("r1", bytes(320)))
        self.assertEqual(
            [c[0] for c in self.calls],
            ["publish", "audio", "flush", "unpublish", "feedback"],
        )
        await self.p.start("r2")
        self.p.enqueue("r2", bytes(320))
        await self.p.stop("r1")
        await self.p.step()
        self.assertEqual(self.calls[-2][0], "publish")
        self.assertEqual(self.calls[-1], ("audio", "r2", 320))

    async def test_delayed_flush_blocks_republish_and_rejects_old_pcm(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed(name, payload):
            self.calls.append((name, payload))
            if name == "flush":
                entered.set()
                await release.wait()

        self.p.command = delayed
        await self.p.start("r1")
        stop = asyncio.create_task(self.p.stop("r1"))
        await entered.wait()
        start = asyncio.create_task(self.p.start("r2"))
        await asyncio.sleep(0)
        self.assertFalse(start.done())
        self.assertFalse(self.p.enqueue("r1", bytes(320)))
        release.set()
        await asyncio.gather(start, stop)
        self.assertEqual(self.p.response, "r2")

    async def test_natural_drain_is_estimate_and_terminal_not_generation_end(
        self,
    ):
        await self.p.start("r1")
        self.p.enqueue("r1", bytes(641))
        self.p.finish("r1")
        self.assertEqual(len(self.p.queue), 3)
        self.assertFalse(any(c[0] == "feedback" for c in self.calls))
        for now in [0, 0.02, 0.04, 0.06, 0.5]:
            self.now = now
            await self.p.step()
        self.assertEqual(
            self.calls[-1], ("feedback", "r1", 0, {"completed": True})
        )
        self.assertFalse(self.p.enqueue("r1", bytes(320)))

    async def test_failed_flush_prevents_next_reply(self):
        await self.p.start("r1")

        async def fail(*_):
            raise RuntimeError("SDK failure")

        self.p.command = fail
        with self.assertRaises(RuntimeError):
            await self.p.stop("r1")
        with self.assertRaises(RuntimeError):
            await self.p.start("r2")
        self.assertFalse(self.p.enqueue("r1", bytes(320)))


if __name__ == "__main__":
    unittest.main()
