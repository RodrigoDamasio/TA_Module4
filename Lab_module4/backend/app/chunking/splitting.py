"""Shared last step of every chunker: packing, header, oversize split, ids (§6).

Chunkers produce `Draft`s (a logical unit with exact lines). `finalize` turns them into
`Chunk`s:
  1. small neighbouring units of the same scope are packed up to `min_chars` (course §2.3:
     chunks of 200-1000 tokens; a 2-line class or an import block alone is noise),
  2. every chunk gets its context header,
  3. units over `max_chars` are split into overlapping windows, so the embedding model never
     silently truncates a chunk (course §3 pitfall)."""

from dataclasses import dataclass, field

from app.domain.chunks import Chunk, ChunkKind, chunk_id, sha256
from app.domain.files import Language


@dataclass
class Draft:
    kind: ChunkKind
    start_line: int  # 1-based, inclusive
    end_line: int
    symbol: str | None = None
    signature: str | None = None
    context: list[str] = field(default_factory=list)  # header parts after the file name
    scope: str = ""  # owning class ("" = module level): packing never crosses scopes


@dataclass(frozen=True)
class SplitOptions:
    max_chars: int = 1400
    overlap: float = 0.15
    header: bool = True
    min_chars: int = 0  # pack smaller units with their neighbours (0 = never)


HEADER_ROOM = 250  # a packed chunk's header lists several signatures


def _size(draft: Draft, lines: list[str]) -> int:
    return sum(len(line) + 1 for line in lines[draft.start_line - 1 : draft.end_line])


def pack(drafts: list[Draft], lines: list[str], min_chars: int, max_chars: int) -> list[Draft]:
    """Greedy: a unit joins the previous group when either is still under `min_chars`, both
    share a scope, and the result fits in `max_chars`."""
    if min_chars <= 0:
        return drafts
    groups: list[list[Draft]] = []
    sizes: list[int] = []
    for draft in sorted(drafts, key=lambda d: (d.start_line, d.end_line)):
        size = _size(draft, lines)
        if (
            groups
            and groups[-1][-1].scope == draft.scope
            and (sizes[-1] < min_chars or size < min_chars)
            and sizes[-1] + size + HEADER_ROOM <= max_chars
        ):
            groups[-1].append(draft)
            sizes[-1] += size
        else:
            groups.append([draft])
            sizes.append(size)
    return [_merge(group) for group in groups]


def _merge(group: list[Draft]) -> Draft:
    if len(group) == 1:
        return group[0]
    main = max(group, key=lambda d: d.end_line - d.start_line)
    symbols = [d.symbol for d in group if d.symbol]
    shared = group[0].context[:1] if group[0].scope else []
    labels = list(dict.fromkeys(d.context[-1] for d in group if d.context))
    labels = [x for x in labels if x not in shared]
    return Draft(
        kind=main.kind,
        start_line=group[0].start_line,
        end_line=max(d.end_line for d in group),
        symbol=", ".join(dict.fromkeys(symbols)) or None,
        signature=main.signature if len([d for d in group if d.signature]) == 1 else None,
        context=[*shared, *labels],
        scope=group[0].scope,
    )


def make_header(path: str, context: list[str]) -> str:
    return " · ".join([f"# file: {path}", *context])


def windows(lines: list[str], budget: int, overlap: float) -> list[tuple[int, int]]:
    """Line-aligned windows (0-based, end exclusive) of at most `budget` chars, overlapping
    by ~`overlap` of the previous window's lines. A single over-long line is its own window
    (it is cut later)."""
    spans: list[tuple[int, int]] = []
    start = 0
    while start < len(lines):
        end, size = start, 0
        while end < len(lines) and (end == start or size + len(lines[end]) + 1 <= budget):
            size += len(lines[end]) + 1
            end += 1
        spans.append((start, end))
        if end >= len(lines):
            break
        back = int((end - start) * overlap)
        start = max(end - back, start + 1)
    return spans


def finalize(
    codebase: str,
    path: str,
    language: Language,
    source_lines: list[str],
    drafts: list[Draft],
    options: SplitOptions,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    packed = pack(drafts, source_lines, options.min_chars, options.max_chars)
    for draft in sorted(packed, key=lambda d: (d.start_line, d.end_line)):
        body = source_lines[draft.start_line - 1 : draft.end_line]
        if not any(line.strip() for line in body):
            continue
        header = make_header(path, draft.context) if options.header else ""
        code = "\n".join(body)
        if len(header) + 1 + len(code) <= options.max_chars:
            chunks.append(_chunk(codebase, path, language, draft, draft.start_line, code, header))
            continue
        budget = max(200, options.max_chars - len(header) - 16)  # room for " (part i/n)"
        spans = windows(body, budget, options.overlap)
        for i, (s, e) in enumerate(spans, 1):
            part_code = "\n".join(body[s:e])[:budget]
            part_header = f"{header} (part {i}/{len(spans)})" if header else ""
            chunks.append(
                _chunk(
                    codebase,
                    path,
                    language,
                    draft,
                    draft.start_line + s,
                    part_code,
                    part_header,
                    end_line=draft.start_line + e - 1,
                    part=(i, len(spans)),
                )
            )
    return chunks


def _chunk(
    codebase: str,
    path: str,
    language: Language,
    draft: Draft,
    start: int,
    code: str,
    header: str,
    end_line: int | None = None,
    part: tuple[int, int] | None = None,
) -> Chunk:
    end = end_line if end_line is not None else draft.end_line
    digest = sha256(header + "\n" + code)
    return Chunk(
        id=chunk_id(codebase, path, start, end, digest),
        codebase=codebase,
        path=path,
        language=language,
        kind=draft.kind,
        symbol=draft.symbol,
        signature=draft.signature,
        start_line=start,
        end_line=end,
        code=code,
        header=header,
        part=part,
        content_hash=digest,
    )


def uncovered_blocks(
    first: int, last: int, covered: list[tuple[int, int]], lines: list[str]
) -> list[tuple[int, int]]:
    """Contiguous runs of lines in [first, last] not inside any covered range, trimmed of
    blank lines at both ends. Blank-only runs are dropped."""
    taken = set()
    for s, e in covered:
        taken.update(range(s, e + 1))
    blocks: list[tuple[int, int]] = []
    run: list[int] = []
    for n in range(first, last + 1):
        if n in taken:
            if run:
                blocks.append((run[0], run[-1]))
                run = []
        else:
            run.append(n)
    if run:
        blocks.append((run[0], run[-1]))
    trimmed = []
    for s, e in blocks:
        while s <= e and not lines[s - 1].strip():
            s += 1
        while e >= s and not lines[e - 1].strip():
            e -= 1
        if s <= e:
            trimmed.append((s, e))
    return trimmed
