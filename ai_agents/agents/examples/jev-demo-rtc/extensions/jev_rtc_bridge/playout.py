"""Serialized RTC publisher; no browser PCM queue or claimed audible ACK."""

import asyncio
from collections import deque
import time


class RTCPlayout:
    """Fence replies around flush/unpublish and pace 16 kHz mono PCM.

    All SDK calls go through one lock, so a delayed flush from an older reply
    cannot unpublish the next reply. The sender feeds exactly 10 ms at a time.
    Cursors describe server emission, never confirmed browser playout.
    """

    FRAME_BYTES = 320
    FRAME_MS = 10

    def __init__(self, command, send_frame, feedback, clock=time.monotonic):
        self.command = command
        self.send_frame = send_frame
        self.feedback = feedback
        self.clock = clock
        self.lock = asyncio.Lock()
        self.response = None
        self.queue = deque()
        self.tail = b""
        self.sent_ms = 0
        self.queued_bytes = 0
        self.next_at = 0
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
            self.done = False
            self.next_at = self.clock()

    def enqueue(self, rid, pcm):
        if rid != self.response or self.closed or self.failed or self.done:
            return False
        if self.queued_bytes + len(self.tail) + len(pcm) > 64 * 1024 * 1024:
            raise BufferError("RTC outgoing audio queue exhausted")
        data = self.tail + pcm
        complete = len(data) // self.FRAME_BYTES * self.FRAME_BYTES
        for offset in range(0, complete, self.FRAME_BYTES):
            self.queue.append(data[offset : offset + self.FRAME_BYTES])
        self.queued_bytes += complete
        self.tail = data[complete:]
        return True

    def finish(self, rid):
        if rid != self.response:
            return
        if self.tail:
            self.queue.append(self.tail.ljust(self.FRAME_BYTES, b"\0"))
            self.queued_bytes += self.FRAME_BYTES
            self.tail = b""
        self.done = True

    async def stop(self, rid=None):
        async with self.lock:
            if rid is not None and rid != self.response:
                return
            await self._stop()

    async def _stop(self):
        rid = self.response
        # Invalidate BEFORE any async SDK operation: newly delivered old frames
        # must not be enqueued while a flush is waiting for its command result.
        self.response = None
        self.queue.clear()
        self.tail = b""
        self.queued_bytes = 0
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
        return max(0, self.sent_ms - 250)

    async def step(self):
        async with self.lock:
            if not self.response or self.closed or self.failed:
                return
            if self.muted:
                self.queue.clear()
                self.tail = b""
                self.queued_bytes = 0
                if self.done:
                    rid, self.response = self.response, None
                    await self.feedback(rid, 0, completed=True)
                return
            now = self.clock()
            if now < self.next_at:
                return
            if self.queue:
                if not self.published:
                    await self.command(
                        "publish", {"audio": True, "video": False}
                    )
                    self.published = True
                frame = self.queue.popleft()
                self.queued_bytes -= len(frame)
                await self.send_frame(self.response, frame)
                self.sent_ms += self.FRAME_MS
                # Keep deadlines on the original media clock. Basing each one
                # on send completion accumulates scheduler and SDK overhead,
                # eventually feeding fewer than 100 frames per second.
                interval = self.FRAME_MS / 1000
                self.next_at = max(
                    self.next_at + interval,
                    self.clock() - 0.1,
                    now + interval / 2,
                )
                if self.sent_ms % 200 == 0:
                    await self.feedback(self.response, self.cursor())
            elif self.done and now >= self.next_at + 0.25:
                rid = self.response
                self.response = None
                await self.feedback(rid, self.cursor(), completed=True)

    async def close(self):
        async with self.lock:
            self.closed = True
            await self._stop()
