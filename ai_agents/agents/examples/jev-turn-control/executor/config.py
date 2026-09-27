"""Server-owned configuration; never accept this from a voice/browser payload."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExecutorConfig:
    """Defaults deliberately keep execution off."""

    enabled: bool = False
    model: str = "gpt-6-luna"
    reasoning_effort: str = "low"
    timeout: float = 60.0
    max_tasks_per_session: int = 8
    work_dir: Path = Path(".executor-work")
    allowed_capabilities: tuple[str, ...] = ("artifact",)
    cancel_behavior: str = "interrupt_no_rollback"
    max_artifact_bytes: int = 65536
    max_artifacts: int = 4

    def __post_init__(self):
        if self.timeout <= 0 or self.max_tasks_per_session < 1:
            raise ValueError("invalid executor bounds")
        if self.cancel_behavior != "interrupt_no_rollback":
            raise ValueError("only interrupt_no_rollback is supported")
        if self.reasoning_effort not in ("none", "low", "medium", "high"):
            raise ValueError("unsupported effort; check deployment catalog")


@dataclass(frozen=True)
class RoutingConfig:
    """Two fixed prompt candidates; tune only on dev."""

    prompt_override: str = ""
    variant: str = "refined"
    execute_threshold: float = 0.75
    timeout: float = 20.0
    model: str = "jev-1.13.0"
