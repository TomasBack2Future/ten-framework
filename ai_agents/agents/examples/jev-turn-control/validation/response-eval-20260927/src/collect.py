"""Execute a frozen batch in a non-serving khipaa Pod; no keys in artifacts."""

import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KUBE = [
    "kubectl",
    "--kubeconfig",
    os.environ.get("KUBECONFIG", str(Path.home() / "k8s/hipaa.kubeconfig")),
    "-n",
    "ten-jev-demo",
]
POD = "jev-response-eval-20260927"


def run(stage):
    jobs = [
        json.loads(line)
        for line in (ROOT / "data/snapshots.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    if stage == "holdout":
        assert (
            ROOT / "manifests/selection-lock.json"
        ).exists(), "selection must be locked first"
    jobs = [
        j for j in jobs if (j["split"] == "holdout") == (stage == "holdout")
    ]
    destination = ROOT / "results" / (stage + "-network.jsonl")
    assert not destination.exists(), "refuse to overwrite raw evidence"
    payload = {
        "jobs": jobs,
        "keys": {
            "jev": Path("/tmp/b.pub").read_text(encoding="utf-8").strip(),
            "scaledown": Path("/tmp/c.pub").read_text(encoding="utf-8").strip(),
        },
    }
    code = (ROOT / "src/remote.py").read_text(encoding="utf-8")
    with destination.open("w", encoding="utf-8") as out:
        process = subprocess.run(
            KUBE + ["exec", "-i", POD, "--", "python", "-c", code],
            input=json.dumps(payload).encode(),
            stdout=out,
            stderr=subprocess.PIPE,
            check=False,
        )
    print(
        json.dumps(
            {
                "stage": stage,
                "exit_code": process.returncode,
                "rows": sum(1 for _ in destination.open(encoding="utf-8")),
                "stderr_bytes": len(process.stderr),
            }
        ),
        flush=True,
    )
    if process.returncode:
        # kubectl diagnostics do not include input credentials, still redact.
        message = process.stderr.decode(errors="replace")
        for secret in payload["keys"].values():
            message = message.replace(secret, "[REDACTED]")
        (ROOT / "results" / (stage + "-stderr.txt")).write_text(message)
        raise SystemExit(process.returncode)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["development-validation", "holdout"])
    run(parser.parse_args().stage)
