"""Replay captured Cartesia PCM chunk sizes; no provider/network calls."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = (
    Path(__file__).resolve().parents[3]
    / "ten_packages/extension/jev_turn_control_python"
)
PACKAGE = "jev_duration_test"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
for module in ("config", "engine"):
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE}.{module}", ROOT / f"{module}.py"
    )
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
Config = sys.modules[f"{PACKAGE}.config"].Config
TurnEngine = sys.modules[f"{PACKAGE}.engine"].TurnEngine

# b09b9e8 live diagnostic: 50 mono PCM16 chunks, 16 kHz, 291272 bytes.
FRAMES = (
    4036,
    6400,
    2692,
    6400,
    6400,
    5280,
    6400,
    6400,
    4704,
    6400,
    6400,
    5046,
    6400,
    6400,
    5044,
    6400,
    6400,
    5044,
    6400,
    6400,
    5044,
    6400,
    6400,
    5046,
    6400,
    6400,
    5044,
    6400,
    6400,
    5044,
    6400,
    6400,
    5044,
    6400,
    6400,
    5046,
    6400,
    6400,
    5044,
    6400,
    6400,
    4708,
    6400,
    6400,
    5044,
    6400,
    6400,
    5044,
    6400,
    4518,
)
REPORTED_MS = 9094


class DurationAccountingTests(unittest.TestCase):
    def response(self, frames=FRAMES, expected=REPORTED_MS, normal=True):
        engine = TurnEngine()
        engine.text = "A request"
        engine.start("answer")
        rid = engine.active
        engine.output(rid, "Complete answer.", 0, final=True)
        for size in frames:
            engine.audio(rid, (size / 2) / 16000 * 1000)
        engine.audio(rid, completed=True, expected_ms=expected, normal=normal)
        engine.playback(rid, sum(frames) / 32, 10000, completed=True)
        return engine, engine.history[-1]

    def test_real_chunks_match_exact_quantized_total(self):
        self.assertEqual(sum(FRAMES), 291272)
        self.assertEqual(sum(FRAMES) / 32, 9102.25)
        self.assertEqual(
            sum(int(n / 32000 * 1000) for n in FRAMES), REPORTED_MS
        )
        engine, heard = self.response()
        self.assertTrue(heard["fully_played"])
        self.assertEqual(heard["text"], "Complete answer.")
        self.assertEqual(
            engine.finished[heard["response_id"]]["audio_ms"], 9102.25
        )

    def test_missing_or_duplicate_chunk_is_not_accepted(self):
        for frames in [FRAMES[1:], FRAMES + FRAMES[:1]]:
            with self.subTest(frames=len(frames)):
                self.assertFalse(self.response(frames)[1]["fully_played"])

    def test_arbitrary_discrepancy_inside_frame_count_bound_is_rejected(self):
        self.assertFalse(
            self.response(expected=REPORTED_MS + 1)[1]["fully_played"]
        )

    def test_missing_or_abnormal_end_still_rejected(self):
        for expected, normal in [(None, True), (REPORTED_MS, False)]:
            with self.subTest(expected=expected, normal=normal):
                self.assertFalse(
                    self.response(expected=expected, normal=normal)[1][
                        "fully_played"
                    ]
                )

    def test_accurate_total_remains_supported(self):
        self.assertTrue(
            self.response(expected=round(sum(FRAMES) / 32))[1]["fully_played"]
        )

    def test_false_flag_excludes_assistant_from_summary_source(self):
        engine, _ = self.response()
        engine.history[1]["fully_played"] = False
        engine.history[0]["text"] = "a" * 1100
        engine.history.append({"role": "user", "text": "Recent turn"})
        engine.config = Config.load(
            {
                "compression": {
                    "enabled": True,
                    "trigger_chars": 1000,
                    "keep_turns": 1,
                }
            }
        )
        request = engine.begin_compression(20000)
        self.assertEqual([x["role"] for x in request["source"]], ["user"])

    def test_invalid_expected_values_never_confirm_playback(self):
        for expected in [
            True,
            0,
            -1,
            float("nan"),
            float("inf"),
            "9094",
            3600001,
        ]:
            with self.subTest(expected=expected):
                self.assertFalse(
                    self.response(expected=expected)[1]["fully_played"]
                )

    def test_new_response_and_session_reset_both_duration_counters(self):
        engine, _ = self.response()
        engine.text = "Next request"
        engine.start("answer")
        next_response = engine.responses[engine.active]
        self.assertEqual(next_response["audio_ms"], 0)
        self.assertEqual(next_response["audio_chunk_floor_ms"], 0)
        engine.audio(engine.active, FRAMES[0] / 32)
        self.assertEqual(next_response["audio_chunk_floor_ms"], 126)
        new_session = TurnEngine(session_id="new-session")
        new_session.text = "A new session"
        new_session.start("answer")
        fresh = new_session.responses[new_session.active]
        self.assertEqual(fresh["audio_ms"], 0)
        self.assertEqual(fresh["audio_chunk_floor_ms"], 0)
        new_session.audio(engine.active, 200)
        self.assertEqual(fresh["audio_chunk_floor_ms"], 0)

    def test_quantization_does_not_override_short_cursor_or_stop(self):
        for stopped, confirmed, played_ms in [
            (True, True, 9102.25),
            (False, False, 9102.25),
            (False, True, 500),
        ]:
            with self.subTest(
                stopped=stopped, confirmed=confirmed, played_ms=played_ms
            ):
                engine = TurnEngine()
                engine.text = "Question"
                engine.start("answer")
                rid = engine.active
                engine.output(rid, "Complete answer.", 0, final=True)
                for size in FRAMES:
                    engine.audio(rid, size / 32000 * 1000)
                engine.audio(rid, completed=True, expected_ms=REPORTED_MS)
                engine.playback(
                    rid,
                    played_ms,
                    10000,
                    stopped=stopped,
                    completed=True,
                    confirmed=confirmed,
                )
                self.assertFalse(engine.history[-1]["fully_played"])

    def test_adapter_drops_late_frames_after_stop_and_across_sessions(self):
        import asyncio
        import importlib
        from unittest.mock import AsyncMock
        from ten_runtime import AudioFrame

        extension = importlib.import_module(f"{PACKAGE}.extension")
        adapter = extension.JevTurnControlExtension("duration_fence")
        adapter.engine = TurnEngine(session_id="old-session")
        adapter.engine.text = "Question"
        adapter.engine.start("answer")
        rid = adapter.engine.active
        env = types.SimpleNamespace(send_audio_frame=AsyncMock())
        adapter.ten_env = env
        frame = AudioFrame.create("pcm_frame")
        frame.set_sample_rate(16000)
        frame.set_number_of_channels(1)
        frame.set_bytes_per_sample(2)
        frame.set_samples_per_channel(FRAMES[0] // 2)
        frame.alloc_buf(FRAMES[0])
        frame.set_property_string("request_id", rid)

        async def check():
            await adapter.on_audio_frame(env, frame)
            response = adapter.engine.responses[rid]
            self.assertEqual(response["audio_chunk_floor_ms"], 126)
            env.send_audio_frame.assert_awaited_once()
            adapter.engine.stop("test interruption")
            await adapter.on_audio_frame(env, frame)
            self.assertEqual(response["audio_chunk_floor_ms"], 126)
            env.send_audio_frame.assert_awaited_once()
            adapter.engine.playback(rid, 126.125, 100, stopped=True)
            await adapter.on_audio_frame(env, frame)
            self.assertFalse(adapter.engine.history[-1]["fully_played"])
            adapter.engine = TurnEngine(session_id="new-session")
            adapter.engine.text = "New question"
            adapter.engine.start("answer")
            await adapter.on_audio_frame(env, frame)
            fresh = adapter.engine.responses[adapter.engine.active]
            self.assertEqual(fresh["audio_ms"], 0)
            self.assertEqual(fresh["audio_chunk_floor_ms"], 0)
            env.send_audio_frame.assert_awaited_once()

        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
