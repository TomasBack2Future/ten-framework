"""RTC media output and loopback-only observation/control transport."""

import asyncio
import json
from contextlib import suppress

from ten_runtime import (
    AsyncExtension,
    AudioFrame,
    Cmd,
    CmdResult,
    Data,
    Loc,
    StatusCode,
)
from websockets.asyncio.server import serve

from .playout import RTCPlayout


class JevRTCBridge(AsyncExtension):
    async def on_init(self, ten_env):
        self.ten_env = ten_env
        raw, error = await ten_env.get_property_to_json("")
        if error:
            raise ValueError("RTC bridge configuration unavailable")
        self.config = json.loads(raw)
        self.clients = set()
        self.connected = asyncio.Event()
        self.server = None
        self.task = None
        self.playout = RTCPlayout(self.command, self.audio, self.feedback)

    async def command(self, name, payload):
        cmd = Cmd.create(name)
        cmd.set_property_from_json(None, json.dumps(payload))
        cmd.set_dests([Loc("", "", "agora_rtc")])
        result, error = await asyncio.wait_for(self.ten_env.send_cmd(cmd), 3)
        if error or result is None or result.get_status_code() != StatusCode.OK:
            raise RuntimeError("RTC command failed: " + name)

    async def data(self, name, payload):
        message = Data.create(name)
        message.set_property_from_json(None, json.dumps(payload))
        message.set_dests([Loc("", "", "turn_control")])
        await self.ten_env.send_data(message)

    async def feedback(self, rid, cursor, **flags):
        await self.data(
            "jev_rtc_playback",
            {"response_id": rid, "played_ms": cursor, **flags},
        )

    async def audio(self, rid, pcm):
        frame = AudioFrame.create("pcm_frame")
        frame.set_sample_rate(16000)
        frame.set_number_of_channels(1)
        frame.set_bytes_per_sample(2)
        frame.set_samples_per_channel(len(pcm) // 2)
        frame.alloc_buf(len(pcm))
        buf = frame.lock_buf()
        buf[:] = pcm
        frame.unlock_buf(buf)
        frame.set_property_from_json(
            "metadata", json.dumps({"response_id": rid})
        )
        frame.set_dests([Loc("", "", "agora_rtc")])
        await self.ten_env.send_audio_frame(frame)

    async def on_start(self, ten_env):
        self.server = await serve(
            self.client, "127.0.0.1", self.config["port"], max_size=16384
        )
        self.task = asyncio.create_task(self.clock())
        ten_env.log_info("JEV_RTC_BRIDGE_READY")

    async def clock(self):
        try:
            while True:
                await self.playout.step()
                await asyncio.sleep(0.005)
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.data("jev_control", {"action": "stop"})
            with suppress(Exception):
                await self.playout.close()
            await self.broadcast(
                {
                    "type": "error",
                    "error": "RTC publisher failed; end this session and reconnect",
                }
            )

    async def broadcast(self, message):
        text = json.dumps(message)
        for client in tuple(self.clients):
            try:
                await asyncio.wait_for(client.send(text), 1)
            except Exception:
                self.clients.discard(client)
                await client.close()

    async def client(self, socket):
        if self.clients:
            await socket.close(1008, "Control client already connected")
            return
        self.clients.add(socket)
        try:
            await asyncio.wait_for(self.connected.wait(), 15)
            await socket.send(json.dumps({"type": "ready"}))
            async for raw in socket:
                message = json.loads(raw)
                payload = message.get("data", {})
                if message.get("name") == "jev_control" and payload.get(
                    "action"
                ) in ("snapshot", "stop", "disconnect"):
                    await self.data("jev_control", payload)
                elif (
                    message.get("name") == "rtc_output"
                    and type(payload.get("muted")) is bool
                ):
                    # Muting output cancels this reply; unmuting resumes only a
                    # subsequent response, never a hidden buffered suffix.
                    self.playout.muted = payload["muted"]
                    if self.playout.muted:
                        await self.data("jev_control", {"action": "stop"})
                else:
                    await socket.close(
                        1008, "RTC control only; PCM and browser ACKs rejected"
                    )
        finally:
            self.clients.discard(socket)
            await self.data("jev_control", {"action": "stop"})

    async def on_data(self, ten_env, data):
        if data.get_name() != "jev_event":
            return
        raw, error = data.get_property_to_json(None)
        if error:
            return
        event = json.loads(raw)
        rid, kind = event.get("response_id"), event["type"]
        if kind == "response.started":
            await self.playout.start(rid)
        elif kind == "response.cancelled":
            await self.playout.stop(rid)
        elif kind == "response.audio_completed":
            self.playout.finish(rid)
        await self.broadcast(
            {"type": "data", "name": "jev_event", "data": event}
        )

    async def on_audio_frame(self, ten_env, frame):
        raw, error = frame.get_property_to_json("metadata")
        if error:
            return
        if (
            frame.get_sample_rate(),
            frame.get_number_of_channels(),
            frame.get_bytes_per_sample(),
        ) != (16000, 1, 2):
            raise ValueError("RTC bridge expects mono PCM16 at 16 kHz")
        rid = json.loads(raw).get("response_id")
        buf = frame.lock_buf()
        pcm = bytes(buf)
        frame.unlock_buf(buf)
        if not pcm or len(pcm) % 2:
            raise ValueError("RTC bridge expects nonempty PCM16 samples")
        try:
            await self.playout.send(rid, pcm)
        except Exception:
            await self.data("jev_control", {"action": "stop"})
            await self.broadcast(
                {
                    "type": "error",
                    "error": "RTC publisher failed; end this session and reconnect",
                }
            )
            raise

    async def on_cmd(self, ten_env, cmd):
        if cmd.get_name() == "on_connected":
            self.connected.set()
        # Connection errors are surfaced rather than treated as an audible ACK.
        if cmd.get_name() in (
            "on_connection_failure",
            "on_connection_error",
            "on_disconnected",
        ):
            self.connected.clear()
            await self.data("jev_control", {"action": "stop"})
            await self.broadcast(
                {"type": "error", "error": "RTC connection interrupted"}
            )
        await ten_env.return_result(CmdResult.create(StatusCode.OK, cmd))

    async def on_stop(self, ten_env):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        with suppress(Exception):
            await self.playout.close()
        if self.server:
            self.server.close()
            await self.server.wait_closed()
