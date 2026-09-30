"""Re-run every controller trace from exact frozen HTTP bodies, without network."""

import json
from analyze import ROOT, load
from remote import canonical, digest
from replay import Replay, engine_class


class FrozenCollector:
    def __init__(self, calls):
        self.calls = calls
        self.lookups = 0

    def request(self, provider, state, questions, repeat=0):
        body = {
            "model": "jev-1.13.0" if provider == "jev" else "classify-1",
            "state": state if provider == "jev" else {"text": canonical(state)},
            "questions": questions,
        }
        request_hash = digest({"provider": provider, "body": body})
        key = digest({"request_hash": request_hash, "repeat": repeat})
        if key not in self.calls:
            raise AssertionError("Missing exact request body: " + request_hash)
        self.lookups += 1
        return self.calls[key]

    def emit(self, row):
        pass


def main():
    calls, _ = load()
    sequences = {
        s["id"]: s
        for s in map(
            json.loads,
            (ROOT / "data/new-sequences.jsonl")
            .read_text(encoding="utf-8")
            .splitlines(),
        )
    }
    collector = FrozenCollector(calls)
    sources = {
        name: engine_class(ROOT / directory, "offline_" + name)
        for name, directory in [
            ("base", "reference"),
            ("fixed", "reference-fixed"),
        ]
    }
    runner = Replay(
        collector,
        sources,
        {
            p: json.loads(
                (ROOT / "manifests" / f"prompt-{p}.json").read_text(
                    encoding="utf-8"
                )
            )
            for p in ("A", "B")
        },
    )
    total = 0
    for row in map(
        json.loads,
        (ROOT / "results/sequence-network.jsonl")
        .read_text(encoding="utf-8")
        .splitlines(),
    ):
        if row["record_type"] != "sequence":
            continue
        spec = {
            "sequence": sequences[row["id"]],
            "engine": row["engine"],
            "provider": row["provider"],
            "arm": row["arm"],
            "prompt": "B" if row["arm"] in ("B", "D") else "A",
            "threshold": row["threshold"],
            "silence_recheck_ms": row["silence_recheck_ms"],
        }
        actual = runner.run(spec)
        assert actual == row, (
            row["id"],
            row["engine"],
            row["provider"],
            row["arm"],
        )
        total += 1
    assert total == 2592
    result = {
        "sequences": total,
        "exact_body_cache_lookups": collector.lookups,
        "network_calls": 0,
        "all_events_and_results_identical": True,
    }
    (ROOT / "results/offline-verification.json").write_text(
        json.dumps(result, indent=2)
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
