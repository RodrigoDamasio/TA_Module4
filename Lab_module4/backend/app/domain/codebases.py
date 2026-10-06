"""Codebases (extension: multiple codebases) and the per-file index records."""

import re
from dataclasses import dataclass, field
from enum import StrEnum

from .errors import InvalidPath
from .files import Language

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


class CodebaseKind(StrEnum):
    SAMPLE = "sample"  # shipped with the app, read-only
    USER = "user"  # uploaded, expires


def validate_codebase_id(value: str) -> str:
    if not _SLUG.match(value):
        raise InvalidPath(
            "Codebase ids are 1-40 characters: lowercase letters, digits and '-', "
            f"starting with a letter or digit (got '{value[:40]}').",
            pointer="#/codebase",
        )
    return value


@dataclass
class Codebase:
    id: str
    kind: CodebaseKind
    created_at: str
    updated_at: str
    expires_at: str | None = None
    file_count: int = 0
    chunk_count: int = 0
    bytes: int = 0
    languages: dict[str, int] = field(default_factory=dict)  # chunks per language

    @property
    def read_only(self) -> bool:
        return self.kind is CodebaseKind.SAMPLE


@dataclass(frozen=True)
class FileRecord:
    codebase: str
    path: str
    language: Language
    content_hash: str
    bytes: int
    chunk_count: int
    chunker_version: str
    fallback: bool  # parse failed → fixed-size chunks
    indexed_at: str
