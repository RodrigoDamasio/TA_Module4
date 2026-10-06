"""RFC 9457 Problem Details: the single place where errors become HTTP responses."""

import logging
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.config import get_settings
from app.domain.errors import (
    CodebaseNotFound,
    EmptyIndex,
    EvaluationNotFound,
    InputTooLarge,
    InvalidPath,
    JobNotFound,
    LLMBadResponse,
    LLMQuotaExceeded,
    LLMRequestRejected,
    LLMTimeout,
    LLMUnavailable,
    ModelsLoading,
    QueueFull,
    ReadOnlyCodebase,
    TooManyCodebases,
    UnsupportedFileType,
)

from .guards import RateLimited

PROBLEM_JSON = "application/problem+json"
logger = logging.getLogger(__name__)


# ---- model -----------------------------------------------------------------


class FieldError(BaseModel):
    detail: str
    pointer: str  # JSON Pointer (RFC 6901) into the request body, e.g. "#/url"


class Problem(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    errors: list[FieldError] | None = None  # extension member (RFC 9457 §3.2)


# OpenAPI documentation for error responses
PROBLEM_RESPONSE: dict[str, Any] = {
    "model": Problem,
    "content": {PROBLEM_JSON: {}},
    "description": "RFC 9457 Problem Details",
}


# ---- catalog ---------------------------------------------------------------


@dataclass(frozen=True)
class ProblemType:
    slug: str
    status: int
    title: str
    description: str


def _p(slug: str, status: int, title: str, description: str) -> ProblemType:
    return ProblemType(slug, status, title, description)


VALIDATION_ERROR = _p(
    "validation-error",
    422,
    "Your request is not valid.",
    "One or more fields in the request body are invalid. See `errors` for each field.",
)
MALFORMED_REQUEST = _p(
    "malformed-request",
    400,
    "The request body is not valid JSON.",
    "The request body could not be parsed as JSON.",
)
CODEBASE_NOT_FOUND = _p(
    "codebase-not-found",
    404,
    "Codebase not found.",
    "No codebase has this id. See GET /codebases. User codebases expire after 24 hours.",
)
JOB_NOT_FOUND = _p(
    "job-not-found", 404, "Job not found.", "No index or evaluation job has this id."
)
EVALUATION_NOT_FOUND = _p(
    "evaluation-not-found",
    404,
    "Evaluation report not found.",
    "No stored evaluation report has this id. See GET /evaluations.",
)
CODEBASE_READ_ONLY = _p(
    "codebase-read-only",
    409,
    "This codebase is read-only.",
    "Sample codebases ship with the app and cannot be changed or deleted. Index your files "
    "into a codebase with another id.",
)
TOO_MANY_CODEBASES = _p(
    "too-many-codebases",
    409,
    "Too many codebases.",
    "The server holds a limited number of user codebases. Delete one or wait until one expires.",
)
INPUT_TOO_LARGE = _p(
    "input-too-large",
    413,
    "Too much code.",
    "Too many files or bytes for one request or one codebase. `detail` states the limit.",
)
UNSUPPORTED_FILE_TYPE = _p(
    "unsupported-file-type",
    422,
    "Unsupported file type.",
    "Python, TypeScript, JavaScript, Markdown and common text/config files are indexed.",
)
EMPTY_INDEX = _p(
    "empty-index",
    422,
    "Nothing is indexed there.",
    "The selected codebases contain no chunks yet. Index files first.",
)
RATE_LIMITED = _p(
    "rate-limited",
    429,
    "Too many requests.",
    "This client sent too many requests. Retry after the `Retry-After` delay.",
)
LLM_QUOTA_EXHAUSTED = _p(
    "llm-quota-exhausted",
    503,
    "The answer limit has been reached.",
    "The LLM provider's daily quota is used up. Search still works. Retry after the "
    "`Retry-After` delay.",
)
LLM_UNAVAILABLE = _p(
    "llm-unavailable",
    503,
    "The answer service is unavailable.",
    "The LLM provider could not be reached or is overloaded. Retry after `Retry-After`.",
)
BUSY = _p(
    "busy",
    503,
    "The server is busy.",
    "Too many index or evaluation jobs are queued. Retry after the `Retry-After` delay.",
)
MODELS_LOADING = _p(
    "models-loading",
    503,
    "The search models are still loading.",
    "The local embedding model loads in the background after a start. Retry in a few seconds.",
)
LLM_BAD_RESPONSE = _p(
    "llm-bad-response",
    502,
    "The model's answer was not usable.",
    "The model returned an invalid answer twice. Try again or rephrase the question.",
)
WAIT_TIMEOUT = _p(
    "wait-timeout",
    504,
    "The job is still running.",
    "`?wait=true` gave up waiting. The job continues: follow the `Location` header.",
)
INTERNAL_ERROR = _p(
    "internal-error",
    500,
    "Internal server error.",
    "An unexpected error occurred. It has been logged.",
)

CATALOG = {
    p.slug: p
    for p in (
        VALIDATION_ERROR, MALFORMED_REQUEST, CODEBASE_NOT_FOUND, JOB_NOT_FOUND,
        EVALUATION_NOT_FOUND, CODEBASE_READ_ONLY, TOO_MANY_CODEBASES, INPUT_TOO_LARGE,
        UNSUPPORTED_FILE_TYPE, EMPTY_INDEX, RATE_LIMITED, LLM_QUOTA_EXHAUSTED, LLM_UNAVAILABLE,
        BUSY, MODELS_LOADING, LLM_BAD_RESPONSE, WAIT_TIMEOUT, INTERNAL_ERROR,
    )
}  # fmt: skip


class WaitTimeout(Exception):
    def __init__(self, job_id: str, seconds: int) -> None:
        super().__init__(f"Job {job_id} did not finish within {seconds}s; it is still running.")
        self.job_id = job_id


# ---- building responses ----------------------------------------------------


def problem_response(
    request: Request,
    problem_type: ProblemType | None,
    *,
    status: int | None = None,
    detail: str | None = None,
    errors: list[FieldError] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    if problem_type is None:  # about:blank — title SHOULD be the HTTP reason phrase
        status = status or 500
        type_, title = "about:blank", HTTPStatus(status).phrase
    else:
        status = problem_type.status
        type_ = f"{get_settings().base_url}/problems/{problem_type.slug}"
        title = problem_type.title

    body = Problem(
        type=type_,
        title=title,
        status=status,
        detail=detail,
        instance=request.url.path,
        errors=errors,
    )
    return JSONResponse(
        body.model_dump(exclude_none=True),
        status_code=status,
        media_type=PROBLEM_JSON,
        headers=headers,
    )


def _json_pointer(loc: tuple[int | str, ...]) -> str:
    """("body", "url") -> "#/url" (RFC 6901, with ~ and / escaped)."""
    parts = [str(p).replace("~", "~0").replace("/", "~1") for p in loc[1:]]
    return "#/" + "/".join(parts) if parts else "#"


def _friendly_message(error: dict[str, Any]) -> str:
    kind = error.get("type", "")
    if kind == "missing":
        return "This field is required."
    if kind in ("string_too_short", "too_short"):
        minimum = error.get("ctx", {}).get("min_length", 1)
        if minimum <= 1:
            return "Must not be empty."
        unit = "characters" if kind == "string_too_short" else "items"
        return f"Must be at least {minimum} {unit}."
    if kind == "enum":
        expected = error.get("ctx", {}).get("expected", "")
        return f"Must be one of: {expected}." if expected else "Unsupported value."
    return str(error.get("msg", "Invalid value.")).removeprefix("Value error, ")


# ---- handlers --------------------------------------------------------------


async def _validation_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, RequestValidationError)  # noqa: S101 — narrows the type
    errors = exc.errors()
    if any(e.get("type") == "json_invalid" for e in errors):
        return problem_response(request, MALFORMED_REQUEST)
    field_errors = [
        FieldError(detail=_friendly_message(e), pointer=_json_pointer(tuple(e["loc"])))
        for e in errors
    ]
    count = len(field_errors)
    return problem_response(
        request,
        VALIDATION_ERROR,
        detail=f"The request body has {count} invalid field{'s' if count != 1 else ''}.",
        errors=field_errors,
    )


def _retry_after(seconds: float) -> dict[str, str]:
    return {"Retry-After": str(max(1, round(seconds)))}


def _simple(problem_type: ProblemType, retry_after: float | None = None):
    async def handler(request: Request, exc: Exception) -> Response:
        headers = _retry_after(retry_after) if retry_after else None
        return problem_response(request, problem_type, detail=str(exc), headers=headers)

    return handler


async def _invalid_path_handler(request: Request, exc: Exception) -> Response:
    pointer = exc.pointer if isinstance(exc, InvalidPath) else "#"
    return problem_response(
        request,
        VALIDATION_ERROR,
        detail="The request body has 1 invalid field.",
        errors=[FieldError(detail=str(exc), pointer=pointer)],
    )


async def _wait_timeout_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, WaitTimeout)  # noqa: S101 — narrows the type
    return problem_response(
        request, WAIT_TIMEOUT, detail=str(exc), headers={"Location": f"/jobs/{exc.job_id}"}
    )


