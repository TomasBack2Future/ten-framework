"""Read runtime model catalog without borrowing desktop authentication."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import tempfile


async def probe():
    """A catalog entry never proves deployment account entitlement."""
    # Optional SDK is imported only for an explicit probe.
    # pylint: disable=import-outside-toplevel
    from openai_codex import (
        AsyncCodex,
        CodexConfig,
    )  # pylint: disable=import-outside-toplevel
    import importlib.metadata  # pylint: disable=import-outside-toplevel

    with tempfile.TemporaryDirectory(prefix="jev-probe-") as home:
        environment = {
            key: os.environ[key]
            for key in ("PATH", "SYSTEMROOT", "TMPDIR")
            if key in os.environ
        }
        environment.update({"CODEX_HOME": home, "HOME": home})
        async with AsyncCodex(CodexConfig(env=environment, cwd=home)) as client:
            account = await client.account()
            models = await client.models()
            return {
                "sdk": importlib.metadata.version("openai-codex"),
                "isolated_home": True,
                "account_present": account.account is not None,
                "model": "gpt-6-luna",
                "catalog": [
                    m
                    for m in models.model_dump(mode="json")["data"]
                    if m["model"] == "gpt-6-luna"
                ],
                "live_execution": "blocked_no_authorized_deployment_credential",
            }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(asyncio.run(probe()), indent=2) + "\n")
