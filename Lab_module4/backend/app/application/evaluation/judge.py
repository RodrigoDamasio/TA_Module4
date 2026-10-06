"""LLM-as-judge (course §5.3): faithfulness, relevance and correctness in ONE call."""

from dataclasses import dataclass

from app.domain.schemas import JudgeLLM, JudgeOut

from ..prompts import PromptLibrary
from ..structured import StructuredCaller
from ..tracing import Tracer

CRITERIA = ("faithfulness", "relevance", "correctness")


@dataclass(frozen=True)
class Grade:
    scores: dict[str, int]
    reasons: dict[str, str]
    cached: bool


class LLMJudge:
    def __init__(self, caller: StructuredCaller, prompts: PromptLibrary) -> None:
        self._caller, self._prompts = caller, prompts

    def grade(
        self, question: str, expected: str, excerpts: str, answer: str, tracer: Tracer
    ) -> Grade:
        result = self._caller.call(
            self._prompts.judge_system(),
            self._prompts.judge_task(question, expected, excerpts or "(none)", answer),
            JudgeLLM,
            JudgeOut,
            tracer,
            max_output_tokens=600,
        )
        value = result.value or result.last_valid
        assert value is not None  # noqa: S101 — the caller raises otherwise
        return Grade(
            scores={c: getattr(value, c).score for c in CRITERIA},
            reasons={c: getattr(value, c).reason for c in CRITERIA},
            cached=result.cached,
        )
