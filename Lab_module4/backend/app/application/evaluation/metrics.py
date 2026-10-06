"""Retrieval metrics (course §5.2). Pure functions over ranked lists.

`relevant_flags[i]` is True when the i-th retrieved chunk overlaps any relevant target;
`targets_hit[t]` is the first rank (1-based) at which target t was hit, or None."""

import math


def precision_at_k(relevant_flags: list[bool], k: int) -> float:
    """Fraction of the top-k retrieved chunks that are relevant (denominator: k)."""
    return sum(relevant_flags[:k]) / k if k > 0 else 0.0


def recall_at_k(targets_hit: list[int | None], k: int) -> float:
    """Fraction of relevant targets hit by at least one chunk in the top k."""
    if not targets_hit:
        return 0.0
    return sum(1 for r in targets_hit if r is not None and r <= k) / len(targets_hit)


def reciprocal_rank(relevant_flags: list[bool]) -> float:
    """1 / rank of the first relevant chunk (0 when none is relevant)."""
    for i, flag in enumerate(relevant_flags):
        if flag:
            return 1.0 / (i + 1)
    return 0.0


def hit_at_k(relevant_flags: list[bool], k: int) -> float:
    return 1.0 if any(relevant_flags[:k]) else 0.0


def ndcg_at_k(relevant_flags: list[bool], k: int, n_relevant: int) -> float:
    """Binary-relevance nDCG@k. Several chunks can cover one target (a class and its split
    parts), so the ideal list holds max(targets, relevant chunks retrieved) relevant
    chunks, capped at k — the score stays within 0..1."""
    dcg = sum(1 / math.log2(i + 2) for i, flag in enumerate(relevant_flags[:k]) if flag)
    ideal_n = min(k, max(n_relevant, sum(relevant_flags[:k])))
    ideal = sum(1 / math.log2(i + 2) for i in range(ideal_n))
    return dcg / ideal if ideal > 0 else 0.0


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile (p in 0..100)."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(p / 100 * len(ordered)) - 1)
    return ordered[index]
