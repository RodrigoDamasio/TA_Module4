"""Markdown chunker (§6.3): one chunk per heading section, keeping the heading path."""

import re
from pathlib import PurePosixPath

from app.domain.chunks import ChunkKind

from .splitting import Draft

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
MIN_SECTION_CHARS = 200


def sections(path: str, lines: list[str]) -> list[tuple[int, int, str]]:
    """(start, end, heading path) — 1-based, inclusive."""
    found: list[tuple[int, list[str]]] = []
    stack: list[tuple[int, str]] = []
    in_fence = False
    for n, line in enumerate(lines, 1):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        match = None if in_fence else _HEADING.match(line)
        if match:
            level, title = len(match.group(1)), match.group(2)
            stack = [(lv, t) for lv, t in stack if lv < level] + [(level, title)]
            found.append((n, [t for _, t in stack]))
    result: list[tuple[int, int, str]] = []
    if not found or found[0][0] > 1:
        first_end = (found[0][0] - 1) if found else len(lines)
        result.append((1, first_end, PurePosixPath(path).name))
    for i, (start, heading_path) in enumerate(found):
        end = found[i + 1][0] - 1 if i + 1 < len(found) else len(lines)
        result.append((start, end, " > ".join(heading_path)))
    return result


def merge_small(found: list[tuple[int, int, str]], lines: list[str]) -> list[tuple[int, int, str]]:
    """A tiny section (a title with one line) merges into the next one."""
    merged: list[tuple[int, int, str]] = []
    carry: int | None = None
    for i, (start, end, title) in enumerate(found):
        size = sum(len(line) + 1 for line in lines[start - 1 : end])
        if size < MIN_SECTION_CHARS and i + 1 < len(found):
            carry = carry or start
            continue
        merged.append((carry or start, end, title))
        carry = None
    return merged


class MarkdownChunker:
    def drafts(self, path: str, content: str) -> list[Draft]:
        lines = content.splitlines()
        return [
            Draft(ChunkKind.SECTION, s, e, title, None, [f"section: {title}"])
            for s, e, title in merge_small(sections(path, lines), lines)
        ]
