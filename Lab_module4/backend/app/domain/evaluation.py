"""Evaluation dataset types (course §5.4)."""

from dataclasses import dataclass, field

CATEGORIES = (
    "symbol",
    "conceptual",
    "location",
    "multi_file",
    "cross_codebase",
    "unanswerable",
)


@dataclass(frozen=True)
class RelevantTarget:
    codebase: str
    path: str
    symbol: str | None = None
    lines: tuple[int, int] | None = None  # resolved from `symbol` by parsing the sample

    @property
    def label(self) -> str:
        return f"{self.codebase}/{self.path}" + (f"::{self.symbol}" if self.symbol else "")


@dataclass(frozen=True)
class EvalExample:
    id: str
    question: str
    codebases: list[str]
    category: str
    expected_answer: str
    relevant: list[RelevantTarget] = field(default_factory=list)
    must_mention: list[str] = field(default_factory=list)
    expect_found: bool = True
    forbidden: list[str] = field(default_factory=list)  # e.g. a planted-injection marker
