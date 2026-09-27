"""Seen control regression; reconstructed inputs are NOT historic full requests."""

import json
from pathlib import Path
from replay import engine_class

ROOT = Path(__file__).resolve().parents[1]


def case(engine_name, threshold=0.47):
    Engine, Config = engine_class(
        ROOT / ("reference" if engine_name == "base" else "reference-fixed"),
        "seen_" + engine_name + str(threshold).replace(".", "_"),
    )
    engine = Engine(
        Config.load(
            {
                "start": {"threshold": threshold},
                "observation": {"include_text": True},
            }
        )
    )
    engine.input("One. Three. Four.", True, 171587, "asr-count")
    request = engine.begin_decision(171710)
    engine.complete_decision(
        request,
        {
            "start": {
                "label": "continuation",
                "score": 0.45,
                "probabilities": {
                    "continuation": 0.45,
                    "ignore": 0.36,
                    "answer": 0.1,
                    "clarify": 0.07,
                    "explicit_wait": 0.02,
                },
            }
        },
        171798,
    )
    engine.tick(176605)
    assert engine.active and engine.guidance_sent
    prior = engine.active
    engine.now = 177620
    engine.stop("user_reclaims_floor")
    engine.playback(prior, 0, 177896, stopped=True)
    engine.input("How many digits are there?", True, 178254, "asr-question")
    request = engine.begin_decision(178380)
    answer = {
        "label": "answer",
        "score": 0.42,
        "probabilities": {
            "answer": 0.42,
            "continuation": 0.43,
            "clarify": 0.12,
            "ignore": 0.02,
            "explicit_wait": 0.01,
        },
    }
    engine.complete_decision(request, {"start": answer}, 178502)
    engine.drain_actions()
    starts = []
    for now in range(178504, 184001, 10):
        engine.tick(now)
        starts.extend(
            {"at_ms": now, "mode": a["mode"]}
            for a in engine.drain_actions()
            if a["type"] == "response.start"
        )
    return {
        "engine": engine_name,
        "threshold": threshold,
        "supplied_observed_score": answer,
        "starts": starts,
        "pending_at_end": engine.pending,
        "guidance_sent_at_end": engine.guidance_sent,
        "model_request_reconstruction": request,
        "new_provider_call": False,
    }


def main():
    rows = [case(e, t) for e in ("base", "fixed") for t in (0.47, 0.42)]
    assert not rows[0]["starts"]
    assert rows[2]["starts"][0]["mode"] == "clarify"
    assert rows[1]["starts"][0]["mode"] == "answer"
    result = {
        "provenance": "SEEN regression. Count prefix and complete request context reconstructed; visible question/selected label .42 and relevant times from prior investigation. Not an exact captured historic HTTP body. No claim that a new prompt fixed historical model semantics.",
        "rows": rows,
    }
    (ROOT / "results/seen-regression.json").write_text(
        json.dumps(result, indent=2)
    )
    print(
        json.dumps(
            [{k: r[k] for k in ("engine", "threshold", "starts")} for r in rows]
        )
    )


if __name__ == "__main__":
    main()
