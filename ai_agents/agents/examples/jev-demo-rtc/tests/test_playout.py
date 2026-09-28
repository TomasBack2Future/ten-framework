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

    async def test_chunks_are_forwarded_immediately_without_agent_queue(self):
        await self.p.start("r1")
        self.assertEqual(self.calls, [])
        await self.p.send("r1", bytes(1280))
        await self.p.send("r1", bytes(640))
        self.assertEqual(
            [c for c in self.calls if c[0] == "audio"],
            [("audio", "r1", 1280), ("audio", "r1", 640)],
        )

    async def test_flush_unpublish_then_next_reply_publish(self):
        await self.p.start("r1")
        await self.p.send("r1", bytes(1280))
        await self.p.stop("r1")
        self.assertFalse(await self.p.send("r1", bytes(320)))
        self.assertEqual(
            [c[0] for c in self.calls],
            ["publish", "audio", "flush", "unpublish", "feedback"],
        )
        await self.p.start("r2")
        await self.p.stop("r1")
        await self.p.send("r2", bytes(320))
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
        release.set()
        await asyncio.gather(start, stop)
        self.assertEqual(self.p.response, "r2")
        self.assertFalse(await self.p.send("r1", bytes(320)))

    async def test_natural_drain_is_estimate_and_terminal_not_generation_end(
        self,
    ):
        await self.p.start("r1")
        await self.p.send("r1", bytes(640))
        self.p.finish("r1")
        self.assertFalse(any(c[0] == "feedback" for c in self.calls))
        self.now = 0.24
        await self.p.step()
        self.assertFalse(any(c[0] == "feedback" for c in self.calls))
        self.now = 0.27
        await self.p.step()
        self.assertEqual(
            self.calls[-1], ("feedback", "r1", 0, {"completed": True})
        )
        self.assertFalse(await self.p.send("r1", bytes(320)))

    async def test_generation_end_does_not_complete_before_forwarded_audio_duration(self):
        await self.p.start("r1")
        await self.p.send("r1", bytes(32000))
        self.p.finish("r1")
        self.now = 0.5
        await self.p.step()
        self.assertEqual(self.p.response, "r1")
        self.now = 1.25
        await self.p.step()
        self.assertEqual(self.p.response, None)
        self.assertEqual(
            self.calls[-1], ("feedback", "r1", 750, {"completed": True})
        )

    async def test_failed_flush_prevents_next_reply(self):
        await self.p.start("r1")

        async def fail(*_):
            raise RuntimeError("SDK failure")

        self.p.command = fail
        with self.assertRaises(RuntimeError):
            await self.p.stop("r1")
        with self.assertRaises(RuntimeError):
            await self.p.start("r2")
        self.assertFalse(await self.p.send("r1", bytes(320)))


if __name__ == "__main__":
    unittest.main()
