"""Build an independent RTC graph from the unchanged Jev provider pipeline."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import tempfile

APP = Path(__file__).resolve().parents[1]
WS = APP.parent / "jev-turn-control"
spec = importlib.util.spec_from_file_location(
    "jev_ws_graph", WS / "scripts/run_graph.py"
)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def graph_for(overrides, session_id, port, uid=1001, bot_uid=1002):
    if (
        not session_id
        or any(c not in "0123456789abcdef" for c in session_id)
        or len(session_id) != 32
    ):
        raise ValueError("RTC session must be a random 128-bit hex identifier")
    result = base.graph_for("live", overrides)
    graph = result["ten"]["predefined_graphs"][0]["graph"]
    result["ten"]["predefined_graphs"][0]["name"] = "jev_demo_rtc"
    for node in graph["nodes"]:
        if node["name"] == "turn_control":
            node["addon"] = "jev_rtc_control"
        elif node["name"] == "websocket_server":
            # Keep the imported adapter's destination, but substitute an RTC-only
            # bridge. This endpoint carries control/events; it rejects PCM.
            node["addon"] = "jev_rtc_bridge"
            node["property"] = {"port": port}
    graph["connections"] = [
        c for c in graph["connections"] if c["extension"] != "websocket_server"
    ]
    graph["connections"].append(
        {
            "extension": "websocket_server",
            "data": [
                {"name": n, "dest": [{"extension": "turn_control"}]}
                for n in ("jev_control", "jev_rtc_playback")
            ],
        }
    )
    graph["nodes"].append(
        {
            "type": "extension",
            "name": "agora_rtc",
            "addon": "agora_rtc",
            "extension_group": "rtc",
            "property": {
                "app_id": "${env:AGORA_APP_ID}",
                "app_certificate": "${env:AGORA_APP_CERTIFICATE}",
                "channel": "jev-rtc-" + session_id,
                "stream_id": bot_uid,
                "remote_stream_id": uid,
                "subscribe_audio": True,
                "subscribe_audio_sample_rate": 16000,
                "subscribe_audio_num_of_channels": 1,
                "publish_audio": True,
                "publish_data": False,
                "enable_agora_asr": False,
            },
        }
    )
    graph["connections"].append(
        {
            "extension": "agora_rtc",
            "audio_frame": [
                {"name": "pcm_frame", "dest": [{"extension": "stt"}]}
            ],
            "cmd": [
                {"name": n, "dest": [{"extension": "websocket_server"}]}
                for n in (
                    "on_connected",
                    "on_disconnected",
                    "on_connection_failure",
                    "on_connection_error",
                )
            ],
        }
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-only")
    args = parser.parse_args()
    graph = graph_for(
        json.loads(os.environ.get("JEV_SESSION_CONFIG", "{}")),
        os.environ["JEV_SESSION_ID"],
        int(os.environ["JEV_GRAPH_PORT"]),
    )
    if args.write_only:
        Path(args.write_only).write_text(json.dumps(graph, indent=2) + "\n")
        return
    required = [
        "AGORA_APP_ID",
        "AGORA_APP_CERTIFICATE",
        "SONIOX_API_KEY",
        "GROQ_API_KEY",
        "CARTESIA_API_KEY",
    ]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise SystemExit("Missing server credentials: " + ", ".join(missing))
    descriptor, path = tempfile.mkstemp(prefix="jev-rtc-", suffix=".json")
    with os.fdopen(descriptor, "w") as handle:
        json.dump(graph, handle)
    os.environ["JEV_PROPERTY_FILE"] = path
    os.execv("/bin/bash", ["bash", str(APP / "scripts/start.sh")])


if __name__ == "__main__":
    main()
