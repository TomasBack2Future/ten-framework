"""Request accounting and within-request variability from retained raw evidence."""

import json
from collections import defaultdict
from analyze import ROOT, load, gate
from sequence_metrics import percentile


def main():
    calls, _ = load()
    result = {"network": {}, "repeatability": {}, "raw_files": {}}
    for provider in ("jev", "scaledown"):
        rows = [r for r in calls.values() if r["provider"] == provider]
        latency = [r["latency_ms"] for r in rows if not r["error"]]
        result["network"][provider] = {
            "http_calls": len(rows),
            "http_or_validation_errors": sum(bool(r["error"]) for r in rows),
            "over_800ms": sum(r["runtime_timeout_800ms"] for r in rows),
            "p50_ms": percentile(latency, 0.5),
            "p95_ms": percentile(latency, 0.95),
            "returned_models": sorted({str(r["resolved_model"]) for r in rows}),
        }
        repeats = defaultdict(list)
        repeated_hashes = {r["request_hash"] for r in rows if r["repeat"]}
        for row in rows:
            if row["request_hash"] in repeated_hashes:
                repeats[row["request_hash"]].append(row)
        details = []
        for request_hash, group in repeats.items():
            valid = [r for r in group if not r["error"]]
            choices = {
                r["response"]["answers"]["start"]["choice"] for r in valid
            }
            gates = {gate(r, "start", 0.47) for r in group}
            details.append(
                {
                    "request_hash": request_hash,
                    "n": len(group),
                    "label_changed": len(choices) > 1,
                    "gate_changed_at_047": len(gates) > 1,
                    "choices": sorted(choices),
                }
            )
        result["repeatability"][provider] = {
            "request_groups": len(details),
            "calls_per_group": 4,
            "groups_with_label_change": sum(
                d["label_changed"] for d in details
            ),
            "groups_with_gate_change_at_047": sum(
                d["gate_changed_at_047"] for d in details
            ),
            "details": details,
        }
    for path in sorted((ROOT / "results").glob("*network.jsonl")):
        counts = defaultdict(int)
        for row in map(
            json.loads, path.read_text(encoding="utf-8").splitlines()
        ):
            counts[row["record_type"]] += 1
        result["raw_files"][path.name] = dict(counts)
    (ROOT / "results/measurement-summary.json").write_text(
        json.dumps(result, indent=2)
    )
    print(json.dumps({k: v for k, v in result.items() if k != "repeatability"}))
    print(
        json.dumps(
            {
                p: {k: v for k, v in d.items() if k != "details"}
                for p, d in result["repeatability"].items()
            }
        )
    )


if __name__ == "__main__":
    main()
