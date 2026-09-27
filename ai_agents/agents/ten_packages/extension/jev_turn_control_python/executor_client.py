"""Nonblocking voice-side mailbox; no SDK or OpenAI key in the voice process."""

import asyncio
import json
import os

import aiohttp


class ExecutorClient:
    """One remote call session, never recreated silently after an error/restart."""

    def __init__(self, emit, enabled=False):
        self.emit = emit
        self.enabled = (
            enabled and os.environ.get("JEV_CODEX_ENABLED", "false") == "true"
        )
        self.url = os.environ.get("JEV_EXECUTOR_URL", "").rstrip("/")
        self.token = os.environ.get("JEV_EXECUTOR_TOKEN", "")
        self.queue = asyncio.Queue(8)
        self.state = {
            "status": "disabled" if not self.enabled else "connecting"
        }
        self.client = self.sid = self.worker = None
        self.last_version = 0
        self.latest_revision = 0
        self.failed = False

    def start(self):
        if self.enabled:
            self.worker = asyncio.create_task(self.run())

    def submit(self, revision, text, context):
        if not self.enabled or self.failed or revision <= self.latest_revision:
            return
        try:
            self.queue.put_nowait(
                {
                    "input_revision": revision,
                    "text": " ".join(text[:12000].split()),
                    "context": json.dumps(context, ensure_ascii=False)[-16000:],
                }
            )
            self.latest_revision = revision
            self.state = {"status": "queued", "input_revision": revision}
        except asyncio.QueueFull:
            self.input_error("input_capacity", revision)

    def input_error(self, code, revision):
        """Reject only this input; keep the call and accepted work alive."""
        self.emit(
            "task.error",
            {
                "task_id": "call-executor",
                "status": "error",
                "code": code,
                "input_revision": revision,
            },
        )

    def fail(self, code):
        self.failed = True
        self.state = {
            "task_id": "call-executor",
            "status": "error",
            "code": code,
        }
        self.emit("task.error", self.state)

    async def request(self, method, path, payload=None):
        async with self.client.request(
            method, self.url + path, json=payload, allow_redirects=False
        ) as response:
            if method == "POST" and path.endswith("/inputs"):
                if response.status == 429:
                    return {"retry": True}
                if response.status == 400:
                    return {"rejected": True}
            if response.status not in (200, 201, 202):
                raise ValueError("executor unavailable")
            body = bytearray()
            async for chunk in response.content.iter_chunked(8192):
                body.extend(chunk)
                if len(body) > 32768:
                    raise ValueError("executor response too large")
            return json.loads(body)

    async def run(self):
        try:
            if (
                not self.url.startswith(("http://", "https://"))
                or len(self.token) < 32
            ):
                raise ValueError("executor configuration missing")
            async with aiohttp.ClientSession(
                headers={"Authorization": "Bearer " + self.token},
                timeout=aiohttp.ClientTimeout(total=3),
                json_serialize=lambda value: json.dumps(
                    value, ensure_ascii=False
                ),
            ) as client:
                self.client = client
                created = await self.request("POST", "/sessions")
                self.sid = created["session_id"]
                path = "/sessions/" + self.sid
                pending = None
                try:
                    while not self.failed:
                        if pending is None:
                            try:
                                pending = await asyncio.wait_for(
                                    self.queue.get(), 0.2
                                )
                            except asyncio.TimeoutError:
                                pass
                        if pending is not None:
                            admitted = await self.request(
                                "POST", path + "/inputs", pending
                            )
                            if admitted.get("retry"):
                                await asyncio.sleep(0.2)
                            else:
                                if admitted.get("rejected"):
                                    self.input_error(
                                        "input_rejected",
                                        pending["input_revision"],
                                    )
                                pending = None
                        state = await self.request("GET", path)
                        if state["version"] > self.last_version:
                            self.last_version = state["version"]
                            # If newer inputs are still local, an old completion is not current.
                            state["current"] = (
                                pending is None
                                and self.queue.empty()
                                and state.get("input_revision", 0)
                                >= self.latest_revision
                            )
                            state["task_id"] = "call-executor"
                            self.state = state
                            kind = {
                                "completed": "task.completed",
                                "error": "task.error",
                            }.get(state["status"], "task.started")
                            self.emit(kind, state)
                finally:
                    try:
                        await self.request("DELETE", path)
                    except Exception:
                        pass  # Service TTL cleans abandoned sessions; never log credentials.
        except Exception:
            self.fail("executor_unavailable")
        finally:
            self.client = None

    async def close(self):
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
