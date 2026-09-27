"""Send credentials only via exec stdin to an isolated non-serving Pod."""

import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POD = "jev-sd-reasoning-20260927"
KUBE = [
    "kubectl",
    "--kubeconfig",
    os.environ.get("KUBECONFIG", str(Path.home() / "k8s/hipaa.kubeconfig")),
    "-n",
    "ten-jev-demo",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    jobs = json.loads((ROOT / "data/jobs.json").read_text(encoding="utf-8"))
    if args.pilot:
        jobs = [jobs[0]]
    payload = {
        "jobs": jobs,
        "questions": json.loads(
            (ROOT / "manifests/questions.json").read_text(encoding="utf-8")
        ),
        "keys": {
            "jev": Path("/tmp/b.pub").read_text(encoding="utf-8").strip(),
            "sd": Path("/tmp/c.pub").read_text(encoding="utf-8").strip(),
        },
        "concurrency": 1 if args.pilot else 2,
    }
    destination = (
        ROOT
        / "results"
        / ("pilot.jsonl" if args.pilot else "measurements.jsonl")
    )
    assert not (args.pilot and args.resume), "pilot cannot resume main"
    if args.resume:
        assert destination.exists(), "no captured stream to resume"
        saved = {
            (r["job_id"], r["arm"])
            for r in map(
                json.loads, destination.read_text(encoding="utf-8").splitlines()
            )
        }
        outstanding = []
        for job in payload["jobs"]:
            arms = [a for a in job["arms"] if (job["id"], a) not in saved]
            if arms:
                outstanding.append(
                    dict(job, arms=arms, collection_epoch="resume")
                )
        payload["jobs"] = outstanding
    else:
        assert not destination.exists(), "refuse to overwrite raw results"
    with destination.open("a" if args.resume else "w", encoding="utf-8") as out:
        result = subprocess.run(
            KUBE
            + [
                "exec",
                "-i",
                POD,
                "--",
                "python",
                "-c",
                (ROOT / "src/probe.py").read_text(encoding="utf-8"),
            ],
            input=json.dumps(payload).encode(),
            stdout=out,
            stderr=subprocess.PIPE,
            check=False,
        )
    print(
        json.dumps(
            {
                "stage": "pilot" if args.pilot else "main",
                "exit": result.returncode,
                "rows": sum(1 for _ in destination.open(encoding="utf-8")),
            }
        ),
        flush=True,
    )
    if result.returncode:
        message = result.stderr.decode(errors="replace")
        for key in payload["keys"].values():
            message = message.replace(key, "[REDACTED]")
        (ROOT / "results/runner-error.txt").write_text(message)
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
