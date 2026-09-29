"""A partial decision must release the provider slot when final ASR arrives."""

import importlib
from unittest.mock import Mock

from test_engine import Config, PACKAGE, TurnEngine, answer

extension = importlib.import_module(f"{PACKAGE}.extension")


def test_new_final_retires_stale_partial_request():
    adapter = extension.JevTurnControlExtension("stale_decision")
    adapter.engine = TurnEngine(Config.load())
    adapter.now = lambda: 350
    adapter.engine.input("Can you", False, 0)
    request = adapter.engine.begin_decision(120)
    adapter.classification_task = Mock()
    adapter.classification_task.done.return_value = False

    adapter.engine.input("Can you tell me another one?", True, 350)
    adapter.retire_stale_decision()

    adapter.classification_task.cancel.assert_called_once()
    assert adapter.engine.inflight is None
    assert any(
        event["type"] == "decision.discarded"
        and event["payload"]["discard_reason"] == "input_revision"
        for event in adapter.engine.events
    )
    newer = adapter.engine.begin_decision(470)
    assert newer["revision"] > request["revision"]
    assert newer["state"]["asr_final"] is True
    adapter.engine.complete_decision(newer, {}, 1270, error=True)
    adapter.engine.tick(1519)
    assert not adapter.engine.active
    adapter.engine.tick(1520)
    assert adapter.engine.responses[adapter.engine.active]["mode"] == "answer"


def test_speaking_stop_request_is_not_cancelled_by_continued_asr():
    adapter = extension.JevTurnControlExtension("stop_decision")
    adapter.engine = TurnEngine(Config.load())
    adapter.now = lambda: 650
    adapter.engine.input("Please answer?", True, 0)
    start = adapter.engine.begin_decision(120)
    adapter.engine.complete_decision(start, {"start": answer()}, 200)
    adapter.engine.tick(450)
    assert adapter.engine.active
    adapter.engine.input("Stop", False, 500, "stop-segment")
    request = adapter.engine.begin_decision(620)
    adapter.classification_task = Mock()
    adapter.classification_task.done.return_value = False

    adapter.engine.input("Stop now", False, 650, "stop-segment")
    adapter.retire_stale_decision()

    adapter.classification_task.cancel.assert_not_called()
    assert adapter.engine.inflight["request_id"] == request["request_id"]
