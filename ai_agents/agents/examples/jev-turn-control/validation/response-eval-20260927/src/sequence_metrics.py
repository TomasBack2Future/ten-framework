"""Controller metrics with family denominators and paired bootstrap intervals."""

import json
import random
from collections import defaultdict
from analyze import ROOT, wilson


def percentile(values, q):
    return sorted(values)[int((len(values) - 1) * q)] if values else None


def summarize(rows):
    positive = [r for r in rows if r["opportunity_ms"] is not None]
    negative = [r for r in rows if r["opportunity_ms"] is None]
    responded = [r for r in positive if not r["missed"]]
    delays = [r["delay_ms"] for r in responded]
    false_starts = sum(bool(r["early_starts"]) for r in rows)
    return {
        "n": len(rows),
        "families": len({r["family"] for r in rows}),
        "positive_n": len(positive),
        "negative_n": len(negative),
        "misses": sum(r["missed"] for r in positive),
        "response_recall": len(responded) / len(positive) if positive else None,
        "recall_wilson95": wilson(len(responded), len(positive)),
        "sequences_with_early_start": false_starts,
        "early_start_wilson95": wilson(false_starts, len(rows)),
        "negative_false_response": sum(bool(r["starts"]) for r in negative),
        "negative_false_response_wilson95": wilson(
            sum(bool(r["starts"]) for r in negative), len(negative)
        ),
        "delay_p50_ms": percentile(delays, 0.5),
        "delay_p95_ms": percentile(delays, 0.95),
        "delay_censored": len(positive) - len(responded),
        "response_after_2s": sum(v > 2000 for v in delays),
        "clarify_starts": sum(
            s["mode"] == "clarify" for r in rows for s in r["starts"]
        ),
        "answer_starts": sum(
            s["mode"] == "answer" for r in rows for s in r["starts"]
        ),
        "requests": sum(len(r["requests"]) for r in rows),
        "provider_failures": sum(r["provider_failures"] for r in rows),
        "stale": sum(r["stale"] for r in rows),
        "cancelled": sum(
            e["type"] == "response.cancelled" for r in rows for e in r["events"]
        ),
    }


def paired(base, candidate):
    by_id = {r["id"]: r for r in candidate}
    values = defaultdict(list)
    for a in base:
        b = by_id[a["id"]]
        values[a["family"]].append(
            {
                "miss_delta": int(b["missed"]) - int(a["missed"]),
                "early_delta": int(bool(b["early_starts"]))
                - int(bool(a["early_starts"])),
                "delay_delta_ms": (
                    b["delay_ms"] - a["delay_ms"]
                    if a["delay_ms"] is not None and b["delay_ms"] is not None
                    else None
                ),
            }
        )
    result = {}
    rng = random.Random(20260927)
    families = list(values.values())
    for metric in ("miss_delta", "early_delta", "delay_delta_ms"):
        observed = [
            v[metric]
            for group in families
            for v in group
            if v[metric] is not None
        ]
        samples = []
        for _ in range(2000):
            vals = [
                v[metric]
                for group in rng.choices(families, k=len(families))
                for v in group
                if v[metric] is not None
            ]
            if vals:
                samples.append(sum(vals) / len(vals))
        result[metric] = {
            "mean": sum(observed) / len(observed) if observed else None,
            "paired_n": len(observed),
            "bootstrap95": [
                percentile(samples, 0.025),
                percentile(samples, 0.975),
            ],
        }
    result["families"] = len(families)
    return result


def main():
    rows = [
        r
        for r in map(
            json.loads,
            (ROOT / "results/sequence-network.jsonl")
            .read_text(encoding="utf-8")
            .splitlines(),
        )
        if r["record_type"] == "sequence"
    ]
    assert len(rows) == 2592, f"incomplete {len(rows)}"
    keys = {(r["id"], r["engine"], r["provider"], r["arm"]) for r in rows}
    assert len(keys) == len(rows)
    result = {"groups": {}, "paired": {}}
    groups = defaultdict(list)
    for row in rows:
        for source in ("all", row["source_type"]):
            for scenario in ("all", row["scenario"]):
                key = "/".join(
                    (
                        row["engine"],
                        row["provider"],
                        row["arm"],
                        row["split"],
                        source,
                        scenario,
                    )
                )
                groups[key].append(row)
    result["groups"] = {k: summarize(v) for k, v in groups.items()}
    for provider in ("jev", "scaledown"):
        for split in ("validation", "holdout"):
            base = [
                r
                for r in rows
                if r["engine"] == "base"
                and r["provider"] == provider
                and r["arm"] == "A"
                and r["split"] == split
            ]
            fixed = [
                r
                for r in rows
                if r["engine"] == "fixed"
                and r["provider"] == provider
                and r["arm"] == "A"
                and r["split"] == split
            ]
            result["paired"][f"{provider}/{split}/fixed-A-minus-base-A"] = (
                paired(base, fixed)
            )
            for arm in (
                "B",
                "C",
                "D",
                "timing-300",
                "timing-500",
                "timing-1000",
                "timing-2000",
            ):
                candidate = [
                    r
                    for r in rows
                    if r["engine"] == "fixed"
                    and r["provider"] == provider
                    and r["arm"] == arm
                    and r["split"] == split
                ]
                result["paired"][f"{provider}/{split}/{arm}-minus-fixed-A"] = (
                    paired(fixed, candidate)
                )
    (ROOT / "results/sequence-metrics.json").write_text(
        json.dumps(result, indent=2)
    )
    for key, value in result["groups"].items():
        if key.startswith("fixed/jev/") and "/holdout/all/all" in key:
            print(key, json.dumps(value))


if __name__ == "__main__":
    main()
