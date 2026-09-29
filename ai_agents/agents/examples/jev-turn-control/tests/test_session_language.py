"""Session language controls both the spoken voice and the LLM request."""

import importlib
import importlib.util
from pathlib import Path

import pytest

from test_engine import Config, PACKAGE

memory = importlib.import_module(f"{PACKAGE}.memory")
APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "jev_session_graph", APP / "scripts/run_graph.py"
)
graph_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(graph_module)


def node_property(graph, name):
    nodes = graph["ten"]["predefined_graphs"][0]["graph"]["nodes"]
    return next(node["property"] for node in nodes if node["name"] == name)


@pytest.mark.parametrize(
    ("language", "voice_id"),
    [
        ("ja", "861213b7-f057-45c8-9527-0f4c144f1a03"),
        ("ko", "90dba946-774b-40ed-98d9-ac3835117827"),
    ],
)
def test_english_keeps_existing_voice_and_other_languages_select_their_own(
    language, voice_id
):
    english = graph_module.graph_for("live", {})
    selected = graph_module.graph_for("live", {"voice.language": language})
    assert node_property(english, "tts")["params"]["language"] == "en"
    assert node_property(english, "tts")["params"]["voice"]["id"].startswith(
        "${env:CARTESIA_VOICE_ID|"
    )
    assert node_property(selected, "tts")["params"] == {
        **node_property(english, "tts")["params"],
        "voice": {"mode": "id", "id": voice_id},
        "language": language,
    }
    assert node_property(selected, "turn_control")["voice"]["language"] == language
    assert node_property(selected, "stt") == node_property(english, "stt")


def test_unsupported_language_is_rejected_in_graph_and_controller():
    for language in ("fr", "", 42):
        with pytest.raises(ValueError, match="voice language"):
            graph_module.graph_for("live", {"voice.language": language})
        with pytest.raises(ValueError, match="voice.language|voice language"):
            Config.load({"voice": {"language": language}})


def test_selected_language_reaches_voice_prompt_even_with_override():
    action = {
        "response_id": "reply-1",
        "mode": "answer",
        "input_text": "Tell me more",
        "context": [],
    }
    japanese = Config.load({"voice": {"language": "ja", "prompt": "Be brief."}})
    japanese_request = memory.voice_request(action, japanese)
    assert "Be brief." in japanese_request["prompt"]
    assert "Session response language: Japanese" in japanese_request["prompt"]
    assert "regardless of the input language" in japanese_request["prompt"]
    korean = Config.load({"voice": {"language": "ko", "prompt": "Be brief."}})
    assert "Session response language: Korean" in memory.voice_request(
        action, korean
    )["prompt"]
    english_request = memory.voice_request(action, Config.load())
    assert "Session response language: English" in english_request["prompt"]


def test_backchannel_uses_selected_language():
    assert Config.load()["backchannel"]["phrases"] == ["Mm-hmm.", "I see."]
    assert Config.load({"voice": {"language": "ja"}})["backchannel"]["phrases"] == [
        "うん。",
        "なるほど。",
    ]
    assert Config.load({"voice": {"language": "ko"}})["backchannel"]["phrases"] == [
        "네.",
        "그렇군요.",
    ]
