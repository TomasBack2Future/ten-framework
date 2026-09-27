"""Nonblocking, revision-fenced artifact tasks. No speech-control coupling."""

# pylint: disable=broad-exception-caught  # Sanitize provider boundary failures.

import asyncio
import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field

from .config import ExecutorConfig


@dataclass(frozen=True)
class Request:
    """Trusted accepted-turn projection, not a shared wire schema."""

    session_id: str
    turn_id: str
    input_revision: int
    text: str
    stable: bool = True
    route: str = "execute"
    support: str = "supported"
    capability: str = "artifact"


@dataclass
class Record:
    """Public task state and private coroutine handle."""

    task_id: str
    request: Request
    status: str = "queued"
    summary: str = "Task queued"
    artifacts: list = field(default_factory=list)
    thread_id: str | None = None
    usage: dict = field(default_factory=dict)
    created: float = field(default_factory=time.monotonic)
    finished: float | None = None
    runner: asyncio.Task | None = field(default=None, repr=False)


class Executor:
    """One instance per worker, with per-session caps and at-most-once starts.

    Backends return bounded file plans. Only this trusted writer commits them.
    Revision fencing is per task input, never unrelated conversational input.
    Restart does not replay requests: the host must allocate a new session id.
    """

    def __init__(self, backend, config=None):
        self.config = config or ExecutorConfig()
        self.backend = backend
        self.records = {}
        self.accepted = {}
        self.latest = {}
        self.events = asyncio.Queue()

    def _emit(self, record, event):
        req = record.request
        self.events.put_nowait(
            {
                "type": event,
                "session_id": req.session_id,
                "payload": {
                    "task_id": record.task_id,
                    "turn_id": req.turn_id,
                    "input_revision": req.input_revision,
                    "status": record.status,
                    "summary": record.summary,
                    "artifacts": record.artifacts,
                },
            }
        )

    def submit(self, request):
        """Return immediately; partials and unsupported requests never start."""
        if not self.config.enabled or not request.stable:
            return None
        if request.route != "execute" or request.support != "supported":
            return None
        if request.capability not in self.config.allowed_capabilities:
            return None
        if not request.text.strip() or request.input_revision < 0:
            raise ValueError("invalid request")
        key = (request.session_id, request.turn_id)
        if key in self.accepted:
            # A correction must explicitly adjust the original task.
            return self.accepted[key]
        count = sum(
            r.request.session_id == request.session_id
            for r in self.records.values()
        )
        if count >= self.config.max_tasks_per_session:
            raise ValueError("session task limit reached")
        task_id = uuid.uuid4().hex
        record = Record(task_id, request)
        self.records[task_id] = record
        self.accepted[key] = task_id
        self.latest[task_id] = request.input_revision
        record.runner = asyncio.create_task(self._run(record))
        return task_id

    def status(self, session_id, task_id):
        """Session-scoped access prevents cross-session task control."""
        record = self.records.get(task_id)
        if record is None or record.request.session_id != session_id:
            raise ValueError("unknown task")
        return record

    async def cancel(self, session_id, task_id):
        """Fence writes before cancellation; completed side effects remain."""
        record = self.status(session_id, task_id)
        if record.status in ("completed", "cancelled", "error"):
            return record.status
        self.latest[task_id] += 1
        record.status = "cancelled"
        record.summary = "Task cancelled; completed changes are not rolled back"
        record.runner.cancel()
        await asyncio.gather(record.runner, return_exceptions=True)
        record.finished = time.monotonic()
        self._emit(record, "task.cancelled")
        return record.status

    async def adjust(self, session_id, task_id, revision, text):
        """Cancel-and-replace within the same task directory, with a new version."""
        record = self.status(session_id, task_id)
        if revision <= max(record.request.input_revision, self.latest[task_id]):
            raise ValueError("stale adjustment")
        await self.cancel(session_id, task_id)
        old = record.request
        record.request = Request(session_id, old.turn_id, revision, text)
        self.latest[task_id] = revision
        record.status, record.summary = "queued", "Task adjusted"
        record.finished = None
        record.runner = asyncio.create_task(self._run(record))
        return task_id

    async def close(self):
        """Terminate only tasks owned by this adapter."""
        for task_id, record in list(self.records.items()):
            await self.cancel(record.request.session_id, task_id)

    async def _run(self, record):
        version = record.request.input_revision
        record.status, record.summary = "running", "Creating local artifact"
        self._emit(record, "task.started")
        session_hash = hashlib.sha256(
            record.request.session_id.encode()
        ).hexdigest()[:24]
        directory = (
            self.config.work_dir.resolve() / session_hash / record.task_id
        )
        directory.mkdir(parents=True, exist_ok=True)
        try:
            plan = await asyncio.wait_for(
                self.backend.run(record, directory, self.config),
                timeout=self.config.timeout,
            )
            if self.latest[record.task_id] != version:
                return
            files = self._validate_plan(plan, directory)
            # No await between the fence and commit: cancellation cannot interleave.
            for name, content in files:
                (directory / name).write_text(content, encoding="utf-8")
            record.artifacts = [
                {
                    "name": name,
                    "sha256": hashlib.sha256(content.encode()).hexdigest(),
                    "bytes": len(content.encode()),
                }
                for name, content in files
            ]
            record.status, record.summary = (
                "completed",
                f"Created {len(files)} artifact(s)",
            )
            record.finished = time.monotonic()
            self._emit(record, "task.completed")
        except (
            Exception
        ) as exc:  # Boundary: never send provider exception text/secrets.
            record.status = "error"
            record.summary = "Task failed: " + type(exc).__name__
            record.finished = time.monotonic()
            self._emit(record, "task.error")

    def _validate_plan(self, plan, directory):
        files = plan.get("files", [])
        if not 0 <= len(files) <= self.config.max_artifacts:
            raise ValueError("invalid artifact count")
        result = []
        seen = set()
        for item in files:
            name, content = item["name"], item["content"]
            if (
                not isinstance(content, str)
                or len(content.encode()) > self.config.max_artifact_bytes
            ):
                raise ValueError("artifact too large")
            if not re.fullmatch(r"[A-Za-z0-9_-]+\.(html|csv|txt|json)", name):
                raise ValueError("invalid artifact path")
            if name in seen or (directory / name).is_symlink():
                raise ValueError("duplicate or symlink artifact")
            seen.add(name)
            result.append((name, content))
        return result


class FakeBackend:
    """Deterministic plan fixture, explicitly not a model or classifier."""

    def __init__(self, plan=None, delay=0.01):
        self.plan = plan or {
            "files": [{"name": "index.html", "content": "<h1>Demo</h1>"}]
        }
        self.delay = delay
        self.starts = 0

    async def run(self, record, directory, config):
        """Exercise async lifecycle without network or arbitrary shell."""
        del record, directory, config
        self.starts += 1
        await asyncio.sleep(self.delay)
        return json.loads(json.dumps(self.plan))
