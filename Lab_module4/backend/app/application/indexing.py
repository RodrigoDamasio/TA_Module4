"""IndexingService (§7.1): validate → hash-skip → chunk → embed (cached) → replace.

Order for crash safety: the vector store and BM25 are written before the file record. A
crash in between leaves the old hash, so the next index of that file simply redoes it
(delete-then-upsert is idempotent)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.chunking.registry import ChunkerRegistry, Strategy
from app.domain.chunks import CHUNKER_VERSION, Chunk, sha256
from app.domain.codebases import Codebase, CodebaseKind, FileRecord, validate_codebase_id
from app.domain.errors import (
    InputTooLarge,
    InvalidPath,
    ReadOnlyCodebase,
    TooManyCodebases,
    UnsupportedFileType,
)
from app.domain.files import Language, SourceFile, language_for, skip_reason, validate_path
from app.domain.ports import IndexRepository, VectorStore

from .embedding import CachedEmbeddings, Models
from .retrieval.bm25 import BM25Index

Progress = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class IndexLimits:
    max_files_per_request: int = 50
    max_bytes_per_request: int = 500_000
    max_files_per_codebase: int = 200
    max_bytes_per_codebase: int = 1_000_000
    max_user_codebases: int = 10
    ttl_hours: int = 24


def now_iso(clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> str:
    return clock().isoformat(timespec="seconds")


def size(text: str) -> int:
    return len(text.encode())


class IndexingService:
    def __init__(
        self,
        repo: IndexRepository,
        store: VectorStore,
        bm25: BM25Index,
        models: Models,
        embeddings: CachedEmbeddings,
        chunkers: ChunkerRegistry,
        limits: IndexLimits,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        strategy: Strategy = Strategy.CODE_AWARE,
    ) -> None:
        self._repo, self._store, self._bm25 = repo, store, bm25
        self._models, self._embeddings, self._chunkers = models, embeddings, chunkers
        self._limits, self._clock, self._strategy = limits, clock, strategy

    @property
    def repo(self) -> IndexRepository:
        return self._repo

    # ---- validation (before a job is created, so errors are synchronous 4xx) ------------

    def validate(
        self, codebase: str, files: list[SourceFile], kind: CodebaseKind = CodebaseKind.USER
    ) -> None:
        validate_codebase_id(codebase)
        limits = self._limits
        if not files:
            raise InvalidPath("Send at least one file.")
        existing = self._repo.get_codebase(codebase)
        if existing is not None and existing.read_only and kind is CodebaseKind.USER:
            raise ReadOnlyCodebase(codebase)
        if existing is None and kind is CodebaseKind.USER:
            users = [c for c in self._repo.list_codebases() if c.kind is CodebaseKind.USER]
            if len(users) >= limits.max_user_codebases:
                raise TooManyCodebases(limits.max_user_codebases)
        if len(files) > limits.max_files_per_request:
            raise InputTooLarge(
                f"At most {limits.max_files_per_request} files per request (got {len(files)})."
            )
        total = sum(size(f.content) for f in files)
        if total > limits.max_bytes_per_request:
            raise InputTooLarge(
                f"At most {limits.max_bytes_per_request:,} bytes per request (got {total:,})."
            )
        paths = [validate_path(f.path) for f in files]
        if len(set(paths)) != len(paths):
            raise InvalidPath("Each file path may appear only once per request.")
        if len(files) == 1 and language_for(files[0].path) is None:
            raise UnsupportedFileType(
                f"'{files[0].path}' is not a supported file type (Python, TypeScript, "
                "JavaScript, Markdown, or common text/config files)."
            )
        if kind is CodebaseKind.USER:
            current = {r.path: r.bytes for r in self._repo.files(codebase)}
            current |= {f.path: size(f.content) for f in files}
            if len(current) > limits.max_files_per_codebase:
                raise InputTooLarge(
                    f"A codebase holds at most {limits.max_files_per_codebase} files."
                )
            if sum(current.values()) > limits.max_bytes_per_codebase:
                raise InputTooLarge(
                    f"A codebase holds at most {limits.max_bytes_per_codebase:,} bytes."
                )

    # ---- indexing ---------------------------------------------------------------------

    def index(
        self,
        codebase: str,
        files: list[SourceFile],
        kind: CodebaseKind = CodebaseKind.USER,
        progress: Progress | None = None,
    ) -> dict[str, Any]:
        started = self._clock()
        self.ensure_codebase(codebase, kind)
        embedder = self._models.embedder()
        result: dict[str, Any] = {
            "codebase": codebase,
            "files_indexed": 0,
            "files_unchanged": 0,
            "skipped": [],
            "chunks_added": 0,
            "chunks_removed": 0,
            "by_language": {},
            "embedding_cache_hits": 0,
            "fallbacks": [],
        }
        for n, file in enumerate(files, 1):
            reason = skip_reason(file.path, file.content)
            if reason is not None:
                result["skipped"].append({"path": file.path, "reason": reason})
            else:
                digest = sha256(file.content)
                record = self._repo.get_file(codebase, file.path)
                if (
                    record is not None
                    and record.content_hash == digest
                    and record.chunker_version == CHUNKER_VERSION
                ):
                    result["files_unchanged"] += 1
                else:
                    chunked = self._chunkers.chunk(
                        codebase, file.path, file.content, self._strategy
                    )
                    vectors, hits = self._embeddings.documents(
                        embedder, [c.embed_text for c in chunked.chunks]
                    )
                    removed = self.store_file(
                        codebase, file.path, digest, size(file.content), chunked.language.value,
                        chunked.chunks, vectors, chunked.fallback,
                    )  # fmt: skip
                    result["files_indexed"] += 1
                    result["chunks_added"] += len(chunked.chunks)
                    result["chunks_removed"] += removed
                    result["embedding_cache_hits"] += hits
                    lang = chunked.language.value
                    result["by_language"][lang] = result["by_language"].get(lang, 0) + len(
                        chunked.chunks
                    )
                    if chunked.fallback:
                        result["fallbacks"].append(file.path)
            if progress is not None:
                progress(
                    {
                        "files_done": n,
                        "files_total": len(files),
                        "chunks": result["chunks_added"],
                        "cache_hits": result["embedding_cache_hits"],
                    }
                )
        self.refresh_stats(codebase)
        result["duration_ms"] = round((self._clock() - started).total_seconds() * 1000)
        return result

    def store_file(
        self,
        codebase: str,
        path: str,
        digest: str,
        nbytes: int,
        language: str,
        chunks: list[Chunk],
        vectors: list[list[float]],
        fallback: bool,
    ) -> int:
        """Replace one file's chunks everywhere, then write its record. Returns how many old
        chunks were removed."""
        removed = self._store.delete_file(codebase, path)
        self._bm25.remove_file(codebase, path)
        if chunks:
            self._store.upsert(chunks, vectors)
            for c in chunks:
                self._bm25.add(c.id, codebase, c.embed_text, path)
        self._repo.save_file(
            FileRecord(
                codebase=codebase,
                path=path,
                language=Language(language),
                content_hash=digest,
                bytes=nbytes,
                chunk_count=len(chunks),
                chunker_version=CHUNKER_VERSION,
                fallback=fallback,
                indexed_at=now_iso(self._clock),
            )
        )
        return removed

    def ensure_codebase(self, codebase: str, kind: CodebaseKind) -> Codebase:
        existing = self._repo.get_codebase(codebase)
        if existing is not None:
            return existing
        now = self._clock()
        expires = (
            (now + timedelta(hours=self._limits.ttl_hours)).isoformat(timespec="seconds")
            if kind is CodebaseKind.USER
            else None
        )
        record = Codebase(codebase, kind, now_iso(self._clock), now_iso(self._clock), expires)
        self._repo.save_codebase(record)
        return record

    def refresh_stats(self, codebase: str) -> Codebase | None:
        record = self._repo.get_codebase(codebase)
        if record is None:
            return None
        files = self._repo.files(codebase)
        record.file_count = len(files)
        record.chunk_count = sum(f.chunk_count for f in files)
        record.bytes = sum(f.bytes for f in files)
        languages: dict[str, int] = {}
        for f in files:
            languages[f.language.value] = languages.get(f.language.value, 0) + f.chunk_count
        record.languages = languages
        record.updated_at = now_iso(self._clock)
        self._repo.save_codebase(record)
        return record
