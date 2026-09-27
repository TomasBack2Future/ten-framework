"""Bounded paired provider evaluation. Never sends gold or source metadata."""

# pylint: disable=broad-exception-caught  # Sanitize provider boundary failures.

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import statistics

from .config import RoutingConfig
from .routing import Router, ROUTES


def metrics(rows):
    """Errors count as wrong; actual-dispatch metrics include support/stability."""
    matrix = {key: {p: 0 for p in (*ROUTES, "error")} for key in ROUTES}
    tp = fp = fn = support_ok = false_dispatch = non_actionable = 0
    latencies = []
    for row in rows:
        pred, gold = row.get("route", "error"), row["gold"]["route"]
        matrix[gold][pred] += 1
        tp += pred == gold == "execute"
        fp += pred == "execute" and gold != "execute"
        fn += pred != "execute" and gold == "execute"
        support_ok += row.get("support") == row["gold"]["support"]
        actionable = (
            gold == "execute"
            and row["gold"]["support"] == "supported"
            and row["stable"]
        )
        dispatch = (
            pred == "execute"
            and row.get("support") == "supported"
            and row["stable"]
        )
        non_actionable += not actionable
        false_dispatch += dispatch and not actionable
        if "latency_ms" in row:
            latencies.append(row["latency_ms"])
    return {
        "n": len(rows),
        "errors": sum("error" in r for r in rows),
        "confusion_matrix": matrix,
        "accuracy": sum(r.get("route") == r["gold"]["route"] for r in rows)
        / max(1, len(rows)),
        "execute_precision": tp / (tp + fp) if tp + fp else None,
        "execute_recall": tp / (tp + fn) if tp + fn else None,
        "false_execution_rate": false_dispatch / max(1, non_actionable),
        "support_accuracy": support_ok / max(1, len(rows)),
        "p50_latency_ms": statistics.median(latencies) if latencies else None,
        "max_latency_ms": max(latencies) if latencies else None,
        "cost_usd": None,
    }


async def run(args):
    """Run exactly one paired evaluation without automatic retries."""
    data = [json.loads(line) for line in args.dataset.read_text().splitlines()]
    samples = [row for row in data if row["split"] == args.split]
    config = RoutingConfig(
        variant=args.variant, execute_threshold=args.threshold
    )
    routers = {
        "jev": Router("jev", args.jev_key, config),
        "scaledown": Router("scaledown", args.scaledown_key, config),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise ValueError("refuse to overwrite an evaluation run")
    rows = []
    # At most one sample at a time, providers paired. No automatic paid retries.
    with args.output.open("w") as stream:
        for sample in samples:

            async def classify(provider, router, sample=sample):
                result = {
                    "id": sample["id"],
                    "family": sample["family"],
                    "split": sample["split"],
                    "kind": sample["kind"],
                    "provider": provider,
                    "variant": args.variant,
                    "gold": sample["gold"],
                    "stable": sample["input"]["stable"],
                }
                try:
                    result.update(await router.classify(sample))
                except (
                    Exception
                ) as exc:  # No body, URL or credentials in output.
                    result["error"] = type(exc).__name__
                return result

            pair = await asyncio.gather(
                *(classify(k, v) for k, v in routers.items())
            )
            for row in pair:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
                rows.append(row)
            print(
                json.dumps({"sample": sample["id"], "complete": len(rows)}),
                flush=True,
            )
    summary = {
        k: metrics([r for r in rows if r["provider"] == k]) for k in routers
    }
    summary["dataset_sha256"] = hashlib.sha256(
        args.dataset.read_bytes()
    ).hexdigest()
    summary["split"], summary["variant"] = args.split, args.variant
    args.output.with_suffix(".summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    print(json.dumps(summary))


def main():
    """Parse bounded evaluation CLI arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument(
        "--split", choices=("dev", "locked-test"), required=True
    )
    parser.add_argument(
        "--variant", choices=("baseline", "refined"), required=True
    )
    parser.add_argument("--threshold", type=float, default=0.65)
    parser.add_argument("--jev-key", type=Path, required=True)
    parser.add_argument("--scaledown-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
