import importlib.util
from pathlib import Path
import unittest

APP = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(
    "rtc_graph", APP / "scripts/run_graph.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GraphTests(unittest.TestCase):
    def test_rtc_media_and_isolated_channel_without_ws_audio(self):
        graph = module.graph_for({}, "a" * 32, 8766)["ten"][
            "predefined_graphs"
        ][0]["graph"]
        nodes = {n["name"]: n for n in graph["nodes"]}
        self.assertEqual(
            nodes["agora_rtc"]["property"]["channel"], "jev-rtc-" + "a" * 32
        )
        self.assertEqual(nodes["websocket_server"]["addon"], "jev_rtc_bridge")
        self.assertNotIn(
            "websocket_server", [n["addon"] for n in graph["nodes"]]
        )
        self.assertEqual(nodes["turn_control"]["addon"], "jev_rtc_control")
        self.assertNotIn(
            "audio_frame",
            next(
                c
                for c in graph["connections"]
                if c["extension"] == "websocket_server"
            ),
        )
        rtc = next(
            c for c in graph["connections"] if c["extension"] == "agora_rtc"
        )
        self.assertEqual(rtc["audio_frame"][0]["dest"], [{"extension": "stt"}])
        self.assertEqual(
            nodes["agora_rtc"]["property"]["app_certificate"],
            "${env:AGORA_APP_CERTIFICATE}",
        )

    def test_invalid_session_and_overrides_rejected(self):
        for session in ["", "../etc", "g" * 32]:
            with self.assertRaises(ValueError):
                module.graph_for({}, session, 8766)
        with self.assertRaises(ValueError):
            module.graph_for({"transport.enabled": False}, "a" * 32, 8766)
