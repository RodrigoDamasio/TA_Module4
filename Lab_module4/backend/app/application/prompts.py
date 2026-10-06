"""Prompt library (app/prompts, versioned by the VERSION file) — the Lab 2/3 loader."""

import math
import re
from functools import cache
from pathlib import Path

from app.domain.retrieval import SearchHit

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
PLACEHOLDERS = frozenset({"question", "excerpts", "expected_answer", "answer", "validation_errors"})
FENCE = "````"  # four backticks: excerpts (Markdown files) may contain ``` themselves


def fill(template: str, **values: object) -> str:
    """Replace only the given {placeholders}; other braces (JSON, code) stay as they are.
    One pass, so a value that contains '{question}' is never substituted again."""
    return _PLACEHOLDER.sub(
        lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), template
    )


def estimate_tokens(text: str) -> int:
    """~3.5 characters per token for code-heavy prompts (conservative for budgets)."""
    return math.ceil(len(text) / 3.5)


def render_excerpt(n: int, hit: SearchHit) -> str:
    c = hit.chunk
    label = f"[{n}] {c.codebase}/{c.path}:{c.start_line}-{c.end_line}"
    if c.symbol:
        label += f" · {c.symbol}"
    return f"{label}\n{FENCE}{c.language.value}\n{c.code}\n{FENCE}"


class PromptLibrary:
    def __init__(self, root: Path = PROMPTS_DIR) -> None:
        self._root = root

    @cache  # noqa: B019 — one library per process; files never change at runtime
    def _read(self, name: str) -> str:
        return (self._root / name).read_text().strip()

    @property
    def version(self) -> str:
        return self._read("VERSION")

    def system(self) -> str:
        return self._read("system.md")

    def answer_task(self, question: str, excerpts: str) -> str:
        return fill(self._read("answer_task.md"), question=question, excerpts=excerpts)

    def judge_system(self) -> str:
        return self._read("judge_system.md")

    def judge_task(self, question: str, expected_answer: str, excerpts: str, answer: str) -> str:
        return fill(
            self._read("judge_task.md"),
            question=question,
            expected_answer=expected_answer,
            excerpts=excerpts,
            answer=answer,
        )

    def repair(self, validation_errors: str) -> str:
        return fill(self._read("repair.md"), validation_errors=validation_errors)
