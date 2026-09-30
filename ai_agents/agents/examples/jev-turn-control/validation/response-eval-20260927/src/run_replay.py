"""Run locked ablations and independently labelled silence counterfactuals."""

import json
import subprocess
from pathlib import Path
from collect import ROOT, KUBE, POD


def main():
    sequences = [
        json.loads(line)
        for line in (ROOT / "data/new-sequences.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    choices = json.loads(
        (ROOT / "manifests/selection-lock.json").read_text(encoding="utf-8")
    )["selections"]
    specs = []
    for seq in sequences:
        for provider in ("jev", "scaledown"):
            for engine in ("base", "fixed"):
                for arm, prompt, threshold in [
                    ("A", "A", 0.47),
                    ("B", "B", 0.47),
                    ("C", "A", choices[provider]["A"]["locked_threshold"]),
                    ("D", "B", choices[provider]["B"]["locked_threshold"]),
                ]:
                    specs.append(
                        {
                            "sequence": seq,
                            "provider": provider,
                            "engine": engine,
                            "arm": arm,
                            "prompt": prompt,
                            "threshold": threshold,
                        }
                    )
            for interval in (300, 500, 1000, 2000):
                specs.append(
                    {
                        "sequence": seq,
                        "provider": provider,
                        "engine": "fixed",
                        "arm": "timing-" + str(interval),
                        "prompt": "A",
                        "threshold": 0.47,
                        "silence_recheck_ms": interval,
                    }
                )
    files = {}
    for name, directory in [
        ("base", "reference"),
        ("fixed", "reference-fixed"),
    ]:
        for path in (ROOT / directory).glob("*"):
            if path.is_file():
                files[name + "/" + path.name] = path.read_text(encoding="utf-8")
    payload = {
        "files": files,
        "specs": specs,
        "prompts": {
            p: json.loads(
                (ROOT / "manifests" / f"prompt-{p}.json").read_text(
                    encoding="utf-8"
                )
            )
            for p in ("A", "B")
        },
        "keys": {
            "jev": Path("/tmp/b.pub").read_text(encoding="utf-8").strip(),
            "scaledown": Path("/tmp/c.pub").read_text(encoding="utf-8").strip(),
        },
    }
    bootstrap = 'import sys,json,types\npayload=json.load(sys.stdin)\nfor name in ("remote","replay"):\n m=types.ModuleType(name);sys.modules[name]=m;exec(payload["modules"][name],m.__dict__)\nsys.modules["replay"].main(payload)'
    payload["modules"] = {
        name: (ROOT / "src" / f"{name}.py").read_text(encoding="utf-8")
        for name in ("remote", "replay")
    }
    dest = ROOT / "results/sequence-network.jsonl"
    assert not dest.exists()
    with dest.open("w", encoding="utf-8") as out:
        process = subprocess.run(
            KUBE + ["exec", "-i", POD, "--", "python", "-c", bootstrap],
            input=json.dumps(payload).encode(),
            stdout=out,
            stderr=subprocess.PIPE,
            check=False,
        )
    print(
        json.dumps(
            {
                "exit_code": process.returncode,
                "specs": len(specs),
                "rows": sum(1 for _ in dest.open(encoding="utf-8")),
            }
        ),
        flush=True,
    )
    if process.returncode:
        message = process.stderr.decode(errors="replace")
        for key in payload["keys"].values():
            message = message.replace(key, "[REDACTED]")
        (ROOT / "results/sequence-stderr.txt").write_text(message)
        raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
