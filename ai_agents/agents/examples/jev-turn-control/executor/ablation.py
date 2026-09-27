"""Three-arm harness; fake runs validate orchestration only, never model benefit."""

# pylint: disable=line-too-long  # Preserve explicit benchmark/prompt text.
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import time

from .adapter import Executor, FakeBackend, Request
from .config import ExecutorConfig, RoutingConfig
from .routing import Router
from .sandbox import tasks, fixture_plan, verify
from .sdk_backend import CodexBackend


async def run(args):
    """Identical task prompts/files/backend across all arms; bounded 12 tasks."""
    routing = RoutingConfig(variant="refined", execute_threshold=0.75)
    routers = {
        "jev": Router("jev", args.jev_key, routing),
        "scaledown": Router("scaledown", args.scaledown_key, routing),
    }
    rows = []
    with tempfile.TemporaryDirectory() as temporary:
        for task in tasks():
            # Three accepted turns per task, no private goal in provider context.
            turns = [
                "Hello, nice to meet you.",
                "Explain what an HTML file is. Do not create anything.",
                task["prompt"],
            ]
            for number, text in enumerate(turns):
                sample = {
                    "input": {
                        "text": text,
                        "history": [
                            {"role": "user", "content": prior}
                            for prior in turns[:number]
                        ],
                        "active_tasks": [],
                        "capabilities": [
                            {
                                "name": "artifact",
                                "description": "Create HTML, CSV, TXT and JSON artifacts locally. No other capabilities.",
                            }
                        ],
                        "stable": True,
                    }
                }
                pair = await asyncio.gather(
                    *(router.classify(sample) for router in routers.values())
                )
                decisions = {
                    "all_accepted": {
                        "route": "execute",
                        "support": "supported",
                        "latency_ms": 0,
                    },
                    **dict(zip(routers, pair)),
                }
                for arm, decision in decisions.items():
                    root = Path(temporary) / task["id"] / arm / str(number)
                    config = ExecutorConfig(enabled=True, work_dir=root)
                    backend = (
                        CodexBackend()
                        if args.backend == "codex"
                        else FakeBackend(
                            fixture_plan(task) if number == 2 else {"files": []}
                        )
                    )
                    executor = Executor(backend, config)
                    start = time.monotonic()
                    ident = executor.submit(
                        Request(
                            "ablation",
                            task["id"],
                            1,
                            text,
                            route=decision["route"],
                            support=decision["support"],
                        )
                    )
                    success = number != 2
                    status = "not_dispatched"
                    usage = {}
                    if ident:
                        await executor.records[ident].runner
                        record = executor.records[ident]
                        status, usage = record.status, record.usage
                        location = (
                            root
                            / hashlib.sha256(b"ablation").hexdigest()[:24]
                            / ident
                        )
                        try:
                            success = (
                                verify(task, location)
                                if number == 2 and status == "completed"
                                else number != 2
                                and not list(location.glob("*"))
                            )
                        except (OSError, ValueError, KeyError):
                            success = False
                    rows.append(
                        {
                            "task": task["id"],
                            "turn": number,
                            "arm": arm,
                            "backend": args.backend,
                            "decision": decision,
                            "dispatched": bool(ident),
                            "success": success,
                            "status": status,
                            "usage": usage,
                            "total_latency_ms": decision["latency_ms"]
                            + (time.monotonic() - start) * 1000,
                            "cost_usd": None,
                            "interpretation": (
                                "model comparison"
                                if args.backend == "codex"
                                else "fake fixture orchestration only; no model benefit inference"
                            ),
                        }
                    )
                    await executor.close()
                print(
                    json.dumps({"task": task["id"], "turn": number}), flush=True
                )
    args.output.write_text("".join(json.dumps(row) + "\n" for row in rows))


def main():
    """Require explicit backend and keys; no unbounded simulator or retries."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("fake", "codex"), required=True)
    parser.add_argument("--jev-key", type=Path, required=True)
    parser.add_argument("--scaledown-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("refuse to overwrite ablation run")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
