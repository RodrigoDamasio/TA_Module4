"""Cost and quota monitoring (course §6.3) for the free tier: real calls today vs the daily
limit, cache hit rate, tokens, a paid-tier equivalent, and latency percentiles per stage."""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.ports import EmbeddingCache, LLMClient, LLMRequest, LLMResponse, TraceStore

from .evaluation.metrics import percentile

PACIFIC = ZoneInfo("America/Los_Angeles")  # Gemini's daily quotas reset at midnight PT
STAGES = ("embed_query", "vector_search", "bm25", "fuse", "rerank", "generate")


class UsageMeter:
    """In-memory counters (reset on restart; the circuit breaker is the real quota guard)."""

    def __init__(self, clock: Callable[[], datetime] = lambda: datetime.now(PACIFIC)) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._day = ""
        self.real = self.cached = self.input_tokens = self.output_tokens = 0

    def record(self, response: LLMResponse) -> None:
        with self._lock:
            self._roll()
            if response.cached:
                self.cached += 1
            else:
                self.real += 1
                self.input_tokens += response.usage.input
                self.output_tokens += response.usage.output + response.usage.thinking

    def _roll(self) -> None:
        day = self._clock().date().isoformat()
        if day != self._day:
            self._day = day
            self.real = self.cached = self.input_tokens = self.output_tokens = 0

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            self._roll()
            return {
                "real": self.real,
                "cached": self.cached,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
            }


class MeteredLLMClient:
    """Outermost LLM wrapper: sees cache hits and real calls alike."""

    def __init__(self, inner: LLMClient, meter: UsageMeter) -> None:
        self._inner, self._meter = inner, meter

    def generate(self, request: LLMRequest) -> LLMResponse:
        response = self._inner.generate(request)
        self._meter.record(response)
        return response


@dataclass(frozen=True)
class Pricing:
    daily_request_limit: int = 1000
    input_per_million: float = 0.10
    output_per_million: float = 0.40


class StatsService:
    def __init__(
        self,
        traces: TraceStore,
        meter: UsageMeter,
        embedding_cache: EmbeddingCache,
        index_totals: Callable[[], dict[str, int]],
        quota_status: Callable[[], dict[str, Any]],
        pricing: Pricing,
        retention: int,
    ) -> None:
        self._traces, self._meter, self._cache = traces, meter, embedding_cache
        self._index_totals, self._quota, self._pricing = index_totals, quota_status, pricing
        self._retention = retention

    def stats(self) -> dict[str, Any]:
        traces = self._traces.recent(self._retention)
        counts: dict[str, int] = {}
        for t in traces:
            counts[t.kind] = counts.get(t.kind, 0) + 1
        latency: dict[str, dict[str, float | None]] = {}
        queries = [t for t in traces if t.kind in ("query", "search")]
        totals = [t.total_ms for t in queries]
        latency["total"] = _p50_p95(totals)
        for stage in STAGES:
            values = [s.ms for t in queries for s in t.spans if s.name == stage]
            if values:
                latency[stage] = _p50_p95(values)
        usage = self._meter.snapshot()
        calls = usage["real"] + usage["cached"]
        p = self._pricing
        cost = (
            usage["input_tokens"] * p.input_per_million
            + usage["output_tokens"] * p.output_per_million
        ) / 1_000_000
        cache = self._cache.stats()
        lookups = cache["hits"] + cache["misses"]
        return {
            "window": f"last {len(traces)} requests (max {self._retention})",
            "requests": counts,
            "latency_ms": latency,
            "llm": {
                "calls_today": usage["real"],
                "cached_today": usage["cached"],
                "cache_hit_rate": round(usage["cached"] / calls, 3) if calls else None,
                "daily_limit": p.daily_request_limit,
                "left_today": max(0, p.daily_request_limit - usage["real"]),
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "paid_equivalent_usd": round(cost, 6),
            },
            "index": {
                **self._index_totals(),
                "embeddings_cached": cache["stored"],
                "embedding_cache_hit_rate": round(cache["hits"] / lookups, 3) if lookups else None,
            },
            "quota": self._quota(),
        }


def _p50_p95(values: list[float]) -> dict[str, float | None]:
    p50, p95 = percentile(values, 50), percentile(values, 95)
    return {
        "p50": round(p50, 1) if p50 is not None else None,
        "p95": round(p95, 1) if p95 is not None else None,
    }
