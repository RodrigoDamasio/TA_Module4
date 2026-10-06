"""Background jobs: indexing (CPU-bound embedding) and full evaluations (LLM calls)."""

import secrets
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


TERMINAL = {JobStatus.COMPLETED, JobStatus.FAILED}


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Job:
    id: str
    kind: Literal["index", "evaluate"]
    status: JobStatus
    request: dict[str, Any]
    progress: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    created_at: str = field(default_factory=now_iso)
    started_at: str | None = None
    finished_at: str | None = None

    @classmethod
    def create(cls, kind: Literal["index", "evaluate"], request: dict[str, Any]) -> "Job":
        prefix = "idx" if kind == "index" else "evl"
        return cls(f"{prefix}_{secrets.token_hex(6)}", kind, JobStatus.QUEUED, request)

    def start(self) -> None:
        self.status, self.started_at = JobStatus.RUNNING, now_iso()

    def complete(self, result: dict[str, Any]) -> None:
        self.status, self.result, self.finished_at = JobStatus.COMPLETED, result, now_iso()

    def fail(self, title: str, detail: str) -> None:
        self.status, self.finished_at = JobStatus.FAILED, now_iso()
        self.error = {"title": title, "detail": detail}

    @property
    def done(self) -> bool:
        return self.status in TERMINAL

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Job":
        return cls(**(data | {"status": JobStatus(data["status"])}))
