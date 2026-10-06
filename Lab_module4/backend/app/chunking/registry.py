"""Picks the chunker for a file (by language and strategy) and finalizes the chunks.

Strategies (compared in the evaluation grid, §9.3):
  code_aware             — structure-aware chunks + context header (the default)
  code_aware_no_header   — same chunks, no header
  fixed                  — line-aligned fixed-size windows, no header (course Strategy 1)
"""

from dataclasses import dataclass
from enum import StrEnum

from app.domain.chunks import Chunk, ChunkKind
from app.domain.files import Language, language_for

from .markdown import MarkdownChunker, sections
from .python_ast import PythonChunker
from .splitting import Draft, SplitOptions, finalize
from .typescript import TypeScriptChunker


class Strategy(StrEnum):
    CODE_AWARE = "code_aware"
    CODE_AWARE_NO_HEADER = "code_aware_no_header"
    FIXED = "fixed"


@dataclass(frozen=True)
class ChunkResult:
    chunks: list[Chunk]
    language: Language
    fallback: bool  # the parser failed; fixed-size windows were used


class ChunkerRegistry:
    def __init__(self, max_chars: int = 1400, overlap: float = 0.15, min_chars: int = 700) -> None:
        self._max, self._overlap, self._min = max_chars, overlap, min_chars
        self._python = PythonChunker(max_chars)
        self._typescript = TypeScriptChunker(max_chars)
        self._markdown = MarkdownChunker()

    def chunk(
        self, codebase: str, path: str, content: str, strategy: Strategy = Strategy.CODE_AWARE
    ) -> ChunkResult:
        language = language_for(path) or Language.TEXT
        lines = content.splitlines()
        drafts: list[Draft] | None = None
        if strategy is not Strategy.FIXED:
            if language is Language.PYTHON:
                drafts = self._python.drafts(content)
            elif language in (Language.TYPESCRIPT, Language.JAVASCRIPT):
                drafts = self._typescript.drafts(path, content)
            elif language is Language.MARKDOWN:
                drafts = self._markdown.drafts(path, content)
        structured = language is not Language.TEXT and strategy is not Strategy.FIXED
        fallback = structured and drafts is None
        if drafts is None:
            drafts = [Draft(ChunkKind.WINDOW, 1, max(len(lines), 1), None, None, [])]
        options = SplitOptions(
            max_chars=self._max,
            overlap=self._overlap,
            header=strategy is Strategy.CODE_AWARE,
            min_chars=0 if strategy is Strategy.FIXED else self._min,
        )
        return ChunkResult(finalize(codebase, path, language, lines, drafts, options), language,
                           fallback)  # fmt: skip


def locate_symbols(path: str, content: str) -> dict[str, tuple[int, int]]:
    """Every symbol of a file → its full line range, independent of chunk size.

    Used by the evaluation to turn ground truth (`path + symbol`) into line ranges: a class
    maps to its whole body and each method gets its own entry (`Class.method`)."""
    language = language_for(path)
    found: dict[str, tuple[int, int]] = {}

    def add(symbol: str | None, start: int, end: int) -> None:
        if symbol:
            s, e = found.get(symbol, (start, end))
            found[symbol] = (min(s, start), max(e, end))

    if language is Language.MARKDOWN:
        for s, e, title in sections(path, content.splitlines()):
            add(title, s, e)
        return found
    # Two passes: whole classes (huge limit) and split classes (limit 0, so methods appear).
    for limit in (10**9, 0):
        drafts: list[Draft] | None = None
        if language is Language.PYTHON:
            drafts = PythonChunker(limit).drafts(content)
        elif language in (Language.TYPESCRIPT, Language.JAVASCRIPT):
            drafts = TypeScriptChunker(limit).drafts(path, content)
        for d in drafts or []:
            add(d.symbol, d.start_line, d.end_line)
    return found
