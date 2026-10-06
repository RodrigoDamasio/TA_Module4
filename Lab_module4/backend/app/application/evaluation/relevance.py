"""Ground truth: dataset loading, symbol → line range resolution, chunk ↔ target matching.

Targets name `codebase + path + symbol`; they are resolved to line ranges by parsing the
sample files, so the same dataset scores any chunking strategy (fixed-size chunks have no
symbols, but they have lines)."""

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from app.chunking.registry import locate_symbols
from app.domain.chunks import Chunk
from app.domain.evaluation import CATEGORIES, EvalExample, RelevantTarget


class DatasetError(ValueError):
    pass


def parse_examples(raw: list[dict]) -> list[EvalExample]:
    examples = []
    for item in raw:
        if item.get("category") not in CATEGORIES:
            raise DatasetError(f"{item.get('id')}: unknown category {item.get('category')!r}")
        examples.append(
            EvalExample(
                id=item["id"],
                question=item["question"],
                codebases=list(item["codebases"]),
                category=item["category"],
                expected_answer=item.get("expected_answer", ""),
                relevant=[
                    RelevantTarget(
                        t["codebase"],
                        t["path"],
                        t.get("symbol"),
                        tuple(t["lines"]) if t.get("lines") else None,
                    )
                    for t in item.get("relevant", [])
                ],
                must_mention=list(item.get("must_mention", [])),
                expect_found=bool(item.get("expect_found", True)),
                forbidden=list(item.get("forbidden", [])),
            )
        )
    ids = [e.id for e in examples]
    if len(ids) != len(set(ids)):
        raise DatasetError("Example ids must be unique.")
    return examples


def load_dataset(path: Path) -> list[EvalExample]:
    return parse_examples(json.loads(path.read_text()))


Located = tuple[dict[str, tuple[int, int]], int]  # (symbol → lines, number of lines)


def locate_in_content(path: str, content: str) -> Located:
    return locate_symbols(path, content), len(content.splitlines())


def locate_in_chunks(chunks: list[Chunk]) -> Located:
    """For codebases whose files are not on disk: symbols from the stored chunks. A packed
    chunk names several symbols ("AuthError, login"); a method also extends its class
    (`Cart.add` → `Cart`). Ranges are approximate: a packed chunk spans all its members."""
    found: dict[str, tuple[int, int]] = {}
    for c in chunks:
        if not c.symbol:
            continue
        names = [n.strip() for n in c.symbol.split(",")]
        names += [n.rsplit(".", 1)[0] for n in names if "." in n]
        for name in names:
            s, e = found.get(name, (c.start_line, c.end_line))
            found[name] = (min(s, c.start_line), max(e, c.end_line))
    return found, max((c.end_line for c in chunks), default=0)


def resolve(
    examples: list[EvalExample], locate: Callable[[str, str], Located | None]
) -> list[EvalExample]:
    """Fill `lines` for every target. `locate(codebase, path)` returns the file's symbols
    or None when unknown. Unknown files or symbols raise DatasetError — the dataset cannot
    drift from the code it describes."""
    cache: dict[tuple[str, str], Located | None] = {}
    resolved = []
    for example in examples:
        targets = []
        for t in example.relevant:
            if t.lines is not None:
                targets.append(t)
                continue
            key = (t.codebase, t.path)
            if key not in cache:
                cache[key] = locate(t.codebase, t.path)
            located = cache[key]
            if located is None:
                raise DatasetError(f"{example.id}: file not found {t.label}")
            symbols, n_lines = located
            if t.symbol is None:
                lines = (1, max(n_lines, 1))
            elif t.symbol in symbols:
                lines = symbols[t.symbol]
            else:
                raise DatasetError(f"{example.id}: symbol not found {t.label}")
            targets.append(replace(t, lines=lines))
        resolved.append(replace(example, relevant=targets))
    return resolved


def is_relevant(chunk: Chunk, target: RelevantTarget) -> bool:
    if chunk.codebase != target.codebase or chunk.path != target.path:
        return False
    start, end = target.lines or (1, 10**6)
    return chunk.overlaps(start, end)


def judge_ranking(
    chunks: list[Chunk], targets: list[RelevantTarget]
) -> tuple[list[bool], list[int | None]]:
    """(relevant flag per retrieved chunk, first rank hitting each target)."""
    flags = [any(is_relevant(c, t) for t in targets) for c in chunks]
    first_hit: list[int | None] = []
    for t in targets:
        rank = next((i + 1 for i, c in enumerate(chunks) if is_relevant(c, t)), None)
        first_hit.append(rank)
    return flags, first_hit
