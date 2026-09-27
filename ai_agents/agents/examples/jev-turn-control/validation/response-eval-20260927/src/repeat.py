"""Repeat critical paired disagreements without changing frozen decisions."""

import hashlib
import json
import subprocess
from pathlib import Path
from analyze import load, gate
from collect import ROOT, KUBE, POD


def main():
    calls, pairs = load()
    jobs = {
        j["id"]: j
        for j in map(
            json.loads,
            (ROOT / "data/snapshots.jsonl")
            .read_text(encoding="utf-8")
            .splitlines(),
        )
    }
    critical = []
    for pair in pairs:
        j = pair["job"]
        if j["kind"] != "start" or j["checkpoint"] != "primary":
            continue
        a, b = (calls[pair["refs"][p]] for p in ("jev", "scaledown"))
        if a["error"] or b["error"]:
            continue
        aa, bb = (r["response"]["answers"]["start"] for r in (a, b))
        score = aa["probabilities"][aa["choice"]]
        if (
            aa["choice"] != bb["choice"]
            or gate(a, "start", 0.47) != gate(b, "start", 0.47)
            or abs(score - 0.47) <= 0.05
        ):
            critical.append(jobs[j["id"]])
    chosen = []
    for split in ("development", "validation", "holdout"):
        chosen.extend(
            sorted(
                [j for j in critical if j["split"] == split],
                key=lambda j: hashlib.sha256(j["id"].encode()).hexdigest(),
            )[:10]
        )
    frozen = {
        "selection": "provider choice/gate disagreement OR Jev chosen-score within .05 of .47; deterministic SHA order, at most 10 per split",
        "eligible": len(critical),
        "selected": [j["id"] for j in chosen],
        "repeats": 3,
    }
    (ROOT / "manifests/repetitions.json").write_text(
        json.dumps(frozen, indent=2)
    )
    payload = {
        "jobs": [
            dict(j, id=j["id"] + "/repeat-" + str(r), repeat=r)
            for j in chosen
            for r in (1, 2, 3)
        ],
        "keys": {
            "jev": Path("/tmp/b.pub").read_text(encoding="utf-8").strip(),
            "scaledown": Path("/tmp/c.pub").read_text(encoding="utf-8").strip(),
        },
    }
    dest = ROOT / "results/repetitions-network.jsonl"
    assert not dest.exists()
    with dest.open("w", encoding="utf-8") as out:
        proc = subprocess.run(
            KUBE
            + [
                "exec",
                "-i",
                POD,
                "--",
                "python",
                "-c",
                (ROOT / "src/remote.py").read_text(encoding="utf-8"),
            ],
            input=json.dumps(payload).encode(),
            stdout=out,
            stderr=subprocess.PIPE,
            check=False,
        )
    print(
        json.dumps(
            {
                "selected": len(chosen),
                "calls_expected": 6 * len(chosen),
                "exit": proc.returncode,
                "stderr_bytes": len(proc.stderr),
            }
        )
    )
    if proc.returncode:
        raise SystemExit(proc.returncode)


if __name__ == "__main__":
    main()
