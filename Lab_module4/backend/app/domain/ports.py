"""Provider-neutral abstractions (LLM types from Labs 2-3) and the RAG ports."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from .chunks import Chunk
from .codebases import Codebase, FileRecord
from .jobs import Job
from .tracing import Trace

FinishReason = Literal["stop", "max_tokens", "safety", "other"]


# ---- LLM (unchanged from Lab 3) ---------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


@dataclass(frozen=True)
class ToolCall:
    id: str | None
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    call_id: str | None
    name: str
    content: str


@dataclass(frozen=True)
class TokenUsage:
    input: int = 0
    output: int = 0
    thinking: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            self.input + other.input, self.output + other.output, self.thinking + other.thinking
        )


@dataclass(frozen=True)
class UserMessage:
    text: str


@dataclass(frozen=True)
class AssistantMessage:
    text: str | None
    tool_calls: list[ToolCall]
    raw_turn: Any = None  # provider turn, echoed back unchanged in the next request


@dataclass(frozen=True)
class ToolResultsMessage:
    results: list[ToolResult]


Message = UserMessage | AssistantMessage | ToolResultsMessage


@dataclass(frozen=True)
class LLMRequest:
    system: str
    messages: list[Message]
    tools: list[ToolSpec] = field(default_factory=list)
    response_schema: type[BaseModel] | None = None
    max_output_tokens: int = 2048
    thinking_budget: int | None = None


@dataclass(frozen=True)
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall]
    parsed: dict[str, Any] | None
    usage: TokenUsage
    finish_reason: FinishReason
    raw_turn: Any = None
    cached: bool = False  # served by CachingLLMClient (0 real calls)

    def as_message(self) -> AssistantMessage:
        return AssistantMessage(self.text, self.tool_calls, self.raw_turn)


class LLMClient(Protocol):
    def generate(self, request: LLMRequest) -> LLMResponse: ...


# ---- models -------------------------------------------------------------------------------


class Embedder(Protocol):
    name: str
    dim: int
    max_tokens: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class Reranker(Protocol):
    name: str

    def score(self, query: str, texts: list[str]) -> list[float]: ...


# ---- storage ------------------------------------------------------------------------------


class VectorStore(Protocol):
    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...

    def delete_file(self, codebase: str, path: str) -> int: ...

    def delete_codebase(self, codebase: str) -> int: ...

    def query(self, vector: list[float], codebases: list[str], n: int) -> list[tuple[str, float]]:
        """(chunk id, cosine distance), nearest first."""
        ...

    def get(self, ids: list[str]) -> list[Chunk]: ...

    def iter_chunks(
        self, codebase: str | None = None, path: str | None = None
    ) -> Iterator[Chunk]: ...

    def count(self, codebase: str | None = None) -> int: ...


class IndexRepository(Protocol):
    def get_codebase(self, codebase: str) -> Codebase | None: ...

    def list_codebases(self) -> list[Codebase]: ...

    def save_codebase(self, codebase: Codebase) -> None: ...

    def delete_codebase(self, codebase: str) -> None: ...

    def files(self, codebase: str) -> list[FileRecord]: ...

    def get_file(self, codebase: str, path: str) -> FileRecord | None: ...

    def save_file(self, record: FileRecord) -> None: ...

    def delete_file(self, codebase: str, path: str) -> None: ...


class EmbeddingCache(Protocol):
    def get_many(self, model: str, keys: list[str]) -> dict[str, list[float]]: ...

    def put_many(self, model: str, items: dict[str, list[float]]) -> None: ...

    def stats(self) -> dict[str, int]: ...


class JobRepository(Protocol):
    def save(self, job: Job) -> None: ...

    def get(self, job_id: str) -> Job: ...

    def with_status(self, statuses: set[str]) -> list[Job]: ...


class TraceStore(Protocol):
    def save(self, trace: Trace) -> None: ...

    def recent(self, limit: int) -> list[Trace]: ...


class ReportStore(Protocol):
    def save(self, report_id: str, kind: str, report: dict) -> None: ...

    def get(self, report_id: str) -> dict: ...

    def all(self) -> list[dict]: ...


class JobRunner(Protocol):
    def submit(self, job_id: str) -> None: ...

    def has_capacity(self) -> bool: ...
