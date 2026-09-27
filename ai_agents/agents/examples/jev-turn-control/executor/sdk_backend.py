"""Official async SDK backend; enabled only in a dedicated non-root container."""

# pylint: disable=line-too-long  # Preserve explicit benchmark/prompt text.

import asyncio
import json
import os
from pathlib import Path

INTERRUPT_TIMEOUT_SECONDS = 5

PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["files"],
    "properties": {
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "content"],
                "properties": {
                    "name": {"type": "string"},
                    "content": {"type": "string"},
                },
            },
        }
    },
}


class CodexBackend:
    """Generate bounded artifact JSON in a read-only SDK thread.

    No raw deltas, reasoning, shell output or provider error body is published.
    The SDK context is task-scoped; interrupt and context teardown run on cancel.
    Credential presence is not proof of model entitlement.
    """

    def __init__(self, client_factory=None):
        self.client_factory = client_factory

    async def run(self, record, directory, config):
        """Create a task thread and retain its ID for diagnostics/association."""
        # Test injection bypasses environment checks, never configured on wire.
        if self.client_factory is None:
            if not Path("/.dockerenv").exists() or os.geteuid() == 0:
                raise RuntimeError(
                    "dedicated non-root executor container required"
                )
            if not os.environ.get("OPENAI_API_KEY"):
                raise RuntimeError(
                    "executor OpenAI credential is not configured"
                )
        from openai_codex import (  # pylint: disable=import-outside-toplevel
            AsyncCodex,
            ApprovalMode,
            Sandbox,
        )

        factory = self.client_factory or AsyncCodex
        existing = {
            p.name: p.read_text()
            for p in directory.iterdir()
            if p.is_file()
            and not p.is_symlink()
            and p.stat().st_size <= config.max_artifact_bytes
        }
        prompt = json.dumps(
            {
                "request": record.request.text,
                "existing_artifacts": existing,
                "allowed_capabilities": list(config.allowed_capabilities),
                "instruction": "Return a JSON file plan only. Create/modify local HTML/CSV/TXT/JSON artifacts. Do not execute commands, browse, send messages, install dependencies or use external tools. File names must be simple basenames. No scripts or external resources in HTML. Return the complete desired artifact set, including unchanged files to retain; omitted previous files will be removed. At most four files, 64 KiB each.",
            },
            ensure_ascii=False,
        )
        async with factory() as client:
            if self.client_factory is None:
                await client.login_api_key(os.environ["OPENAI_API_KEY"])
                catalog = (await client.models()).model_dump(mode="json")
                model = next(
                    (
                        row
                        for row in catalog["data"]
                        if row["model"] == config.model
                    ),
                    None,
                )
                efforts = (
                    []
                    if model is None
                    else [
                        row["reasoning_effort"]
                        for row in model["supported_reasoning_efforts"]
                    ]
                )
                if config.reasoning_effort not in efforts:
                    raise ValueError(
                        "model/effort unavailable in runtime catalog"
                    )
            thread = await client.thread_start(
                model=config.model,
                cwd=str(directory),
                sandbox=Sandbox.read_only,
                approval_mode=ApprovalMode.deny_all,
                config={
                    "model_reasoning_effort": config.reasoning_effort,
                    "web_search": "disabled",
                    "features": {"shell_tool": False},
                    "shell_environment_policy": {"inherit": "none"},
                },
            )
            record.thread_id = thread.id
            handle = await thread.turn(
                prompt,
                effort=config.reasoning_effort,
                output_schema=PLAN_SCHEMA,
            )
            try:
                result = await handle.run()
            except asyncio.CancelledError:
                try:
                    await asyncio.wait_for(
                        handle.interrupt(), timeout=INTERRUPT_TIMEOUT_SECONDS
                    )
                except Exception:  # pylint: disable=broad-exception-caught
                    # Cleanup failure must not replace the original cancellation.
                    pass
                raise
            if (
                str(getattr(result.status, "value", result.status))
                != "completed"
            ):
                raise RuntimeError("SDK turn did not complete")
            usage = result.usage
            if usage is not None:
                record.usage = (
                    usage.model_dump() if hasattr(usage, "model_dump") else {}
                )
            return json.loads(result.final_response)
