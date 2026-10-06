"""Named failures. Mapped to RFC 9457 problems only in app.api."""

from typing import Literal


class DomainError(Exception):
    """Base class for every expected failure."""


# ---- input -------------------------------------------------------------------------


class InvalidPath(DomainError):
    """Invalid input that maps to one request field (JSON Pointer, default `#/files`)."""

    def __init__(self, message: str, pointer: str = "#/files") -> None:
        super().__init__(message)
        self.pointer = pointer


class InputTooLarge(DomainError):
    pass


class UnsupportedFileType(DomainError):
    pass


class CodebaseNotFound(DomainError):
    def __init__(self, codebase: str) -> None:
        super().__init__(f"No codebase with id '{codebase}'.")
        self.codebase = codebase


class ReadOnlyCodebase(DomainError):
    def __init__(self, codebase: str) -> None:
        super().__init__(f"'{codebase}' is a sample codebase: it cannot be changed or deleted.")
        self.codebase = codebase


class TooManyCodebases(DomainError):
    def __init__(self, limit: int) -> None:
        super().__init__(
            f"The server already holds {limit} user codebases; delete one or wait until one "
            "expires."
        )


class EmptyIndex(DomainError):
    def __init__(self, codebases: list[str]) -> None:
        super().__init__(f"Nothing is indexed in: {', '.join(codebases)}.")


class JobNotFound(DomainError):
    def __init__(self, job_id: str) -> None:
        super().__init__(f"No job with id '{job_id}'.")
        self.job_id = job_id


class EvaluationNotFound(DomainError):
    def __init__(self, report_id: str) -> None:
        super().__init__(f"No evaluation report with id '{report_id}'.")


class QueueFull(DomainError):
    def __init__(self) -> None:
        super().__init__("Too many jobs are waiting; try again in a minute.")


class ModelsLoading(DomainError):
    def __init__(self) -> None:
        super().__init__("The embedding model is still loading; try again in a few seconds.")


class BudgetExceeded(DomainError):
    def __init__(self, limit: int) -> None:
        super().__init__(f"The run reached its limit of {limit} real LLM calls.")
        self.limit = limit


# ---- LLM provider (from Labs 2-3) ------------------------------------------------------


class LLMError(DomainError):
    """Base class for failures talking to the LLM provider."""


class LLMQuotaExceeded(LLMError):
    def __init__(self, scope: Literal["minute", "day"], retry_after_s: float) -> None:
        super().__init__(f"LLM quota exceeded ({scope}); retry after {retry_after_s:.0f}s.")
        self.scope = scope
        self.retry_after_s = retry_after_s


class LLMUnavailable(LLMError):
    def __init__(self, reason: str, retry_after_s: float = 10) -> None:
        super().__init__(reason)
        self.retry_after_s = retry_after_s


class LLMOverloaded(LLMUnavailable):
    """The provider is temporarily overloaded (HTTP 5xx) — worth a short retry."""


class LLMTimeout(LLMError):
    pass


class LLMRequestRejected(LLMError):
    """The provider refused the request (bad key, invalid request, blocked content)."""

    def __init__(self, status: int | None, reason: str) -> None:
        super().__init__(reason)
        self.status = status


class LLMBadResponse(LLMError):
    """The model's answer could not be turned into a valid result."""
