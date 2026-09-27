"""Deterministic streaming/task lifecycle metrics, separate from voice acoustics."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import time

from .adapter import Executor, FakeBackend, Request
from .config import ExecutorConfig


async def evaluate():
    """Measure duplicates, cancellation, stale commits and speech independence."""
    with tempfile.TemporaryDirectory() as directory:
        backend = FakeBackend(delay=0.05)
        executor = Executor(
            backend, ExecutorConfig(enabled=True, work_dir=Path(directory))
        )
        request = Request("stream", "turn", 1, "Create index.html")
        assert executor.submit(replace(request, stable=False)) is None
        first = time.monotonic()
        task_id = executor.submit(request)
        await executor.events.get()
        feedback_ms = (time.monotonic() - first) * 1000
        for _ in range(20):
            assert executor.submit(request) == task_id
        executor.submit(
            replace(
                request,
                turn_id="speech-stop",
                text="别念了",
                route="conversation",
            )
        )
        await executor.records[task_id].runner
        speech_stop_preserved_task = (
            executor.records[task_id].status == "completed"
        )
        completion_ms = (time.monotonic() - first) * 1000
        duplicate_starts = backend.starts - 1
        next_id = executor.submit(replace(request, turn_id="cancel"))
        await asyncio.sleep(0.005)
        started = time.monotonic()
        await executor.cancel("stream", next_id)
        cancel_ms = (time.monotonic() - started) * 1000
        await asyncio.sleep(0.06)
        files = list(Path(directory).rglob("*.html"))
        await executor.close()
        return {
            "backend": "fake_fixture",
            "duplicate_executions": duplicate_starts,
            "cancel_latency_ms": cancel_ms,
            "stale_artifact_commits": len(files) - 1,
            "stop_speech_preserves_task": speech_stop_preserved_task,
            "first_feedback_ms": feedback_ms,
            "completion_ms": completion_ms,
            "audio_stop_latency_ms": None,
            "note": "Task metrics only; no TTS/audio timing claim",
        }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(asyncio.run(evaluate()), indent=2) + "\n")