async def _rate_limited_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, RateLimited)  # noqa: S101 — narrows the type
    return problem_response(
        request, RATE_LIMITED, detail=str(exc), headers=_retry_after(exc.retry_after_s)
    )


async def _quota_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, LLMQuotaExceeded)  # noqa: S101 — narrows the type
    when = "tomorrow" if exc.retry_after_s > 3600 else "shortly"
    return problem_response(
        request,
        LLM_QUOTA_EXHAUSTED,
        detail=f"The free-tier LLM quota is used up; try again {when}. Search still works.",
        headers=_retry_after(exc.retry_after_s or 60),
    )


async def _unavailable_handler(request: Request, exc: Exception) -> Response:
    retry = exc.retry_after_s if isinstance(exc, LLMUnavailable) else 30
    return problem_response(request, LLM_UNAVAILABLE, detail=str(exc), headers=_retry_after(retry))


async def _http_exception_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101 — narrows the type
    phrase = HTTPStatus(exc.status_code).phrase
    detail = exc.detail if exc.detail and exc.detail != phrase else None
    return problem_response(
        request, None, status=exc.status_code, detail=detail, headers=exc.headers
    )


class UnhandledErrorMiddleware(BaseHTTPMiddleware):
    """Turns unexpected exceptions into an `internal-error` problem.

    Must be registered BEFORE CORSMiddleware so CORS wraps it and 500s keep their
    CORS headers (Starlette makes the last-added middleware the outermost).
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            return await call_next(request)
        except Exception:
            logger.exception("Unhandled error on %s %s", request.method, request.url.path)
            return problem_response(
                request, INTERNAL_ERROR, detail="An unexpected error occurred. Please try again."
            )


def register_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(InvalidPath, _invalid_path_handler)
    app.add_exception_handler(CodebaseNotFound, _simple(CODEBASE_NOT_FOUND))
    app.add_exception_handler(JobNotFound, _simple(JOB_NOT_FOUND))
    app.add_exception_handler(EvaluationNotFound, _simple(EVALUATION_NOT_FOUND))
    app.add_exception_handler(ReadOnlyCodebase, _simple(CODEBASE_READ_ONLY))
    app.add_exception_handler(TooManyCodebases, _simple(TOO_MANY_CODEBASES))
    app.add_exception_handler(InputTooLarge, _simple(INPUT_TOO_LARGE))
    app.add_exception_handler(UnsupportedFileType, _simple(UNSUPPORTED_FILE_TYPE))
    app.add_exception_handler(EmptyIndex, _simple(EMPTY_INDEX))
    app.add_exception_handler(RateLimited, _rate_limited_handler)
    app.add_exception_handler(LLMQuotaExceeded, _quota_handler)
    app.add_exception_handler(LLMUnavailable, _unavailable_handler)
    app.add_exception_handler(LLMTimeout, _unavailable_handler)
    app.add_exception_handler(LLMRequestRejected, _unavailable_handler)
    app.add_exception_handler(QueueFull, _simple(BUSY, retry_after=60))
    app.add_exception_handler(ModelsLoading, _simple(MODELS_LOADING, retry_after=15))
    app.add_exception_handler(LLMBadResponse, _simple(LLM_BAD_RESPONSE))
    app.add_exception_handler(WaitTimeout, _wait_timeout_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)


# ---- problem type documentation (types SHOULD be dereferenceable) ---------

router = APIRouter(prefix="/problems", tags=["problems"])


@router.get("/{slug}", responses={404: PROBLEM_RESPONSE})
def describe_problem(slug: str) -> dict[str, str | int]:
    problem_type = CATALOG.get(slug)
    if problem_type is None:
        raise StarletteHTTPException(status_code=404)
    return {
        "type": slug,
        "title": problem_type.title,
        "status": problem_type.status,
        "description": problem_type.description,
    }
