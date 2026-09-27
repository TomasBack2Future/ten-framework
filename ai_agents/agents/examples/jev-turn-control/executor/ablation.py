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


def score_turn(number, dispatched, terminal_success):
    """Keep filesystem outcome separate from the routing dispatch policy."""
    expected_dispatch = number == 2
    policy_success = dispatched == expected_dispatch
    return {
        "terminal_state_success": terminal_success,
        "dispatch_policy_success": policy_success,
        "unexpected_dispatch": dispatched and not expected_dispatch,
        "missed_dispatch": expected_dispatch and not dispatched,
        "success": terminal_success and policy_success,
    }


async def run(args):
    """Identical task prompts/files/backend across all arms; bounded 12 tasks."""
    routing = RoutingConfig(variant="refined", execute_threshold=0.75)
    cache = {}
    routers = {}
    if args.cached_decisions:
        for line in args.cached_decisions.read_text().splitlines():
            row = json.loads(line)
            cache[(row["task"], row["turn"], row["arm"])] = row["decision"]
    else:
        if not args.jev_key or not args.scaledown_key:
            raise ValueError("both provider key files are required")
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
                providers = ("jev", "scaledown")
                pair = (
                    [
                        cache[(task["id"], number, provider)]
                        for provider in providers
                    ]
                    if cache
                    else await asyncio.gather(
                        *(
                            routers[provider].classify(sample)
                            for provider in providers
                        )
                    )
                )
                decisions = {
                    "all_accepted": {
                        "route": "execute",
                        "support": "supported",
                        "latency_ms": 0,
                    },
                    **dict(zip(providers, pair)),
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
                                and status == "completed"
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
                            **score_turn(number, bool(ident), success),
                            "routing_observation": (
                                "replayed" if cache else "live"
                            ),
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
    parser.add_argument("--jev-key", type=Path)
    parser.add_argument("--scaledown-key", type=Path)
    parser.add_argument("--cached-decisions", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("refuse to overwrite ablation run")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
