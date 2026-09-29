"""Create one private session graph; exec the public TEN app without editing it."""

import argparse
import json
import os
from pathlib import Path
import tempfile

APP = Path(__file__).resolve().parents[1]


def graph_for(mode, overrides):
    config = {
        "provider": {"name": "jev" if mode == "live" else "mock"},
        "transport": {"enabled": True, "mock_audio": mode == "mock"},
        "observation": {"include_text": True},
    }
    allowed = {
        "provider.name",
        "provider.profile",
        "voice.prompt",
        "voice.language",
        "executor.enabled",
        "compression.enabled",
        "compression.prompt",
        "compression.summary_prompt",
        "compression.trigger_chars",
        "compression.keep_turns",
        "compression.timeout_ms",
        "turn.enabled",
        "start.enabled",
        "stop.enabled",
        "backchannel.enabled",
        "start.prompt",
        "stop.prompt",
        "backchannel.prompt",
    }
    for key, value in overrides.items():
        if key not in allowed:
            raise ValueError("unsupported session override")
        if key == "provider.name" and value not in ("jev", "sd", "sd_jev"):
            raise ValueError("invalid decision mode")
        if key == "provider.profile" and value not in ("baseline", "tuned"):
            raise ValueError("invalid decision profile")
        if key == "voice.language" and value not in ("en", "ja"):
            raise ValueError("invalid voice language")
        if key.endswith(".enabled") and not isinstance(value, bool):
            raise ValueError("boolean required")
        if key.endswith("prompt") and (
            not isinstance(value, str) or len(value) > 2000
        ):
            raise ValueError("prompt must be at most 2000 characters")
        limits = {
            "compression.trigger_chars": (1000, 24000),
            "compression.keep_turns": (1, 12),
            "compression.timeout_ms": (1000, 30000),
        }
        if key in limits and (
            type(value) is not int
            or not limits[key][0] <= value <= limits[key][1]
        ):
            raise ValueError("numeric setting outside allowed range")
        if (
            key == "executor.enabled"
            and value
            and os.environ.get("JEV_CODEX_ENABLED") != "true"
        ):
            raise ValueError("executor unavailable")
        section, option = key.split(".")
        config.setdefault(section, {})[option] = value
    # Mock transport must never call paid providers, regardless of UI selection.
    if mode == "mock":
        config["provider"]["name"] = "mock"
    language = config.get("voice", {}).get("language", "en")
    graph = {
        "nodes": [
            {
                "type": "extension",
                "name": "turn_control",
                "addon": "jev_turn_control_python",
                "extension_group": "control",
                "property": config,
            },
            {
                "type": "extension",
                "name": "websocket_server",
                "addon": "websocket_server",
                "extension_group": "transport",
                "property": {
                    "host": "127.0.0.1",
                    "port": int(os.environ.get("JEV_GRAPH_PORT", "8765")),
                    "sample_rate": 16000,
                    "channels": 1,
                    "bytes_per_sample": 2,
                },
            },
        ],
        "connections": [
            {
                "extension": "websocket_server",
                "data": [
                    {"name": name, "dest": [{"extension": "turn_control"}]}
                    for name in ("jev_asr", "jev_control", "jev_playback")
                ],
            }
        ],
    }
    if mode == "live":
        graph["nodes"] += [
            {
                "type": "extension",
                "name": "stt",
                "addon": "soniox_asr_python",
                "extension_group": "stt",
                "property": {
                    "url": "wss://stt-rt.soniox.com/transcribe-websocket",
                    "sample_rate": 16000,
                    "holding_mode": "false",
                    "params": {
                        "api_key": "${env:SONIOX_API_KEY}",
                        "model": "${env:SONIOX_MODEL|stt-rt-v3}",
                        "audio_format": "pcm_s16le",
                        "sample_rate": 16000,
                        "num_channels": 1,
                        "enable_endpoint_detection": True,
                    },
                },
            },
            {
                "type": "extension",
                "name": "llm",
                "addon": "openai_llm2_python",
                "extension_group": "llm",
                "property": {
                    "base_url": "https://api.groq.com/openai/v1",
                    "emit_evidence": bool(os.environ.get("JEV_EVENT_LOG_DIR")),
                    "api_key": "${env:GROQ_API_KEY}",
                    "model": "${env:GROQ_MODEL|openai/gpt-oss-20b}",
                    "max_tokens": 512,
                    "prompt": "",
                    "greeting": "",
                    "frequency_penalty": 0.0,
                },
            },
            {
                "type": "extension",
                "name": "tts",
                "addon": "cartesia_tts",
                "extension_group": "tts",
                "property": {
                    "sample_rate": 16000,
                    "enable_words": True,
                    "params": {
                        "api_key": "${env:CARTESIA_API_KEY}",
                        "base_url": "wss://api.cartesia.ai",
                        "model_id": "${env:CARTESIA_MODEL|sonic-3}",
                        "voice": {
                            "mode": "id",
                            "id": (
                                "7ca2afba-a719-4f06-9af2-ea2b8e3cf14c"
                                if language == "ja"
                                else "${env:CARTESIA_VOICE_ID|a0e99841-438c-4a64-b679-ae501e7d6091}"
                            ),
                        },
                        "language": language,
                    },
                },
            },
        ]
        graph["connections"] += [
            {
                "extension": "llm",
                "data": [
                    {
                        "name": "llm_evidence",
                        "dest": [{"extension": "turn_control"}],
                    }
                ],
            },
            {
                "extension": "websocket_server",
                "audio_frame": [
                    {"name": "pcm_frame", "dest": [{"extension": "stt"}]}
                ],
            },
            {
                "extension": "stt",
                "data": [
                    {
                        "name": "asr_result",
                        "dest": [{"extension": "turn_control"}],
                    }
                ],
            },
            {
                "extension": "tts",
                "audio_frame": [
                    {
                        "name": "pcm_frame",
                        "dest": [{"extension": "turn_control"}],
                    }
                ],
                "data": [
                    {"name": name, "dest": [{"extension": "turn_control"}]}
                    for name in (
                        "tts_audio_start",
                        "tts_audio_end",
                        "tts_text_result",
                    )
                ],
            },
        ]
    return {
        "ten": {
            "predefined_graphs": [
                {"name": "jev_turn_control", "auto_start": True, "graph": graph}
            ],
            "log": {
                "handlers": [
                    {
                        "matchers": [{"level": "error"}],
                        "formatter": {"type": "plain", "colored": False},
                        "emitter": {
                            "type": "console",
                            "config": {"stream": "stdout"},
                        },
                    }
                ]
            },
        }
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("mock", "live"),
        default=os.environ.get("JEV_MODE", "mock"),
    )
    parser.add_argument(
        "--write-only",
        help="write graph without starting (no secrets included)",
    )
    args = parser.parse_args()
    overrides = json.loads(os.environ.get("JEV_SESSION_CONFIG", "{}"))
    graph = graph_for(args.mode, overrides)
    if args.write_only:
        Path(args.write_only).write_text(
            json.dumps(graph, indent=2) + "\n", encoding="utf-8"
        )
        return
    if args.mode == "live":
        decision_mode = overrides.get("provider.name", "jev")
        required = ["SONIOX_API_KEY", "GROQ_API_KEY", "CARTESIA_API_KEY"]
        if decision_mode in ("jev", "sd_jev"):
            required.append("JEV_API_KEY")
        if decision_mode in ("sd", "sd_jev"):
            required.append("SCALEDOWN_API_KEY")
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            raise SystemExit(
                "Missing server credentials: " + ", ".join(missing)
            )
    descriptor, path = tempfile.mkstemp(prefix="jev-session-", suffix=".json")
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(graph, handle)
    os.environ["JEV_PROPERTY_FILE"] = path
    os.execv(str(APP / "scripts/start.sh"), [str(APP / "scripts/start.sh")])


if __name__ == "__main__":
    main()
