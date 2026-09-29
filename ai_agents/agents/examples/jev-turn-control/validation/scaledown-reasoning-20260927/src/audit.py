"""Offline verification of paired coverage, wire flags and complete-chain timing."""

import json
from analyze import ROOT, data_bytes
from probe import canonical, digest


def main():
    jobs = {j["id"]: j for j in json.loads(data_bytes("data/jobs.json"))}
    questions = json.loads(data_bytes("manifests/questions.json"))
    rows = [
        json.loads(s)
        for s in data_bytes("results/measurements.jsonl").splitlines()
    ]
    expected = {(j["id"], arm) for j in jobs.values() for arm in j["arms"]}
    observed = {(r["job_id"], r["arm"]) for r in rows}
    assert len(rows) == len(observed) and observed == expected
    stages = 0
    for row in rows:
        job = jobs[row["job_id"]]
        state = job["case"]["state"]
        arm = row["arm"]
        profile = "jev" if job["lane"] == "controlled" else arm
        q = {k: questions[profile][k] for k in job["case"]["gold"]}
        assert row["questions_hash"] == digest(q)
        chain = row["stages"]
        stages += len(chain)
        if arm == "sd_jev":
            comp = chain[0]
            assert comp["provider"] == "compress"
            assert comp["request"] == {
                "context": canonical(state),
                "prompt": "Preserve every field, speaker attribution, negation, task status, user prefix, ASR flags and original size. Classify with these definitions: "
                + canonical(q),
                "scaledown": {"rate": "auto"},
            }
            response = comp["response"]
            text = response.get("compressed_prompt") or response.get(
                "results", {}
            ).get("compressed_prompt")
            state = {"compressed_state_text": text}
            assert len(chain) == 2
        else:
            assert len(chain) == 1
        if arm in ("sd", "sd_reasoning_on"):
            body = {
                "model": "classify-1",
                "reasoning": arm == "sd_reasoning_on",
                "state": {"text": canonical(state)},
                "questions": q,
            }
        else:
            body = {"model": "jev-1.13.0", "state": state, "questions": q}
        assert chain[-1]["request"] == body
        assert row["latency_ms"] + 1 >= sum(s["latency_ms"] for s in chain)
        for stage in chain:
            assert stage["request_hash"] == digest(
                {"provider": stage["provider"], "body": stage["request"]}
            )
            assert not stage["error"] and stage["status"] == 200
            assert json.loads(stage["response_raw"]) == stage["response"]
    result = {
        "paired_results": len(rows),
        "captured_http_stages": stages,
        "missing_or_duplicate_results": 0,
        "wire_bodies_and_reasoning_flags_verified": True,
        "full_chain_timing_verified": True,
        "network_calls": 0,
    }
    (ROOT / "results/audit.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
