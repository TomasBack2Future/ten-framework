"""Exercise RTC feedback against the real, unchanged Jev reducer."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest

from test_playout import module as transport

ROOT = (
    Path(__file__).resolve().parents[3]
    / "ten_packages/extension/jev_turn_control_python"
)
PACKAGE = "rtc_reducer_contract"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
for name in ("config", "engine"):
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE}.{name}", ROOT / f"{name}.py"
    )
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
Config = sys.modules[f"{PACKAGE}.config"].Config
TurnEngine = sys.modules[f"{PACKAGE}.engine"].TurnEngine


class ReducerTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_ack_and_natural_drain_remain_unconfirmed(self):
        engine = TurnEngine(
            Config.load({"provider": {"profile": "baseline"}}), "rtc-test"
        )
        engine.input("Tell me the weather?", True, 0, "s1")
        request = engine.begin_decision(120)
        engine.complete_decision(
            request,
            {
                "start": {
                    "label": "answer",
                    "score": 0.95,
                    "probabilities": {"answer": 0.95},
                }
            },
            200,
        )
        engine.tick(450)
        first = engine.active
        self.assertIsNotNone(first)

        async def command(*_):
            pass

        async def audio(*_):
            pass

        async def feedback(rid, cursor, **flags):
            engine.playback(rid, cursor, 500, confirmed=False, **flags)

        p = transport.RTCPlayout(command, audio, feedback, lambda: 0)
        await p.start(first)
        await p.send(first, bytes(320))
        engine.stop("manual_stop")
        await p.stop(first)
        self.assertIsNone(engine.stopping)
        self.assertFalse(engine.finished[first]["terminal_confirmed"])
        self.assertFalse(engine.finished[first]["fully_played"])
        self.assertFalse(engine.history[-1]["confirmed"])

        engine.input("And tomorrow?", True, 600, "s2")
        request = engine.begin_decision(720)
        engine.complete_decision(
            request,
            {
                "start": {
                    "label": "answer",
                    "score": 0.95,
                    "probabilities": {"answer": 0.95},
                }
            },
            800,
        )
        engine.tick(1050)
        second = engine.active
        self.assertIsNotNone(second)
        self.assertNotEqual(first, second)
        await p.start(second)
        p.finish(second)
        p.clock = lambda: 1
        await p.step()
        self.assertIsNone(engine.active)
        self.assertFalse(engine.finished[second]["fully_played"])
        self.assertFalse(engine.history[-1]["confirmed"])
