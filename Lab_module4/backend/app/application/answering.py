"""AnswerService (§8.4): retrieve → build the numbered context → one Gemini call →
validate the schema and the citations (one repair) → answer + sources + debug pipeline."""

from dataclasses import dataclass

from app.domain.answers import Answer, citation_errors
from app.domain.retrieval import SearchHit, SearchMode, SearchResult
from app.domain.schemas import AnswerLLM, AnswerOut
from app.domain.tracing import PipelineDebug, PromptDebug

from .prompts import PromptLibrary, estimate_tokens, render_excerpt
from .retrieval.retriever import Retriever
from .structured import StructuredCaller
from .tracing import Tracer

NO_EXCERPTS = (
    "No indexed code matched this question, so there is nothing to answer from. "
    "Try other words, another search mode, or another codebase."
)


@dataclass(frozen=True)
class AnswerSettings:
    context_budget_tokens: int = 6000
    max_output_tokens: int = 1500


def build_context(hits: list[SearchHit], budget_tokens: int) -> tuple[list[SearchHit], str]:
    """Hits in rank order (most relevant first, against "lost in the middle"), dropped
    from the end when the budget would be exceeded. Always keeps the first one."""
    kept: list[SearchHit] = []
    parts: list[str] = []
    used = 0
    for hit in hits:
        text = render_excerpt(len(kept) + 1, hit)
        cost = estimate_tokens(text)
        if kept and used + cost > budget_tokens:
            break
        kept.append(hit)
        parts.append(text)
        used += cost
    return kept, "\n\n".join(parts)


class AnswerService:
    def __init__(
        self,
        retriever: Retriever,
        caller: StructuredCaller,
        prompts: PromptLibrary,
        settings: AnswerSettings,
    ) -> None:
        self._retriever, self._caller = retriever, caller
        self._prompts, self._settings = prompts, settings

    def answer(
        self, question: str, codebases: list[str], k: int, mode: SearchMode, tracer: Tracer
    ) -> tuple[Answer, SearchResult, PipelineDebug]:
        result = self._retriever.search(question, codebases, k, mode, tracer)
        debug = PipelineDebug(question=question, retrieval=result.debug)
        if not result.hits:
            return Answer(NO_EXCERPTS, False, [], [], grounded=True, cached=True), result, debug
        return self.generate(question, result.hits, tracer, debug), result, debug

    def generate(
        self, question: str, hits: list[SearchHit], tracer: Tracer, debug: PipelineDebug
    ) -> Answer:
        with tracer.span("build_context") as s:
            sent, excerpts = build_context(hits, self._settings.context_budget_tokens)
            system = self._prompts.system()
            user = self._prompts.answer_task(question, excerpts)
            est = estimate_tokens(system) + estimate_tokens(user)
            s |= {"chunks": len(sent), "est_tokens": est, "dropped": len(hits) - len(sent)}
        debug.prompt = PromptDebug(
            system=system,
            user=user,
            prompt_version=self._prompts.version,
            est_tokens=est,
            chunks_sent=len(sent),
            chunks_dropped=len(hits) - len(sent),
        )
        k = len(sent)
        call = self._caller.call(
            system,
            user,
            AnswerLLM,
            AnswerOut,
            tracer,
            self._settings.max_output_tokens,
            check=lambda v: citation_errors(v.answer, v.found, v.citations, k),
        )
        debug.attempts = call.attempts
        debug.llm_cached = call.cached
        debug.input_tokens = call.usage.input
        debug.output_tokens = call.usage.output + call.usage.thinking
        value = call.value or call.last_valid
        assert value is not None  # noqa: S101 — StructuredCaller raises otherwise
        grounded = call.value is not None
        with tracer.span("validate") as s:
            s |= {"grounded": grounded, "citations": len(set(value.citations))}
        citations = sorted({n for n in value.citations if 1 <= n <= k})
        return Answer(
            text=value.answer,
            found=value.found,
            citations=citations,
            sources=sent,
            grounded=grounded,
            cached=call.cached,
            repaired=len(call.attempts) > 1,
        )
