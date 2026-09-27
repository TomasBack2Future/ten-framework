"""Paired latency and frozen-label accuracy; repetitions cluster by family."""

import hashlib
import gzip
import json
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARMS = ("jev", "sd", "sd_jev", "sd_reasoning_on")


def data_bytes(relative):
    path = ROOT / relative
    if path.exists():
        return path.read_bytes()
    return gzip.decompress(Path(str(path) + ".gz").read_bytes())


def quantile(values, q):
    if not values:
        return None
    values = sorted(values)
    return values[int((len(values) - 1) * q)]


def gate(answer, kind, profile):
    label = answer["choice"]
    p = answer["probabilities"]
    score = p[label]
    if kind == "start":
        if label not in ("answer", "clarify"):
            return False
        if profile[kind]["score_mode"] == "answer_plus_clarify":
            score = p["answer"] + p["clarify"]
        return score >= profile[kind]["threshold"]
    return label == "stop" and score >= profile[kind]["threshold"]


def grade(row, case, profiles):
    exact_n = len(case["gold"]) if case["gold_type"] == "exact_choice" else 0
    binary_n = len(case["gold"]) if case["gold_type"] == "floor_binary" else 0
    out = {
        "exact_correct": 0,
        "exact_n": exact_n,
        "binary_semantic_correct": 0,
        "binary_gate_correct": 0,
        "binary_deadline_correct": 0,
        "binary_n": binary_n,
        "false_positive": 0,
        "false_negative": 0,
        "positive_n": (
            sum(bool(v) for v in case["gold"].values()) if binary_n else 0
        ),
        "negative_n": (
            sum(not v for v in case["gold"].values()) if binary_n else 0
        ),
    }
    if row["error"]:
        return out
    profile = profiles["jev" if row["lane"] == "controlled" else row["arm"]]
    for kind, gold in case["gold"].items():
        answer = row["answers"][kind]
        if exact_n:
            out["exact_correct"] += answer["choice"] == gold
        else:
            semantic = (
                answer["choice"] in ("answer", "clarify")
                if kind == "start"
                else answer["choice"] == "stop"
            )
            pred = gate(answer, kind, profile)
            correct = pred == gold
            out["binary_semantic_correct"] += semantic == gold
            out["binary_gate_correct"] += correct
            out["binary_deadline_correct"] += correct and not row["over_800ms"]
            out["false_positive"] += pred and not gold
            out["false_negative"] += not pred and gold
    return out


def summarize(rows, cases, profiles):
    grades = [grade(r, cases[r["case_id"]], profiles) for r in rows]
    sums = {k: sum(g[k] for g in grades) for k in grades[0]} if grades else {}
    for numerator, denominator in [
        ("exact_correct", "exact_n"),
        ("binary_semantic_correct", "binary_n"),
        ("binary_gate_correct", "binary_n"),
        ("binary_deadline_correct", "binary_n"),
    ]:
        sums[numerator + "_rate"] = (
            sums.get(numerator, 0) / sums[denominator]
            if sums.get(denominator)
            else None
        )
    latency = [r["latency_ms"] for r in rows]
    stage_latency = defaultdict(list)
    for r in rows:
        for s in r["stages"]:
            stage_latency[s["provider"]].append(s["latency_ms"])
    return {
        "trials": len(rows),
        "unique_cases": len({r["case_id"] for r in rows}),
        "families": len({r["family"] for r in rows}),
        "errors": sum(bool(r["error"]) for r in rows),
        "over_800ms": sum(r["over_800ms"] for r in rows),
        "latency_ms": {
            f"p{int(q*100)}": quantile(latency, q)
            for q in (0.5, 0.9, 0.95, 0.99)
        },
        "stage_latency_ms": {
            k: {"p50": quantile(v, 0.5), "p95": quantile(v, 0.95)}
            for k, v in stage_latency.items()
        },
        **sums,
    }


def bootstrap(rows, cases, profiles, arm, reference):
    base = {r["job_id"]: r for r in rows if r["arm"] == reference}
    comp = {r["job_id"]: r for r in rows if r["arm"] == arm}
    grouped = defaultdict(list)
    for key, a in base.items():
        b = comp[key]
        ag, bg = (grade(r, cases[r["case_id"]], profiles) for r in (a, b))
        grouped[a["family"]].append(
            {
                "latency_delta": b["latency_ms"] - a["latency_ms"],
                "exact_delta": bg["exact_correct"] - ag["exact_correct"],
                "exact_n": ag["exact_n"],
                "binary_delta": bg["binary_deadline_correct"]
                - ag["binary_deadline_correct"],
                "binary_n": ag["binary_n"],
            }
        )
    groups = list(grouped.values())
    rng = random.Random(20260927)

    def reduce(selected):
        flat = [v for group in selected for v in group]
        exact_n = sum(v["exact_n"] for v in flat)
        binary_n = sum(v["binary_n"] for v in flat)
        return [
            sum(v["latency_delta"] for v in flat) / len(flat),
            sum(v["exact_delta"] for v in flat) / exact_n if exact_n else None,
            (
                sum(v["binary_delta"] for v in flat) / binary_n
                if binary_n
                else None
            ),
        ]

    observed = reduce(groups)
    samples = [reduce(rng.choices(groups, k=len(groups))) for _ in range(2000)]
    result = {
        "family_clusters": len(groups),
        "paired_trials": len(base),
        "reference": reference,
        "candidate": arm,
    }
    for index, name in enumerate(
        (
            "mean_latency_delta_ms",
            "exact_accuracy_delta",
            "deadline_floor_accuracy_delta",
        )
    ):
        values = [s[index] for s in samples if s[index] is not None]
        result[name] = {
            "estimate": observed[index],
            "family_bootstrap95": [
                quantile(values, 0.025),
                quantile(values, 0.975),
            ],
        }
    return result


