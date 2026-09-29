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


def test_english_keeps_existing_voice_and_japanese_selects_its_own():
    english = graph_module.graph_for("live", {})
    japanese = graph_module.graph_for("live", {"voice.language": "ja"})
    assert node_property(english, "tts")["params"]["language"] == "en"
    assert node_property(english, "tts")["params"]["voice"]["id"].startswith(
        "${env:CARTESIA_VOICE_ID|"
    )
    assert node_property(japanese, "tts")["params"] == {
        **node_property(english, "tts")["params"],
        "voice": {"mode": "id", "id": "7ca2afba-a719-4f06-9af2-ea2b8e3cf14c"},
        "language": "ja",
    }
    assert node_property(japanese, "turn_control")["voice"]["language"] == "ja"
    assert node_property(japanese, "stt") == node_property(english, "stt")


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
    english_request = memory.voice_request(action, Config.load())
    assert "Session response language: English" in english_request["prompt"]


def test_backchannel_uses_selected_language():
    assert Config.load()["backchannel"]["phrases"] == ["Mm-hmm.", "I see."]
    assert Config.load({"voice": {"language": "ja"}})["backchannel"]["phrases"] == [
        "うん。",
        "なるほど。",
    ]
