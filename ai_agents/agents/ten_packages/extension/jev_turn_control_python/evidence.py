"""Private append-only demo evidence, independent of the UI event ring."""

import json
import os
import re
import time
import queue
import threading
import sys
from pathlib import Path


SECRET_FIELD = re.compile(
    r"(?:api[_-]?key|authorization|cookie|password|secret|access[_-]?token|"
    r"refresh[_-]?token|access[_-]?code|^token$|[_-]token$|[_-]key$|certificate)",
    re.I,
)


def scrub(value):
    """Preserve business text; exclude credential fields and known values."""
    if isinstance(value, dict):
        return {
            key: "[credential]" if SECRET_FIELD.search(key) else scrub(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [scrub(item) for item in value]
    if isinstance(value, str):
        for key, secret in os.environ.items():
            if SECRET_FIELD.search(key) and secret:
                value = value.replace(secret, "[credential]")
        value = re.sub(
            r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [credential]", value
        )
    return value


class Evidence:
    """One graph writer per session; no rotation or business-data truncation."""

    def __init__(self, session_id):
        self.directory = None
        self.queue = queue.Queue(maxsize=4096)
        self.offsets = {}
        self.failure = None
        self.worker = None
        self.sequence = 0
        self.revision = os.environ.get("JEV_REVISION", "development")
        self.session_id = session_id
        directory = os.environ.get("JEV_EVENT_LOG_DIR")
        if directory:
            if not re.fullmatch(r"[a-zA-Z0-9_-]+", session_id):
                raise ValueError("invalid evidence session id")
            self.directory = Path(directory) / session_id
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.worker = threading.Thread(target=self.run, daemon=True)
            self.worker.start()

    def write(self, kind, payload, response_id=None):
        if not self.directory or self.failure:
            return
        self.sequence += 1
        event = {
            "schema": "jev.evidence.v1",
            "source": "graph",
            "record_seq": self.sequence,
            "session_id": self.session_id,
            "revision": self.revision,
            "response_id": response_id,
            "wall_time_ns": time.time_ns(),
            "monotonic_ns": time.monotonic_ns(),
            "type": kind,
            "payload": scrub(payload),
        }
        self.append(
            "graph.jsonl",
            (json.dumps(event, ensure_ascii=False) + "\n").encode(),
        )

    def append(self, name, data):
        if self.failure:
            return None
        offset = self.offsets.get(name, 0)
        self.offsets[name] = offset + len(data)
        try:
            self.queue.put_nowait((name, data))
        except queue.Full:
            self.failure = True
            print("JEV_EVIDENCE_QUEUE_FULL", file=sys.stderr)
            return None
        return offset

    def run(self):
        streams = {}
        while True:
            item = self.queue.get()
            try:
                if item is None:
                    break
                name, data = item
                if name not in streams:
                    fd = os.open(
                        self.directory / name,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o600,
                    )
                    streams[name] = os.fdopen(fd, "wb", buffering=0)
                if not self.failure:
                    streams[name].write(data)
            except OSError:
                self.failure = True
                print("JEV_EVIDENCE_WRITE_FAILED", file=sys.stderr)
            finally:
                self.queue.task_done()
        for stream in streams.values():
            try:
                os.fsync(stream.fileno())
                stream.close()
            except OSError:
                self.failure = True
                print("JEV_EVIDENCE_CLOSE_FAILED", file=sys.stderr)

    def close(self):
        if self.worker:
            self.queue.put(None)
            self.worker.join()
            self.worker = None
        if self.failure:
            raise RuntimeError("evidence storage failed")

    def audio(self, pcm, metadata, response_id):
        if not self.directory or self.failure:
            return
        offset = self.append("tts.pcm", pcm)
        self.write(
            "tts.audio",
            {
                "file": "tts.pcm",
                "offset": offset,
                "length": len(pcm),
                "metadata": metadata,
            },
            response_id,
        )
