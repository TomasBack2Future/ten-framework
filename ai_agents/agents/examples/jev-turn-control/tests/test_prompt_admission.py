"""Configuration compatibility for the evaluated prompt (not model accuracy)."""

from test_engine import Config


def test_evaluated_prompt_loads_and_overrides_remain_bounded():
    import pytest

    config = Config.load()
    assert 2000 < len(config["start"]["prompt"]) <= 4096
    assert config["start"]["threshold"] == 0.47
    assert config["start"]["score_mode"] == "answer_plus_clarify"
    with pytest.raises(ValueError, match="prompt exceeds"):
        Config.load({"start": {"prompt": "x" * 4097}})


def test_reply_mass_recovers_borderline_answer_without_overriding_hold():
    from test_engine import TurnEngine

    scores = {
        "answer": 0.43,
        "clarify": 0.12,
        "ignore": 0.24,
        "continuation": 0.20,
        "explicit_wait": 0.01,
    }
    for label, should_start in [("answer", True), ("continuation", False)]:
        engine = TurnEngine(Config.load())
        engine.input("Why are you stopping?", True, 0, "question")
        request = engine.begin_decision(120)
        engine.complete_decision(
            request,
            {
                "start": {
                    "label": label,
                    "score": scores[label],
                    "probabilities": scores,
                }
            },
            200,
        )
        engine.tick(451)
        assert bool(engine.active) == should_start
