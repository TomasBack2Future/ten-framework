"""Image acceptance with real CLI startup and HTTP, but no model/network access."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

from .probe import probe


def main():
    """Run in the non-root, read-only image with network none and private tmpfs."""
    assert os.geteuid() != 0
    assert not os.environ.get("OPENAI_API_KEY")
    result = asyncio.run(probe())
    assert result["sdk"] == "0.157.1" and not result["account_present"]
    token = "smoke-only-service-token-not-a-secret"
    env = {
        **os.environ,
        "JEV_CODEX_ENABLED": "false",
        "JEV_EXECUTOR_TOKEN": token,
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "executor.service"], env=env
    )
    try:
        for _ in range(50):
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:8080/healthz", timeout=1
                ) as response:
                    assert json.load(response) == {"enabled": False}
                    break
            except urllib.error.URLError:
                time.sleep(0.1)
        else:
            raise AssertionError("service did not start")
        for headers, expected in (
            ({}, 401),
            ({"Authorization": "Bearer " + token}, 503),
        ):
            request = urllib.request.Request(
                "http://127.0.0.1:8080/sessions", method="POST", headers=headers
            )
            try:
                urllib.request.urlopen(request, timeout=1)
            except urllib.error.HTTPError as error:
                assert error.code == expected
            else:
                raise AssertionError("disabled session admitted")
    finally:
        process.terminate()
        process.wait(timeout=10)
    enabled = subprocess.run(
        [sys.executable, "-m", "executor.service"],
        env={**env, "JEV_CODEX_ENABLED": "true"},
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert enabled.returncode != 0
    assert b"OPENAI_API_KEY is required" in enabled.stderr
    assert not list(Path("/work/artifacts").glob("*"))
    print(
        "Real CLI startup and disabled HTTP gate passed; no credential or model call."
    )


if __name__ == "__main__":
    main()
