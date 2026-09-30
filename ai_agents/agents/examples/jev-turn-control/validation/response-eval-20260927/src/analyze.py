"""Frozen-score ablations, development-only selection, uncertainty and reports."""

import argparse
import hashlib
import json
import math
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRID = [
    0.20,
    0.25,
    0.30,
    0.35,
    0.40,
    0.42,
    0.45,
    0.47,
    0.50,
    0.55,
    0.60,
    0.65,
    0.70,
    0.75,
    0.80,
    0.85,
    0.90,
    0.95,
]


def load():
    calls, pairs = {}, []
    for path in sorted((ROOT / "results").glob("*network.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["record_type"] == "http":
                calls[row["cache_key"]] = row
            elif row["record_type"] == "pair" and not row["job"].get(
                "repeat", 0
            ):
                pairs.append(row)
    return calls, pairs


def gate(call, kind, threshold):
    if call["error"] or call["runtime_timeout_800ms"]:
        return False
    answer = call["response"]["answers"][kind]
    label = answer["choice"]
    return (
        label in (("answer", "clarify") if kind == "start" else ("stop",))
        and answer["probabilities"][label] >= threshold
    )


def cost(rows, calls, provider, threshold):
    negative, misses, families = 0, 0, set()
    for row in rows:
        pred = gate(calls[row["refs"][provider]], "start", threshold)
        gold = row["job"]["gold_reply"]
        if pred and not gold:
            negative += 1
            families.add(row["job"]["family"])
        misses += int(gold and not pred)
    return (10 * negative + 2 * misses, len(families), abs(threshold - 0.47)), {
        "false_starts": negative,
        "misses": misses,
        "n": len(rows),
    }


def select():
    calls, pairs = load()
    selections = {}
    for provider in ("jev", "scaledown"):
        selections[provider] = {}
        for prompt in ("A", "B"):
            rows = [
                p
                for p in pairs
                if p["job"]["kind"] == "start"
                and p["job"]["checkpoint"] in ("primary", "prefix")
                and p["job"]["prompt"] == prompt
            ]
            dev = [r for r in rows if r["job"]["split"] == "development"]
            val = [r for r in rows if r["job"]["split"] == "validation"]
            assert dev and val
            candidate = min(
                GRID,
                key=lambda t, dev_rows=dev, current_provider=provider: cost(
                    dev_rows, calls, current_provider, t
                )[0],
            )
            candidate_cost, candidate_details = cost(
                val, calls, provider, candidate
            )
            baseline_cost, baseline_details = cost(val, calls, provider, 0.47)
            confirmed = (
                candidate_cost[0] <= baseline_cost[0]
                and candidate_details["false_starts"]
                <= baseline_details["false_starts"]
            )
            selections[provider][prompt] = {
                "development_candidate": candidate,
                "validation_confirmed": confirmed,
                "locked_threshold": candidate if confirmed else 0.47,
                "validation_candidate": candidate_details,
                "validation_baseline": baseline_details,
                "development_grid": {
                    str(t): cost(dev, calls, provider, t)[1] for t in GRID
                },
            }
    raw = ROOT / "results/development-validation-network.jsonl"
    result = {
        "data_sha256": json.loads(
            (ROOT / "manifests/data-freeze.json").read_text(encoding="utf-8")
        )["dataset_sha256"],
        "development_validation_raw_sha256": hashlib.sha256(
            raw.read_bytes()
        ).hexdigest(),
        "selections": selections,
        "score_mode": "chosen-label probability for BOTH providers, controlled comparison; not deployed SD answer+clarify policy",
        "selection_checkpoints": "primary final+120ms and all stable prefixes; final silence probes excluded",
        "validation_rule": "reject increased weighted loss OR false starts; rejected threshold remains .47; do not retune",
        "holdout_used": False,
    }
    path = ROOT / "manifests/selection-lock.json"
    assert not path.exists()
    path.write_text(json.dumps(result, indent=2))
    print(
        json.dumps(
            {
                p: {
                    k: {
                        "threshold": v["locked_threshold"],
                        "confirmed": v["validation_confirmed"],
                    }
                    for k, v in prompts.items()
                }
                for p, prompts in selections.items()
            }
        )
    )


def wilson(success, n):
    if not n:
        return None
    z = 1.95996398454
    center = (success / n + z * z / (2 * n)) / (1 + z * z / n)
    half = (
        z
        * math.sqrt(success / n * (1 - success / n) / n + z * z / (4 * n * n))
        / (1 + z * z / n)
    )
    return [round(center - half, 4), round(center + half, 4)]


def metrics(rows, calls, provider, threshold):
    npos = sum(r["job"]["gold_reply"] for r in rows)
    positive = sum(
        gate(calls[r["refs"][provider]], "start", threshold)
        and r["job"]["gold_reply"]
        for r in rows
    )
    negative = sum(
        gate(calls[r["refs"][provider]], "start", threshold)
        and not r["job"]["gold_reply"]
        for r in rows
    )
    return {
        "n": len(rows),
        "families": len({r["job"]["family"] for r in rows}),
        "positive_n": npos,
        "negative_n": len(rows) - npos,
        "misses": npos - positive,
        "false_starts": negative,
        "recall": positive / npos if npos else None,
        "recall_wilson95": wilson(positive, npos),
        "false_start_rate": (
            negative / (len(rows) - npos) if len(rows) > npos else None
        ),
        "false_start_wilson95": wilson(negative, len(rows) - npos),
        "errors": sum(bool(calls[r["refs"][provider]]["error"]) for r in rows),
        "over_800ms": sum(
            calls[r["refs"][provider]]["runtime_timeout_800ms"] for r in rows
        ),
    }


def report():
    calls, pairs = load()
    selections = json.loads(
        (ROOT / "manifests/selection-lock.json").read_text(encoding="utf-8")
    )["selections"]
    output = {
        "frozen_score": {},
        "stop": {},
        "latency": {},
        "paired_family_bootstrap": {},
    }
    for provider in ("jev", "scaledown"):
        for arm, prompt, t in [
            ("A", "A", 0.47),
            ("B", "B", 0.47),
            ("C", "A", selections[provider]["A"]["locked_threshold"]),
            ("D", "B", selections[provider]["B"]["locked_threshold"]),
        ]:
            for split in ("development", "validation", "holdout"):
                rows = [
                    r
                    for r in pairs
                    if r["job"]["kind"] == "start"
                    and r["job"]["prompt"] == prompt
                    and r["job"]["split"] == split
                ]
                for source in (
                    "all",
                    "authored_synthetic",
                    "public_reference_projection",
                ):
                    for scenario in ["all"] + sorted(
                        {r["job"]["scenario"] for r in rows}
                    ):
                        for checkpoint in ("primary", "prefix", "silence"):
                            chosen = [
                                r
                                for r in rows
                                if (
                                    source == "all"
                                    or r["job"]["source_type"] == source
                                )
                                and (
                                    scenario == "all"
                                    or r["job"]["scenario"] == scenario
                                )
                                and r["job"]["checkpoint"] == checkpoint
                            ]
                            if chosen:
                                output["frozen_score"][
                                    "/".join(
                                        (
                                            provider,
                                            arm,
                                            split,
                                            source,
                                            scenario,
                                            checkpoint,
                                        )
                                    )
                                ] = metrics(chosen, calls, provider, t)
        rows = [r for r in pairs if r["job"]["kind"] == "stop"]
        output["stop"][provider] = {
            split: {
                "n": len(rs),
                "wrong": sum(
                    gate(calls[r["refs"][provider]], "stop", 0.65)
                    != r["job"]["gold_stop"]
                    for r in rs
                ),
            }
            for split in ("development", "validation", "holdout")
            if (rs := [r for r in rows if r["job"]["split"] == split])
        }
        snapshot_keys = {key for pair in pairs for key in pair["refs"].values()}
        snapshot_calls = [calls[key] for key in snapshot_keys]
        successful = [
            r["latency_ms"]
            for r in snapshot_calls
            if r["provider"] == provider and not r["error"]
        ]
        successful.sort()
        output["latency"][provider] = {
            "unique_requests": sum(
                r["provider"] == provider for r in snapshot_calls
            ),
            "errors": sum(
                r["provider"] == provider and bool(r["error"])
                for r in snapshot_calls
            ),
            "p50_ms": successful[int((len(successful) - 1) * 0.5)],
            "p95_ms": successful[int((len(successful) - 1) * 0.95)],
            "over_800ms": sum(v > 800 for v in successful),
        }
        # Primary checkpoints: paired errors resampled by family, not by prefix.
        for arm, prompt, t in [
            ("B", "B", 0.47),
            ("C", "A", selections[provider]["A"]["locked_threshold"]),
            ("D", "B", selections[provider]["B"]["locked_threshold"]),
        ]:
            for split in ("validation", "holdout"):
                base = {
                    r["job"]["sequence_id"]: r
                    for r in pairs
                    if r["job"]["kind"] == "start"
                    and r["job"]["checkpoint"] == "primary"
                    and r["job"]["prompt"] == "A"
                    and r["job"]["split"] == split
                }
                cand = {
                    r["job"]["sequence_id"]: r
                    for r in pairs
                    if r["job"]["kind"] == "start"
                    and r["job"]["checkpoint"] == "primary"
                    and r["job"]["prompt"] == prompt
                    and r["job"]["split"] == split
                }
                groups = defaultdict(list)
                for seq, row in base.items():
                    gold = row["job"]["gold_reply"]
                    a = (
                        gate(calls[row["refs"][provider]], "start", 0.47)
                        != gold
                    )
                    b = (
                        gate(calls[cand[seq]["refs"][provider]], "start", t)
                        != gold
                    )
                    groups[row["job"]["family"]].append(int(b) - int(a))
                if not groups:
                    continue
                rng = random.Random(20260927)
                values = list(groups.values())
                samples = []
                for _ in range(2000):
                    selected = [
                        v
                        for group in rng.choices(values, k=len(values))
                        for v in group
                    ]
                    samples.append(sum(selected) / len(selected))
                samples.sort()
                output["paired_family_bootstrap"][
                    f"{provider}/{arm}-{split}-minus-A"
                ] = {
                    "error_rate_delta": sum(sum(v) for v in values)
                    / sum(map(len, values)),
                    "percentile95": [samples[49], samples[1949]],
                    "families": len(values),
                }
    (ROOT / "results/snapshot-metrics.json").write_text(
        json.dumps(output, indent=2)
    )
    for provider in ("jev", "scaledown"):
        for arm in ("A", "B", "C", "D"):
            key = f"{provider}/{arm}/holdout/all/all/primary"
            if key in output["frozen_score"]:
                print(key, json.dumps(output["frozen_score"][key]))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["select", "report"])
    args = p.parse_args()
    if args.action == "select":
        select()
    else:
        report()
