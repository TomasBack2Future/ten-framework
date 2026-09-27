"""Exercise an already running demo graph with synthetic PCM16 mono 16kHz.

Never loads provider keys. Optional JEV_GATEWAY_COOKIE authenticates a gateway.
Run from the example: .venv/bin/python scripts/validate_live.py input.pcm
"""

import argparse
import asyncio
import base64
import json
import os
from urllib.parse import urlsplit
from pathlib import Path
import time

import websockets


async def validate(url, pcm_path, output_path):
    headers = {}
    if os.environ.get("JEV_GATEWAY_COOKIE"):
        headers["Cookie"] = os.environ["JEV_GATEWAY_COOKIE"]
    parsed = urlsplit(url)
    origin = os.environ.get("JEV_PUBLIC_ORIGIN") or ("https://" if parsed.scheme == "wss" else "http://") + parsed.netloc
    events = []
    audio_bytes = 0
    rid = None
    cancelled = False
    stop_sent = False
    started = time.monotonic()
    async with websockets.connect(
        url, additional_headers=headers, origin=origin, open_timeout=15
    ) as socket:
        if headers:
            while True:
                ready = json.loads(await asyncio.wait_for(socket.recv(), 20))
                if ready.get("type") == "ready":
                    break
        audio = pcm_path.read_bytes() + bytes(32000)

        async def feed():
            for offset in range(0, len(audio), 3200):
                await socket.send(
                    json.dumps(
                        {
                            "audio": base64.b64encode(
                                audio[offset : offset + 3200]
                            ).decode(),
                            "metadata": {"session_id": "synthetic-validation"},
                        }
                    )
                )
                await asyncio.sleep(0.1)

        sender = asyncio.create_task(feed())
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                message = json.loads(await asyncio.wait_for(socket.recv(), 15))
                if message.get("name") == "jev_event":
                    event = message["data"]
                    events.append(event)
                    if event["type"] == "response.started":
                        rid = event["response_id"]
                    elif event["type"] == "response.cancelled":
                        cancelled = True
                        await socket.send(
                            json.dumps(
                                {
                                    "type": "data",
                                    "name": "jev_playback",
                                    "data": {
                                        "response_id": rid,
                                        "played_ms": 200,
                                        "stopped": True,
                                    },
                                }
                            )
                        )
                        await socket.send(
                            json.dumps(
                                {
                                    "type": "data",
                                    "name": "jev_control",
                                    "data": {"action": "snapshot"},
                                }
                            )
                        )
                    elif event["type"] == "state.snapshot" and cancelled:
                        break
                elif message.get("type") == "audio":
                    assert (
                        message["metadata"]["response_id"] == rid
                    ), "audio response fence missing"
                    audio_bytes += len(base64.b64decode(message["audio"]))
                    if audio_bytes > 6400 and not stop_sent:
                        stop_sent = True
                        await socket.send(
                            json.dumps(
                                {
                                    "type": "data",
                                    "name": "jev_control",
                                    "data": {"action": "stop"},
                                }
                            )
                        )
        finally:
            await sender
            result = {
                "synthetic": True,
                "playback": "simulated cursor; not browser/human listening",
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "audio_bytes": audio_bytes,
                "cancelled": cancelled,
                "events": events,
            }
            output_path.write_text(json.dumps(result, indent=2))
    assert audio_bytes > 0 and cancelled, "no live generated audio/cancel"
    assert any(
        e["type"] == "decision.completed"
        and e["payload"]["provider"] == "jev"
        and e["payload"]["score"] is not None
        for e in events
    ), "no live Jev judgment"
    print(
        json.dumps(
            {
                "audio_bytes": audio_bytes,
                "cancelled": cancelled,
                "events": len(events),
            }
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pcm", type=Path)
    parser.add_argument("--url", default="ws://127.0.0.1:8765")
    parser.add_argument(
        "--output", type=Path, default=Path("/tmp/jev-live-evidence.json")
    )
    args = parser.parse_args()
    asyncio.run(validate(args.url, args.pcm, args.output))


if __name__ == "__main__":
    main()
