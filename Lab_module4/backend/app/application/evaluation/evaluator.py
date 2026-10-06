"""Evaluation runs (§9): retrieval (0 calls, deterministic) and full (answers + judge,
plus deterministic answer checks and the judge sanity check)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.domain.chunks import CHUNKER_VERSION
from app.domain.errors import BudgetExceeded, LLMError, LLMQuotaExceeded
from app.domain.evaluation import EvalExample
from app.domain.retrieval import SearchHit, SearchMode
from app.domain.tracing import PipelineDebug

from ..answering import AnswerService, build_context
from ..budget import CallBudget
from ..retrieval.retriever import Retriever
from ..tracing import Tracer
from .judge import CRITERIA, LLMJudge
from .metrics import hit_at_k, mean, ndcg_at_k, percentile, precision_at_k, recall_at_k
from .metrics import reciprocal_rank as rr
from .relevance import judge_ranking

RETRIEVAL_METRICS = ("precision", "recall", "mrr", "hit", "ndcg")
Progress = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class RunConfig:
    k: int = 5
    mode: SearchMode = SearchMode.HYBRID_RERANK
    embedder: str = ""
    prompt_version: str = ""
    model: str = ""


def retrieval_row(example: EvalExample, hits: list[SearchHit], k: int) -> dict[str, Any]:
    chunks = [h.chunk for h in hits]
    flags, first_hit = judge_ranking(chunks, example.relevant)
    row: dict[str, Any] = {
        "id": example.id,
        "category": example.category,
        "question": example.question,
        "retrieved": [
            {
                "rank": h.rank,
                "codebase": h.chunk.codebase,
                "path": h.chunk.path,
                "symbol": h.chunk.symbol,
                "lines": [h.chunk.start_line, h.chunk.end_line],
                "relevant": flag,
            }
            for h, flag in zip(hits, flags, strict=True)
        ],
        "targets": [
            {"target": t.label, "first_rank": r}
            for t, r in zip(example.relevant, first_hit, strict=True)
        ],
    }
    if example.relevant:  # unanswerable examples have nothing to find
        row["metrics"] = {
            "precision": precision_at_k(flags, k),
            "recall": recall_at_k(first_hit, k),
            "mrr": rr(flags),
            "hit": hit_at_k(flags, k),
            "ndcg": ndcg_at_k(flags, k, len(example.relevant)),
        }
    return row


def summarize(rows: list[dict[str, Any]], names: tuple[str, ...], key: str) -> dict[str, Any]:
    """Averages overall and per category of rows[i][key][name] (rows without it skipped)."""

    def averages(subset: list[dict[str, Any]]) -> dict[str, float | None]:
        scored = [r[key] for r in subset if r.get(key)]
        return {n: _round(mean([s[n] for s in scored if s.get(n) is not None])) for n in names} | {
            "n": len(scored)
        }

    categories = sorted({r["category"] for r in rows})
    return {
        "overall": averages(rows),
        "by_category": {c: averages([r for r in rows if r["category"] == c]) for c in categories},
    }


def _round(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Evaluator:
    def __init__(
        self,
        retriever: Retriever,
        answers: AnswerService | None = None,
        judge: LLMJudge | None = None,
        budget: CallBudget | None = None,
    ) -> None:
        self._retriever, self._answers, self._judge = retriever, answers, judge
        self._budget = budget

    # ---- retrieval: 0 calls --------------------------------------------------------

    def retrieval(self, examples: list[EvalExample], config: RunConfig) -> dict[str, Any]:
        rows = []
        latencies = []
        for example in examples:
            tracer = Tracer("evaluate")
            result = self._retriever.search(
                example.question, example.codebases, config.k, config.mode, tracer
            )
            trace = tracer.finish()
            latencies.append(trace.total_ms)
            rows.append(retrieval_row(example, result.hits, config.k) | {"mode_used": result.mode})
        return {
            "kind": "retrieval",
            "created_at": now_iso(),
            "config": _config(config),
            "summary": {
                "retrieval": summarize(rows, RETRIEVAL_METRICS, "metrics"),
                "latency_ms": _latency(latencies),
                "n_examples": len(rows),
            },
            "examples": rows,
        }

    # ---- full: answers + judge ------------------------------------------------------

    def full(
        self,
        examples: list[EvalExample],
        config: RunConfig,
        bad_answers: list[dict[str, Any]] | None = None,
        progress: Progress | None = None,
    ) -> dict[str, Any]:
        assert self._answers is not None and self._judge is not None  # noqa: S101
        rows = []
        latencies = []
        for n, example in enumerate(examples, 1):
            row, ms = self._full_example(example, config)
            rows.append(row)
            if ms is not None:
                latencies.append(ms)
            if progress:
                progress({"examples_done": n, "examples_total": len(examples), **self._calls()})
        sanity = [self._sanity(b, examples, config) for b in bad_answers or []]
        checked = [r for r in rows if r.get("checks")]
        return {
            "kind": "full",
            "created_at": now_iso(),
            "config": _config(config),
            "summary": {
                "retrieval": summarize(rows, RETRIEVAL_METRICS, "metrics"),
                "generation": summarize(rows, CRITERIA, "judge_scores"),
                "checks": {
                    name: _rate([r["checks"][name] for r in checked if name in r["checks"]])
                    for name in ("citations_valid", "found_matches", "mentions_ok", "no_forbidden")
                },
                "judge_sanity": {
                    "passed": sum(1 for s in sanity if s.get("passed")),
                    "total": len(sanity),
                },
                "skipped": [
                    {"id": r["id"], "reason": r["skipped"]} for r in rows if "skipped" in r
                ],
                "latency_ms": _latency(latencies),
                "calls": self._calls(),
                "n_examples": len(rows),
            },
            "examples": rows,
            "judge_sanity": sanity,
        }

    def _calls(self) -> dict[str, int]:
        if self._budget is None:
            return {}
        return {"real_calls": self._budget.real, "cached_calls": self._budget.cached}

    def _full_example(
        self, example: EvalExample, config: RunConfig
    ) -> tuple[dict[str, Any], float | None]:
        assert self._answers is not None and self._judge is not None  # noqa: S101
        tracer = Tracer("evaluate")
        try:
            answer, result, _ = self._answers.answer(
                example.question, example.codebases, config.k, config.mode, tracer
            )
        except Exception as err:  # noqa: BLE001 — recorded per example
            return _skipped(example, err), None
        trace = tracer.finish()
        row = retrieval_row(example, result.hits, config.k)
        text = answer.text
        lowered = text.lower()
        row["answer"] = {
            "text": text,
            "found": answer.found,
            "citations": answer.citations,
            "grounded": answer.grounded,
            "cached": answer.cached,
        }
        row["checks"] = {
            "citations_valid": answer.grounded,
            "found_matches": answer.found == example.expect_found,
            "mentions_ok": all(m.lower() in lowered for m in example.must_mention),
            "no_forbidden": not any(f.lower() in lowered for f in example.forbidden),
        }
        row["missing_mentions"] = [m for m in example.must_mention if m.lower() not in lowered]
        if example.expect_found:
            _, excerpts = build_context(answer.sources, 10**6)
            try:
                grade = self._judge.grade(
                    example.question, example.expected_answer, excerpts, text, tracer
                )
                row["judge_scores"] = grade.scores
                row["judge_reasons"] = grade.reasons
            except Exception as err:  # noqa: BLE001
                row["skipped"] = _reason(err) + " (judge)"
        return row, trace.total_ms

    def _sanity(
        self, bad: dict[str, Any], examples: list[EvalExample], config: RunConfig
    ) -> dict[str, Any]:
        assert self._judge is not None  # noqa: S101
        example = next((e for e in examples if e.id == bad["example"]), None)
        out: dict[str, Any] = {"id": bad["id"], "kind": bad["kind"], "example": bad["example"]}
        if example is None:
            return out | {"skipped": "example not in this run"}
        tracer = Tracer("evaluate")
        try:
            result = self._retriever.search(
                example.question, example.codebases, config.k, config.mode, tracer
            )
            _, excerpts = build_context(result.hits, 10**6)
            grade = self._judge.grade(
                example.question, example.expected_answer, excerpts, bad["answer"], tracer
            )
        except Exception as err:  # noqa: BLE001
            return out | {"skipped": _reason(err)}
        expect = bad["expect"]
        misses = [
            name
            for name in CRITERIA
            if f"{name}_max" in expect and grade.scores[name] > expect[f"{name}_max"]
        ]
        return out | {"scores": grade.scores, "passed": not misses, "lenient_on": misses}


def _skipped(example: EvalExample, err: Exception) -> dict[str, Any]:
    return {
        "id": example.id,
        "category": example.category,
        "question": example.question,
        "skipped": _reason(err),
    }


def _reason(err: Exception) -> str:
    if isinstance(err, BudgetExceeded):
        return "budget"
    if isinstance(err, LLMQuotaExceeded):
        return "quota"
    if isinstance(err, LLMError):
        return f"llm-error: {type(err).__name__}"
    return f"error: {type(err).__name__}"


def _rate(values: list[bool]) -> dict[str, Any]:
    return {"passed": sum(values), "total": len(values)}


def _latency(values: list[float]) -> dict[str, float | None]:
    p50, p95 = percentile(values, 50), percentile(values, 95)
    return {
        "p50": round(p50, 1) if p50 is not None else None,
        "p95": round(p95, 1) if p95 is not None else None,
    }


def _config(config: RunConfig) -> dict[str, Any]:
    return {
        "k": config.k,
        "mode": config.mode.value,
        "embedder": config.embedder,
        "chunker_version": CHUNKER_VERSION,
        "prompt_version": config.prompt_version,
        "model": config.model,
    }


__all__ = ["Evaluator", "RunConfig", "PipelineDebug"]
