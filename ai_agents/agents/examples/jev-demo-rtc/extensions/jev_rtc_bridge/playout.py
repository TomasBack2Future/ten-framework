"""Serialized RTC publisher; forward accepted TTS frames without pacing."""

import asyncio
import time


class RTCPlayout:
    """Fence replies around flush/unpublish and immediately forward PCM.

    All SDK calls go through one lock, so a delayed flush from an older reply
    cannot unpublish the next reply. Cursors describe server emission, never
    confirmed browser playout.
    """

    def __init__(self, command, send_frame, feedback, clock=time.monotonic):
        self.command = command
        self.send_frame = send_frame
        self.feedback = feedback
        self.clock = clock
        self.lock = asyncio.Lock()
        self.response = None
        self.sent_ms = 0
        self.last_feedback_ms = 0
        self.finished_at = 0
        self.first_sent_at = None
        self.playback_end_at = 0
        self.done = False
        self.published = False
        self.closed = False
        self.failed = False
        self.muted = False

    async def start(self, rid):
        async with self.lock:
            if self.closed or self.failed:
                raise RuntimeError("RTC publisher unavailable")
            if self.response == rid:
                return
            if self.response:
                await self._stop()
            self.response = rid
            self.sent_ms = 0
            self.last_feedback_ms = 0
            self.done = False
            self.finished_at = 0
            self.first_sent_at = None
            self.playback_end_at = 0

    async def send(self, rid, pcm):
        async with self.lock:
            if (
                rid != self.response
                or self.closed
                or self.failed
                or self.done
                or self.muted
            ):
                return False
            try:
                if not self.published:
                    await self.command("publish", {"audio": True, "video": False})
                    self.published = True
                await self.send_frame(rid, pcm)
            except Exception:
                self.failed = True
                raise
            now = self.clock()
            if self.first_sent_at is None:
                self.first_sent_at = now
            self.playback_end_at = max(self.playback_end_at, now) + len(pcm) / 32000
            self.sent_ms += len(pcm) / 32
            return True

    def finish(self, rid):
        if rid != self.response:
            return
        self.done = True
        self.finished_at = self.clock()

    async def stop(self, rid=None):
        async with self.lock:
            if rid is not None and rid != self.response:
                return
            await self._stop()

    async def _stop(self):
        rid = self.response
        # Invalidate before any SDK operation so old frames cannot be sent
        # while a flush is waiting for its command result.
        self.response = None
        self.done = False
        try:
            await self.command("flush", {})
            await self.command("unpublish", {"audio": True, "video": False})
            self.published = False
        except Exception:
            self.failed = True
            raise
        if rid:
            await self.feedback(rid, self.cursor(), stopped=True)

    def cursor(self):
        # Conservative transport estimate; excludes a network/jitter allowance.
        # Muting is handled as cancellation, so unheard muted audio is excluded.
        if self.first_sent_at is None:
            return 0
        elapsed_ms = (self.clock() - self.first_sent_at) * 1000
        return max(0, int(min(self.sent_ms, elapsed_ms) - 250))

    async def step(self):
        async with self.lock:
            if not self.response or self.closed or self.failed:
                return
            cursor = self.cursor()
            if cursor - self.last_feedback_ms >= 200:
                self.last_feedback_ms = cursor
                await self.feedback(self.response, cursor)
            if self.done and (
                self.muted
                or self.clock() >= max(self.finished_at, self.playback_end_at) + 0.25
            ):
                rid = self.response
                self.response = None
                await self.feedback(
                    rid, 0 if self.muted else self.cursor(), completed=True
                )

    async def close(self):
        async with self.lock:
            self.closed = True
            await self._stop()
