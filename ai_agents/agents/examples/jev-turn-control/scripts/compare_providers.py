"""Small synthetic connectivity comparison: Jev vs ScaleDown compression + Jev."""

import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import types

import aiohttp


def load_provider():
    root = (
        Path(__file__).resolve().parents[3]
        / "ten_packages/extension/jev_turn_control_python"
    )
    package = types.ModuleType("jev_compare")
    package.__path__ = [str(root)]
    sys.modules["jev_compare"] = package
    for name in ("config", "provider"):
        spec = importlib.util.spec_from_file_location(
            f"jev_compare.{name}", root / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return (
        sys.modules["jev_compare.provider"].DecisionProvider,
        sys.modules["jev_compare.config"].Config,
    )


async def compare(inputs):
    provider_type, config_type = load_provider()
    provider = provider_type(
        config_type.load({"provider": {"name": "jev", "timeout_ms": 10000}})
    )
    key = os.environ.get("SCALEDOWN_API_KEY")
    if not key or not os.environ.get("JEV_API_KEY"):
        raise ValueError(
            "JEV_API_KEY and SCALEDOWN_API_KEY must be set on the server"
        )
    records = []
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20)
        ) as client:
            for text in inputs:
                request = {
                    "kinds": ["start", "stop", "backchannel"],
                    "state": {
                        "input_text": text,
                        "asr_final": False,
                        "assistant_speaking": True,
                        "heard_context": [],
                        "silence_ms": 150,
                    },
                }
                started = time.monotonic()
                direct = await provider.decide(request)
                row = {
                    "input": text,
                    "jev_ms": round((time.monotonic() - started) * 1000, 1),
                    "jev": direct,
                }
                started = time.monotonic()
                async with client.post(
                    "https://api.scaledown.xyz/compress/raw/",
                    headers={"x-api-key": key},
                    json={
                        "context": json.dumps(request["state"]),
                        "prompt": "Preserve user words, whether the assistant is speaking, and timing for turn-control classification.",
                        "scaledown": {"rate": "auto"},
                    },
                    allow_redirects=False,
                ) as response:
                    if response.status != 200:
                        raise ValueError(f"ScaleDown HTTP {response.status}")
                    compressed = await response.json()
                row["scaledown_ms"] = round(
                    (time.monotonic() - started) * 1000, 1
                )
                optimized = compressed.get(
                    "compressed_prompt"
                ) or compressed.get("results", {}).get("compressed_prompt")
                if not isinstance(optimized, str):
                    raise ValueError("ScaleDown compressed_prompt missing")
                started = time.monotonic()
                row["scaledown_then_jev"] = await provider.decide(
                    {**request, "state": optimized}
                )
                row["second_jev_ms"] = round(
                    (time.monotonic() - started) * 1000, 1
                )
                records.append(row)
    finally:
        await provider.close()
    return {
        "synthetic": True,
        "comparison": "compression plus classification; not two interchangeable classifiers",
        "records": records,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(
        compare(
            [
                "What time does the museum open?",
                "Wait, let me finish my question.",
                "Yes, go on.",
            ]
        )
    )
    args.output.write_text(json.dumps(result, indent=2))
    print("Saved three synthetic live comparisons; no keys included.")


if __name__ == "__main__":
    main()
