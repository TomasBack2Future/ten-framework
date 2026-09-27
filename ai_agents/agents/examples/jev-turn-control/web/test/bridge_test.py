"""Regression tests for the public TEN WebSocket transport adapter."""

import importlib.util
import json
import sys
from pathlib import Path
import unittest


PATH = (
    Path(__file__).resolve().parents[4]
    / "ten_packages/extension/websocket_server/websocket_server.py"
)
SPEC = importlib.util.spec_from_file_location("websocket_manager", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class Logger:
    """Quiet test logger."""

    def log_error(self, _message):
        pass


class Socket:
    """Collect transport errors."""

    def __init__(self):
        self.messages = []

    async def send(self, data):
        self.messages.append(json.loads(data))


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    """Only demo messages may cross the browser-to-graph boundary."""

    async def test_allowlist_and_invalid_payload(self):
        received = []

        async def callback(name, payload):
            received.append((name, payload))

        manager = MODULE.WebSocketServerManager(
            "127.0.0.1", 8765, Logger(), on_data_callback=callback
        )
        socket = Socket()
        for name in ("jev_control", "jev_playback", "jev_asr"):
            await manager._process_message(  # pylint: disable=protected-access
                json.dumps({"type": "data", "name": name, "data": {}}),
                socket,
                "test",
            )
        self.assertEqual(len(received), 3)
        for value in (
            {"type": "data", "name": "exec", "data": {}},
            {"type": "data", "name": "jev_control", "data": []},
            [],
            {"audio": "%%%"},
        ):
            await manager._process_message(  # pylint: disable=protected-access
                json.dumps(value), socket, "test"
            )
        self.assertEqual(len(received), 3)
        self.assertEqual(len(socket.messages), 4)


if __name__ == "__main__":
    unittest.main()
