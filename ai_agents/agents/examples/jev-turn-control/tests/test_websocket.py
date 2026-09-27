"""Real TEN graph and WebSocket loop, including PCM fencing and stop ack."""

import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

import websockets

APP = Path(__file__).resolve().parents[1]


async def exercise():
    for _ in range(100):
        try:
            socket = await websockets.connect(
                "ws://127.0.0.1:8765", open_timeout=1
            )
            break
        except OSError:
            await asyncio.sleep(0.05)
    else:
        raise AssertionError("TEN WebSocket graph did not start")
    async with socket:
        await socket.send(
            json.dumps(
                {
                    "type": "data",
                    "name": "jev_asr",
                    "data": {
                        "text": "What is two plus two?",
                        "final": False,
                        "segment_id": "smoke-1",
                    },
                }
            )
        )
        rid = None
        got_audio = False
        cancelled = False
        await_snapshot = False
        for _ in range(200):
            message = json.loads(await asyncio.wait_for(socket.recv(), 5))
            if message["type"] == "audio":
                assert message["metadata"]["response_id"] == rid
                got_audio = True
                await socket.send(
                    json.dumps(
                        {
                            "type": "data",
                            "name": "jev_control",
                            "data": {"action": "stop"},
                        }
                    )
                )
            elif message.get("name") == "jev_event":
                event = message["data"]
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
                                    "played_ms": 40,
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
                    await_snapshot = True
                elif event["type"] == "state.snapshot" and await_snapshot:
                    assert event["payload"]["phase"] == "listening"
                    assert event["payload"]["context"][-1]["confirmed"]
                    assert got_audio and cancelled
                    return
        raise AssertionError("missing PCM/stop/ack/snapshot loop")


def test_real_websocket_roundtrip():
    with tempfile.TemporaryFile() as log:
        with subprocess.Popen(
            [sys.executable, "scripts/run_graph.py", "--mode", "mock"],
            cwd=APP,
            stdout=log,
            stderr=log,
            start_new_session=True,
        ) as process:
            try:
                asyncio.run(asyncio.wait_for(exercise(), 15))
            finally:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
            assert process.returncode == 0
