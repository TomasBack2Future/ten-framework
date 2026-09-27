"""TEN adapter: reducer + bounded classifier + public LLM/TTS interfaces."""

import asyncio
import json
import math
import os
import struct
import time

import aiohttp

from ten_runtime import (
    AsyncExtension,
    AsyncTenEnv,
    AudioFrame,
    Cmd,
    CmdResult,
    Data,
    Loc,
    StatusCode,
)

from .config import Config
from .engine import TurnEngine
from .provider import DecisionProvider


class JevTurnControlExtension(AsyncExtension):
    def __init__(self, name):
        super().__init__(name)
        self.ten_env = None
        self.engine = None
        self.provider = None
        self.started = 0
        self.last_sent = 0
        self.tasks = set()
        self.generation = None
        self.pump_lock = asyncio.Lock()
        self.asr_segment = 0
        self.audio_response = None

    def now(self):
        return int((time.monotonic() - self.started) * 1000)

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def on_init(self, ten_env: AsyncTenEnv):
        self.ten_env = ten_env
        raw, error = await ten_env.get_property_to_json("")
        if error:
            raise ValueError("cannot read turn configuration")
        self.started = time.monotonic()
        self.engine = TurnEngine(
            Config.load(json.loads(raw or "{}")),
            os.environ.get("JEV_SESSION_ID", "demo"),
        )
        self.provider = DecisionProvider(self.engine.config)
        self.engine.snapshot()

    async def on_start(self, ten_env: AsyncTenEnv):
        self.spawn(self.run_clock())
        ten_env.log_info("JEV_EXTENSION_READY stage=decision_mvp")

    async def run_clock(self):
        while not self.engine.closed:
            self.engine.tick(self.now())
            request = self.engine.begin_decision(self.now())
            if request:
                self.spawn(self.classify(request))
            await self.pump()
            await asyncio.sleep(0.02)

    async def classify(self, request):
        try:
            answers = await self.provider.decide(request)
            self.engine.complete_decision(request, answers, self.now())
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            ValueError,
            KeyError,
            TypeError,
        ):
            self.engine.complete_decision(request, {}, self.now(), error=True)
        await self.pump()

    async def send_data(self, name, payload, destination):
        data = Data.create(name)
        data.set_property_from_json(None, json.dumps(payload))
        data.set_dests([Loc("", "", destination)])
        await self.ten_env.send_data(data)

    async def pump(self):
        async with self.pump_lock:
            if self.engine.config["transport"]["enabled"]:
                for event in list(self.engine.events):
                    if event["seq"] > self.last_sent:
                        self.last_sent = event["seq"]
                        await self.send_data(
                            "jev_event", event, "websocket_server"
                        )
            for action in self.engine.drain_actions():
                if action["type"] == "response.cancel":
                    if self.generation:
                        self.generation.cancel()
                    self.audio_response = None
                    if self.engine.config["provider"]["name"] != "mock":
                        self.spawn(self.abort(action["response_id"]))
                elif action["type"] == "response.start":
                    self.generation = self.spawn(self.generate(action))

    async def abort(self, rid):
        # TTS flush is sent before waiting for any LLM acknowledgment.
        await self.send_data("tts_flush", {"flush_id": rid}, "tts")
        command = Cmd.create("abort")
        command.set_dests([Loc("", "", "llm")])
        command.set_property_string("request_id", rid)
        await self.ten_env.send_cmd(command)

    async def generate(self, action):
        rid = action["response_id"]
        try:
            if self.engine.config["provider"]["name"] == "mock":
                text = action["phrase"] or (
                    "Could you finish that thought?"
                    if action["mode"] == "clarify"
                    else "This is a synthetic response for playback testing."
                )
                self.engine.output(rid, text, self.now(), final=True)
                if self.engine.config["transport"]["mock_audio"]:
                    for _ in range(100):
                        if rid != self.engine.active:
                            break
                        await self.mock_audio(rid)
                        await asyncio.sleep(0.04)
                self.engine.emit(
                    "response.audio_completed", {"synthetic": True}, rid
                )
                await self.pump()
                return
            if action["mode"] == "backchannel":
                self.engine.output(
                    rid, action["phrase"], self.now(), final=True
                )
                await self.tts(rid, action["phrase"], True)
                return
            await self.generate_live(action)
        except (
            Exception
        ):  # Vendor failures must not leak credentials or payloads.
            self.engine.emit(
                "error", {"code": "generation_failed", "recoverable": True}, rid
            )
            if rid == self.engine.active:
                self.engine.stop("generation_failed")
            await self.pump()

    async def generate_live(self, action):
        # Import lazily so the offline graph needs only the public runtime.
        from ten_ai_base.struct import (
            parse_llm_response,
            LLMResponseMessageDelta,
            LLMResponseMessageDone,
        )

        rid = action["response_id"]
        system = "You are a concise helpful voice assistant. Use only supplied heard conversation context."
        if action["mode"] == "clarify":
            system += " Ask one short clarification; do not pretend the user has finished."
        messages = [{"role": "system", "content": system}]
        messages += [
            {"role": item["role"], "content": item["text"]}
            for item in action["context"]
            if item["text"]
        ]
        messages.append({"role": "user", "content": action["input_text"]})
        command = Cmd.create("chat_completion")
        command.set_dests([Loc("", "", "llm")])
        command.set_property_from_json(
            None,
            json.dumps(
                {
                    "request_id": rid,
                    "messages": messages,
                    "streaming": True,
                    "parameters": {"temperature": 0.4},
                    "tools": [],
                }
            ),
        )
        fragment = ""
        async for result, error in self.ten_env.send_cmd_ex(command):
            if rid != self.engine.active:
                return
            if error or (result and result.get_status_code() != StatusCode.OK):
                raise RuntimeError("LLM failed")
            if result is None or result.is_final():
                continue
            raw, _ = result.get_property_to_json(None)
            response = parse_llm_response(raw)
            if isinstance(response, LLMResponseMessageDelta):
                text = response.delta or ""
                if not self.engine.output(rid, text, self.now()):
                    return
                fragment += text
                if (
                    any(
                        mark in fragment
                        for mark in (".", "?", "!", "。", "？", "！")
                    )
                    or len(fragment) >= 100
                ):
                    await self.tts(rid, fragment, False)
                    fragment = ""
            elif isinstance(response, LLMResponseMessageDone):
                self.engine.output(rid, "", self.now(), final=True)
                await self.tts(rid, fragment, True)
                fragment = ""
        # Agent EOS is never used as input turn completion.

    async def tts(self, rid, text, final):
        if rid == self.engine.active:
            await self.send_data(
                "tts_text_input",
                {
                    "request_id": rid,
                    "text": text,
                    "text_input_end": final,
                    "metadata": {
                        "session_id": self.engine.session_id,
                        "response_id": rid,
                    },
                },
                "tts",
            )

    async def mock_audio(self, rid):
        # Recognizable synthetic test tone; not generated speech.
        frame = AudioFrame.create("pcm_frame")
        frame.set_sample_rate(16000)
        frame.set_number_of_channels(1)
        frame.set_bytes_per_sample(2)
        frame.set_samples_per_channel(640)
        frame.alloc_buf(1280)
        buf = frame.lock_buf()
        buf[:] = b"".join(
            struct.pack(
                "<h", int(500 * math.sin(2 * math.pi * 440 * i / 16000))
            )
            for i in range(640)
        )
        frame.unlock_buf(buf)
        frame.set_property_from_json(
            "metadata", json.dumps({"response_id": rid, "synthetic": True})
        )
        frame.set_dests([Loc("", "", "websocket_server")])
        await self.ten_env.send_audio_frame(frame)

    async def on_audio_frame(self, ten_env: AsyncTenEnv, frame: AudioFrame):
        metadata, error = frame.get_property_to_json("metadata")
        meta = json.loads(metadata) if not error and metadata else {}
        request_id, _ = frame.get_property_string("request_id")
        rid = meta.get("response_id") or request_id
        if not rid or rid != self.engine.active:
            return
        meta["response_id"] = rid
        frame.set_property_from_json("metadata", json.dumps(meta))
        frame.set_dests([Loc("", "", "websocket_server")])
        await ten_env.send_audio_frame(frame)

    async def on_data(self, _ten_env: AsyncTenEnv, data: Data):
        raw, error = data.get_property_to_json(None)
        if error:
            return
        try:
            payload = json.loads(raw)
            self.handle_data(data.get_name(), payload)
        except (ValueError, TypeError, KeyError):
            self.engine.emit(
                "error", {"code": "invalid_input", "recoverable": True}
            )
        await self.pump()

    def handle_data(self, name, payload):
        now = self.now()
        if name in ("asr_result", "jev_asr"):
            if (
                name == "jev_asr"
                and self.engine.config["provider"]["name"] != "mock"
            ):
                return
            text, final = payload["text"], payload.get(
                "final", payload.get("is_final", False)
            )
            if not isinstance(text, str) or not isinstance(final, bool):
                raise ValueError("invalid ASR")
            segment = payload.get("segment_id", f"asr-{self.asr_segment}")
            self.engine.input(text, final, now, segment)
            if name == "asr_result" and final:
                self.asr_segment += 1
        elif name == "jev_playback":
            cursor = payload["played_ms"]
            if not isinstance(cursor, (int, float)) or not math.isfinite(
                cursor
            ):
                raise ValueError("invalid playback cursor")
            self.engine.playback(
                payload["response_id"],
                cursor,
                now,
                stopped=payload.get("stopped", False),
                completed=payload.get("completed", False),
            )
        elif name == "jev_control":
            action = payload["action"]
            if action == "snapshot":
                self.engine.snapshot()
            elif action == "stop":
                self.engine.now = now
                self.engine.stop("manual_stop")
            elif action == "pause":
                self.engine.pause(now)
            elif action == "resume":
                self.engine.resume(now)
            elif action == "disconnect":
                self.engine.close(now)
            else:
                raise ValueError("unsupported session control")
        elif name == "tts_audio_start":
            rid = payload.get("request_id")
            if rid == self.engine.active:
                self.audio_response = rid
        elif name == "tts_audio_end":
            rid = payload.get("request_id")
            if rid == self.engine.active:
                self.engine.emit(
                    "response.audio_completed", {"synthetic": False}, rid
                )
        elif name == "tts_text_result":
            rid = payload.get("request_id")
            words = [
                {
                    "text": w.get("word", "") + " ",
                    "end_ms": w.get("start_ms", 0) + w.get("duration_ms", 0),
                }
                for w in payload.get("words", [])
            ]
            self.engine.align(rid, words)

    async def on_cmd(self, ten_env: AsyncTenEnv, cmd: Cmd):
        name = cmd.get_name()
        result = CmdResult.create(StatusCode.OK, cmd)
        if name == "jev_ping":
            nonce, _ = cmd.get_property_string("nonce")
            result.set_property_string("nonce", nonce)
            result.set_property_string("stage", "decision_mvp")
        elif name == "jev_inspect":
            result.set_property_from_json(
                "snapshot", json.dumps(self.engine.snapshot())
            )
        elif name == "jev_input":
            raw, _ = cmd.get_property_to_json(None)
            self.handle_data("jev_asr", json.loads(raw))
            result.set_property_int("input_revision", self.engine.revision)
        else:
            result = CmdResult.create(StatusCode.ERROR, cmd)
        await ten_env.return_result(result)
        await self.pump()

    async def on_stop(self, ten_env: AsyncTenEnv):
        if self.engine:
            self.engine.close(self.now())
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
        if self.provider:
            await self.provider.close()
        ten_env.log_info("JEV_EXTENSION_STOPPED")