def main():
    lock = json.loads(
        (ROOT / "manifests/lock.json").read_text(encoding="utf-8")
    )
    for relative, key in [
        ("data/cases.json", "data_sha256"),
        ("data/jobs.json", "jobs_sha256"),
        ("manifests/decision_profiles.json", "profiles_sha256"),
    ]:
        assert hashlib.sha256(data_bytes(relative)).hexdigest() == lock[key]
    cases = {r["id"]: r for r in json.loads(data_bytes("data/cases.json"))}
    profiles = json.loads(
        (ROOT / "manifests/decision_profiles.json").read_text(encoding="utf-8")
    )
    rows = [
        json.loads(line)
        for line in data_bytes("results/measurements.jsonl")
        .decode("utf-8")
        .splitlines()
    ]
    assert len(rows) == lock["arm_results"], f"incomplete: {len(rows)}"
    assert len({(r["job_id"], r["arm"]) for r in rows}) == len(rows)
    output = {
        "groups": {},
        "paired_bootstrap": {},
        "reasoning_control": {},
        "variability": {},
        "http_count": sum(len(r["stages"]) for r in rows),
    }
    groups = defaultdict(list)
    for row in rows:
        for source in ("all", row["cohort"]):
            key = "/".join((row["lane"], row["regime"], row["arm"], source))
            groups[key].append(row)
    output["groups"] = {
        k: summarize(v, cases, profiles) for k, v in groups.items()
    }
    # Per-kind labels, keeping a multi-question request's latency as request latency.
    output["per_kind"] = {}
    for arm in ARMS:
        for kind in (
            "start",
            "stop",
            "backchannel",
            "compression",
            "route",
            "support",
        ):
            selected = [
                r
                for r in rows
                if r["lane"] == "controlled"
                and r["regime"] == "warm"
                and r["arm"] == arm
                and cases[r["case_id"]]["gold_type"] == "exact_choice"
                and kind in cases[r["case_id"]]["gold"]
            ]
            correct = sum(
                not r["error"]
                and r["answers"][kind]["choice"]
                == cases[r["case_id"]]["gold"][kind]
                for r in selected
            )
            output["per_kind"][arm + "/" + kind] = {
                "correct": correct,
                "trials": len(selected),
                "unique_cases": len({r["case_id"] for r in selected}),
                "accuracy": correct / len(selected) if selected else None,
            }
    warm = [
        r for r in rows if r["lane"] == "controlled" and r["regime"] == "warm"
    ]
    for arm, ref in [
        ("sd", "jev"),
        ("sd_jev", "jev"),
        ("sd", "sd_reasoning_on"),
    ]:
        output["paired_bootstrap"][arm + "-minus-" + ref] = bootstrap(
            warm, cases, profiles, arm, ref
        )
    off = {r["job_id"]: r for r in warm if r["arm"] == "sd"}
    on = {r["job_id"]: r for r in warm if r["arm"] == "sd_reasoning_on"}
    output["reasoning_control"] = {
        "paired_trials": len(off),
        "equal_answer_objects": sum(
            off[k].get("answers") == on[k].get("answers") for k in off
        ),
        "reasoning_fields_off": sum(
            bool(s.get("reasoning_fields"))
            for r in off.values()
            for s in r["stages"]
        ),
        "reasoning_fields_on": sum(
            bool(s.get("reasoning_fields"))
            for r in on.values()
            for s in r["stages"]
        ),
        "output_token_pairs_equal": sum(
            off[k]["stages"][-1]
            .get("response", {})
            .get("usage", {})
            .get("output_tokens")
            == on[k]["stages"][-1]
            .get("response", {})
            .get("usage", {})
            .get("output_tokens")
            for k in off
        ),
    }
    for arm in ARMS:
        by_case = defaultdict(list)
        for row in warm:
            if row["arm"] == arm:
                by_case[row["case_id"]].append(row)
        changed = 0
        for group in by_case.values():
            labels = {
                tuple(
                    (k, a["choice"])
                    for k, a in sorted(r.get("answers", {}).items())
                )
                for r in group
            }
            changed += len(labels) > 1
        output["variability"][arm] = {
            "cases": len(by_case),
            "choice_changed_across_three_repeats": changed,
        }
    (ROOT / "results/metrics.json").write_text(json.dumps(output, indent=2))
    for key, value in output["groups"].items():
        if key.endswith("/all"):
            print(key, json.dumps(value))
    print("reasoning_control", json.dumps(output["reasoning_control"]))


if __name__ == "__main__":
    main()
