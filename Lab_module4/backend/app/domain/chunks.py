"""Chunks: the unit that is embedded, searched, and shown as a source."""

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .files import Language

# Bump when chunking changes: stored files are then re-indexed (samples at startup).
CHUNKER_VERSION = "2"  # 2: small units packed to CHUNK_MIN_CHARS


class ChunkKind(StrEnum):
    MODULE = "module"  # imports / top-level code between definitions
    CLASS = "class"  # class, interface, type, enum, schema (or the header part of a big class)
    FUNCTION = "function"
    METHOD = "method"
    SECTION = "section"  # markdown
    WINDOW = "window"  # fixed-size text


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def chunk_id(codebase: str, path: str, start_line: int, end_line: int, digest: str) -> str:
    return sha256(f"{codebase}\0{path}\0{start_line}\0{end_line}\0{digest}")[:24]


@dataclass(frozen=True)
class Chunk:
    id: str
    codebase: str
    path: str
    language: Language
    kind: ChunkKind
    symbol: str | None  # "AuthService.login", "processOrder", "README > Setup"
    signature: str | None
    start_line: int  # 1-based, inclusive
    end_line: int
    code: str  # what the UI and the prompt show
    header: str  # context line, embedded and indexed with the code ("" = no header)
    part: tuple[int, int] | None = None  # (2, 3) when a long unit was split
    content_hash: str = ""

    @property
    def embed_text(self) -> str:
        return f"{self.header}\n{self.code}" if self.header else self.code

    @property
    def location(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"

    def overlaps(self, start: int, end: int) -> bool:
        return self.start_line <= end and start <= self.end_line

    def to_metadata(self) -> dict[str, Any]:
        """Flat scalars only (vector stores reject lists and None)."""
        data: dict[str, Any] = {
            "codebase": self.codebase,
            "path": self.path,
            "language": self.language.value,
            "kind": self.kind.value,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "content_hash": self.content_hash,
            "header": self.header,
            "chunker_version": CHUNKER_VERSION,
        }
        if self.symbol:
            data["symbol"] = self.symbol
        if self.signature:
            data["signature"] = self.signature
        if self.part:
            data["part"] = f"{self.part[0]}/{self.part[1]}"
        return data

    @classmethod
    def from_metadata(cls, chunk_id_: str, code: str, meta: dict[str, Any]) -> "Chunk":
        part = None
        if "part" in meta:
            i, n = str(meta["part"]).split("/")
            part = (int(i), int(n))
        return cls(
            id=chunk_id_,
            codebase=str(meta["codebase"]),
            path=str(meta["path"]),
            language=Language(meta["language"]),
            kind=ChunkKind(meta["kind"]),
            symbol=meta.get("symbol"),
            signature=meta.get("signature"),
            start_line=int(meta["start_line"]),
            end_line=int(meta["end_line"]),
            code=code,
            header=str(meta.get("header", "")),
            part=part,
            content_hash=str(meta.get("content_hash", "")),
        )
