import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time

from ten_runtime import (
    AsyncExtensionTester,
    AsyncTenEnvTester,
    Cmd,
    StatusCode,
)


class GraphProbe(AsyncExtensionTester):
    def __init__(self):
        super().__init__()
        self.verified = False

    async def on_start(self, ten_env: AsyncTenEnvTester) -> None:
        command = Cmd.create("jev_ping")
        command.set_property_string("nonce", "offline-graph-smoke")
        result, error = await ten_env.send_cmd(command)
        assert error is None, error
        assert result is not None
        assert result.get_status_code() == StatusCode.OK
        assert result.get_property_string("nonce") == (
            "offline-graph-smoke",
            None,
        )
        assert result.get_property_string("stage") == ("bootstrap_only", None)
        self.verified = True
        ten_env.log_info("JEV_GRAPH_ROUNDTRIP_PASS")
        ten_env.stop_test()


def test_graph_roundtrip():
    prop = json.loads(Path("property.json").read_text(encoding="utf-8"))
    graph = prop["ten"]["predefined_graphs"][0]["graph"]
    graph["nodes"].append(
        {
            "type": "extension",
            "name": "ten:test_extension",
            "addon": "ten:test_extension",
            "extension_group": "probe",
        }
    )
    graph["connections"] = [
        {
            "extension": "ten:test_extension",
            "cmd": [
                {"name": "jev_ping", "dest": [{"extension": "turn_control"}]}
            ],
        }
    ]
    tester = GraphProbe()
    tester.set_test_mode_graph(json.dumps(graph))
    error = tester.run()
    assert error is None, error
    assert tester.verified


def test_app_lifecycle():
    """Start the actual shipped graph, wait for addon readiness, then stop."""
    with subprocess.Popen(
        ["../scripts/start.sh"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    ) as process:
        output = bytearray()
        selector = selectors.DefaultSelector()
        assert process.stdout is not None
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if selector.select(timeout=0.2):
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        break
                    output.extend(chunk)
                    if b"JEV_EXTENSION_READY" in output:
                        break
            assert b"JEV_EXTENSION_READY" in output, output.decode(
                errors="replace"
            )
            os.killpg(process.pid, signal.SIGTERM)
            tail, _ = process.communicate(timeout=10)
            output.extend(tail)
            assert process.returncode == 0, output.decode(errors="replace")
            assert b"app run completed." in output
            print("JEV_APP_LIFECYCLE_PASS")
        finally:
            selector.close()
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
