"""Pydantic models for LLM output: lenient twins (sent to Gemini) + strict models (validated
locally). Same approach as Labs 2-3 — Gemini accepts only a subset of JSON Schema."""

from pydantic import BaseModel, Field

# ---- answer ------------------------------------------------------------------------


class AnswerLLM(BaseModel):
    answer: str = Field(
        description="Markdown answer. Put the excerpt marker right after each claim, inside "
        "this text, e.g. 'Tokens are signed with JWT_SECRET [2].'"
    )
    found: bool = Field(description="false when the excerpts do not contain the answer")
    citations: list[int] = Field(description="every excerpt number used as [n] in the answer")


class AnswerOut(BaseModel):
    answer: str = Field(min_length=1, max_length=6000)
    found: bool
    citations: list[int] = Field(max_length=10)


# ---- judge (course §5.3, three rubrics in one call) -----------------------------------


class ScoreLLM(BaseModel):
    score: int
    reason: str


class JudgeLLM(BaseModel):
    faithfulness: ScoreLLM
    relevance: ScoreLLM
    correctness: ScoreLLM


class ScoreOut(BaseModel):
    score: int = Field(ge=1, le=5)
    reason: str = Field(min_length=1, max_length=600)


class JudgeOut(BaseModel):
    faithfulness: ScoreOut
    relevance: ScoreOut
    correctness: ScoreOut
