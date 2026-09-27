"""Twelve deterministic artifact tasks with independent filesystem assertions."""

# pylint: disable=line-too-long  # Preserve explicit benchmark/prompt text.

import asyncio
import csv
import hashlib
import io
from html.parser import HTMLParser
import json
from pathlib import Path
import tempfile
import time

from .adapter import Executor, FakeBackend, Request
from .config import ExecutorConfig


def tasks():
    """Source inputs and private assertions are separate from model text."""
    rows = []
    for index, title in enumerate(("Welcome", "Jev Demo", "你好", "Voice Lab")):
        rows.append(
            {
                "id": f"html-{index}",
                "prompt": f"Create index.html with exactly one h1 containing {title}.",
                "kind": "html",
                "title": title,
            }
        )
    for index, values in enumerate(((2, 3), (10, -4), (0, 0), (13, 8, 5))):
        rows.append(
            {
                "id": f"csv-{index}",
                "prompt": f"Create summary.csv with header total and one row containing the sum of {list(values)}.",
                "kind": "csv",
                "values": values,
            }
        )
    for index, words in enumerate(
        (("red", "blue", "red"), ("a", "a"), ("one",), ("猫", "狗", "猫"))
    ):
        rows.append(
            {
                "id": f"json-{index}",
                "prompt": f"Create counts.json with occurrence counts of these words: {list(words)}.",
                "kind": "json",
                "words": words,
            }
        )
    return rows


def fixture_plan(task):
    """Fake fixture producer. Not evidence of natural-language understanding."""
    if task["kind"] == "html":
        name, content = (
            "index.html",
            "<!doctype html><h1>" + task["title"] + "</h1>",
        )
    elif task["kind"] == "csv":
        name, content = (
            "summary.csv",
            "total\n" + str(sum(task["values"])) + "\n",
        )
    else:
        name, content = "counts.json", json.dumps(
            {w: task["words"].count(w) for w in set(task["words"])},
            ensure_ascii=False,
        )
    return {"files": [{"name": name, "content": content}]}


def verify(task, root):
    """Inspect files, not agent-reported completion or artifact metadata."""
    if task["kind"] == "html":

        class HeadingParser(HTMLParser):
            """Extract actual heading text."""

            def __init__(self):
                super().__init__()
                self.inside = False
                self.headings = []

            def handle_starttag(self, tag, attrs):
                if tag == "h1":
                    self.inside = True
                    self.headings.append("")

            def handle_endtag(self, tag):
                if tag == "h1":
                    self.inside = False

            def handle_data(self, data):
                if self.inside:
                    self.headings[-1] += data

        heading_parser = HeadingParser()
        heading_parser.feed((root / "index.html").read_text())
        return heading_parser.headings == [task["title"]]
    if task["kind"] == "csv":
        rows = list(
            csv.DictReader(io.StringIO((root / "summary.csv").read_text()))
        )
        return len(rows) == 1 and int(rows[0]["total"]) == sum(task["values"])
    actual = json.loads((root / "counts.json").read_text())
    return set(actual) == set(task["words"]) and all(
        actual[w] == task["words"].count(w) for w in task["words"]
    )


async def evaluate(output, live_backend=None):
    """Backend receives only prompt and files; gold remains evaluator-local."""
    rows = []
    with tempfile.TemporaryDirectory() as directory:
        config = ExecutorConfig(enabled=True, work_dir=Path(directory))
        for task in tasks():
            backend = live_backend or FakeBackend(fixture_plan(task))
            executor = Executor(backend, config)
            start = time.monotonic()
            task_id = executor.submit(
                Request("sandbox", task["id"], 1, task["prompt"])
            )
            first = await executor.events.get()
            feedback_ms = (time.monotonic() - start) * 1000
            await executor.records[task_id].runner
            record = executor.records[task_id]
            root = (
                config.work_dir
                / hashlib.sha256(b"sandbox").hexdigest()[:24]
                / task_id
            )
            try:
                success = record.status == "completed" and verify(task, root)
            except (OSError, ValueError, KeyError):
                success = False
            rows.append(
                {
                    "id": task["id"],
                    "kind": "self_authored_sandbox",
                    "backend": "codex_sdk" if live_backend else "fake_fixture",
                    "success": success,
                    "status": record.status,
                    "feedback_event": first["type"],
                    "first_feedback_ms": feedback_ms,
                    "completion_ms": (time.monotonic() - start) * 1000,
                    "usage": record.usage,
                    "artifacts": record.artifacts,
                    "cost_usd": None if live_backend else 0,
                }
            )
            await executor.close()
    output.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return rows


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(evaluate(args.output))
    print(
        json.dumps(
            {
                "n": len(result),
                "success": sum(x["success"] for x in result),
                "backend": "fake_fixture",
            }
        )
    )
