"""Answers and the deterministic citation rules (§8.4)."""

import re
from dataclasses import dataclass

from .retrieval import SearchHit

# "[2]", and the grouped forms models also write: "[1, 2]", "[1,3]"
_MARKER = re.compile(r"\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]")


def cited_numbers(text: str) -> set[int]:
    return {int(n) for group in _MARKER.findall(text) for n in group.split(",")}


def citation_errors(answer: str, found: bool, citations: list[int], k: int) -> list[str]:
    """Empty list = grounded. Every [n] must exist; markers in the text, when present, must
    equal `citations`; a found answer must cite something. An answer whose text has no
    markers but a valid `citations` list is accepted: a repair call for a cosmetic omission
    would double the cost of the question (seen in the first real run)."""
    errors: list[str] = []
    in_text = cited_numbers(answer)
    listed = set(citations)
    for n in sorted((in_text | listed) - set(range(1, k + 1))):
        errors.append(f"[{n}] does not exist: only excerpts [1]..[{k}] were provided.")
    if in_text and in_text != listed:
        errors.append(
            f'The [n] markers in "answer" ({sorted(in_text)}) must equal "citations" '
            f"({sorted(listed)})."
        )
    if found and not listed:
        errors.append('"found" is true, so cite at least one excerpt as [n].')
    return errors


@dataclass(frozen=True)
class Answer:
    text: str
    found: bool
    citations: list[int]
    sources: list[SearchHit]
    grounded: bool
    cached: bool = False
    repaired: bool = False
