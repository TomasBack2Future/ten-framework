"""Restore immutable engine sources and expand checked-in measurement evidence."""

import argparse
import gzip
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    evidence_lock = ROOT / "manifests/artifact-hashes.json"
    if evidence_lock.exists():
        for relative, expected in json.loads(
            evidence_lock.read_text(encoding="utf-8")
        ).items():
            assert (
                hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
                == expected
            ), relative
    lock = json.loads(
        (ROOT / "manifests/engine-lock.json").read_text(encoding="utf-8")
    )
    for dirname, revision in [
        ("reference", lock["base_sha"]),
        ("reference-fixed", lock["fixed_sha"]),
    ]:
        destination = ROOT / dirname
        destination.mkdir(exist_ok=True)
        for rel, expected in lock["sha256"].items():
            if not rel.startswith(dirname + "/"):
                continue
            filename = Path(rel).name
            blob = subprocess.check_output(
                [
                    "git",
                    "show",
                    revision + ":" + lock["source_path"] + "/" + filename,
                ],
                cwd=args.repo,
            )
            assert hashlib.sha256(blob).hexdigest() == expected
            (destination / filename).write_bytes(blob)
    for path in (ROOT / "results").glob("*.gz"):
        dest = path.with_suffix("")
        blob = gzip.decompress(path.read_bytes())
        if dest.exists():
            assert dest.read_bytes() == blob
        else:
            dest.write_bytes(blob)
    data = ROOT / "data/new-sequences.jsonl"
    assert (
        hashlib.sha256(data.read_bytes()).hexdigest()
        == json.loads(
            (ROOT / "manifests/data-freeze.json").read_text(encoding="utf-8")
        )["dataset_sha256"]
    )
    # Regenerate derived checkpoints from frozen sequences; no provider calls.
    from snapshots import build

    build()
    print("Immutable engines, dataset and evidence prepared; no network calls.")


if __name__ == "__main__":
    main()
