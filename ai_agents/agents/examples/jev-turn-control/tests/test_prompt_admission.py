"""Configuration compatibility for the evaluated prompt (not model accuracy)."""

from test_engine import Config


def test_evaluated_prompt_loads_and_overrides_remain_bounded():
    import pytest

    config = Config.load()
    assert 2000 < len(config["start"]["prompt"]) <= 4096
    assert config["start"]["threshold"] == 0.47
    assert config["start"]["score_mode"] == "top"
    with pytest.raises(ValueError, match="prompt exceeds"):
        Config.load({"start": {"prompt": "x" * 4097}})
