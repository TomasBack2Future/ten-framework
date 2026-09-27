"""Bounded paired provider evaluation. Never sends gold or source metadata."""

# pylint: disable=broad-exception-caught  # Sanitize provider boundary failures.

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import statistics

from .config import RoutingConfig
from .routing import Router, ROUTES, decision_spec, spec_sha256


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


def resolve_config(args):
    """Freeze all non-dev evaluations to a dataset and complete decision spec."""
    if args.split == "dev":
        return RoutingConfig(
            variant=args.variant or "baseline",
            execute_threshold=(
                args.threshold if args.threshold is not None else 0.65
            ),
            **(
                {"model": args.model}
                if getattr(args, "model", None) is not None
                else {}
            ),
        )
    if args.selection_lock is None:
        raise ValueError("non-dev evaluation requires --selection-lock")
    lock = json.loads(args.selection_lock.read_text())
    if lock.get("schema_version") != 2:
        raise ValueError(
            "legacy selection lock is audit-only; explicit v2 migration required"
        )
    digest = hashlib.sha256(args.dataset.read_bytes()).hexdigest()
    if digest != lock["dataset_sha256"]:
        raise ValueError("dataset does not match selection lock")
    if lock.get("evaluation_boundary") not in (
        "exposed-regression",
        "unseen-holdout",
    ):
        raise ValueError("selection lock must declare evaluation boundary")
    if (args.split == "locked-test") != (
        lock["evaluation_boundary"] == "unseen-holdout"
    ):
        raise ValueError("split does not match declared evaluation boundary")
    variant, threshold = lock["variant"], lock["execute_threshold"]
    if variant not in ("baseline", "refined") or not 0 <= threshold <= 1:
        raise ValueError("invalid locked configuration")
    if args.variant is not None and args.variant != variant:
        raise ValueError("variant conflicts with selection lock")
    if args.threshold is not None and args.threshold != threshold:
        raise ValueError("threshold conflicts with selection lock")
    config = RoutingConfig(
        variant=variant,
        execute_threshold=threshold,
        **(
            {"model": args.model}
            if getattr(args, "model", None) is not None
            else {}
        ),
    )
    expected = lock.get("decision_spec_sha256")
    if (
        spec_sha256(lock["decision_spec"]) != expected
        or spec_sha256(decision_spec(config)) != expected
    ):
        raise ValueError("decision spec does not match selection lock")
    return config


async def run(args):
    """Run exactly one paired evaluation without automatic retries."""
    data = [json.loads(line) for line in args.dataset.read_text().splitlines()]
    config = resolve_config(
        args
    )  # Validate before reading keys or making calls.
    samples = [
        row for row in data if args.split in ("regression", row["split"])
    ]
    if not samples:
        raise ValueError("evaluation selection is empty")
    if args.split.startswith("regression") and any(
        row.get("evaluation_boundary") != "exposed-regression"
        for row in samples
    ):
        raise ValueError("regression data must declare prior exposure")
    if args.split == "locked-test" and any(
        row.get("evaluation_boundary") != "unseen-holdout" for row in samples
    ):
        raise ValueError(
            "legacy/exposed samples cannot be called an unseen holdout"
        )
    spec = decision_spec(config)
    expected = (
        spec_sha256(spec)
        if args.split == "dev"
        else json.loads(args.selection_lock.read_text())["decision_spec_sha256"]
    )
    routers = {
        "jev": Router(
            "jev", args.jev_key, config, expected_spec_sha256=expected
        ),
        "scaledown": Router(
            "scaledown",
            args.scaledown_key,
            config,
            expected_spec_sha256=expected,
        ),
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
                    "decision_spec_schema_version": spec["schema_version"],
                    "decision_spec_sha256": expected,
                    "provider_model_selection": spec["providers"][provider][
                        "model_selection"
                    ],
                    "provider_compression": spec["providers"][provider][
                        "compression"
                    ],
                    "variant": config.variant,
                    "evaluation_boundary": sample.get(
                        "evaluation_boundary", "legacy-unverified"
                    ),
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
    summary["split"], summary["variant"] = args.split, config.variant
    summary["execute_threshold"] = config.execute_threshold
    summary["selection_lock_schema_version"] = 2
    summary["decision_spec"] = spec
    summary["decision_spec_sha256"] = expected
    summary["evaluation_boundary"] = (
        "exposed-regression"
        if args.split.startswith("regression")
        else "unseen-holdout" if args.split == "locked-test" else "dev"
    )
    args.output.with_suffix(".summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    print(json.dumps(summary))


def main():
    """Parse bounded evaluation CLI arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument(
        "--split",
        choices=("dev", "locked-test", "regression-test", "regression"),
        required=True,
    )
    parser.add_argument("--variant", choices=("baseline", "refined"))
    parser.add_argument("--threshold", type=float)
    parser.add_argument(
        "--model", help="Jev model override; must match non-dev decision spec"
    )
    parser.add_argument("--selection-lock", type=Path)
    parser.add_argument("--jev-key", type=Path, required=True)
    parser.add_argument("--scaledown-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
