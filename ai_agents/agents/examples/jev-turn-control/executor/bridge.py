"""Optional host hook. Shared TEN wire envelope remains owned by voice engine."""

from .adapter import Request


class Bridge:
    """Call after accepted-turn routing, independently of TTS start/stop."""

    def __init__(self, executor):
        self.executor = executor

    async def accept(self, request: Request, action=None, task_id=None):
        """Host binds action/target to the session; no implicit cancel-all."""
        if not self.executor.config.enabled or not request.stable:
            return None
        if request.route != "task_control":
            return self.executor.submit(request)
        if request.support != "supported" or not task_id:
            return None  # Ask clarification through the existing voice layer.
        if action == "cancel":
            return await self.executor.cancel(request.session_id, task_id)
        if action == "adjust":
            return await self.executor.adjust(
                request.session_id,
                task_id,
                request.input_revision,
                request.text,
            )
        if action == "status":
            record = self.executor.status(request.session_id, task_id)
            return {
                "task_id": task_id,
                "status": record.status,
                "summary": record.summary,
                "artifacts": record.artifacts,
            }
        raise ValueError("explicit task control action required")
