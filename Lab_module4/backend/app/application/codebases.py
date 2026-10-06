"""CodebaseService: list, inspect, delete, expire user codebases; rebuild BM25 and repair
the index at startup (§7.1, §7.3)."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from app.domain.chunks import Chunk
from app.domain.codebases import Codebase, CodebaseKind, FileRecord
from app.domain.errors import CodebaseNotFound, ReadOnlyCodebase
from app.domain.ports import IndexRepository, VectorStore

from .indexing import IndexingService
from .retrieval.bm25 import BM25Index

logger = logging.getLogger(__name__)


class CodebaseService:
    def __init__(
        self,
        repo: IndexRepository,
        store: VectorStore,
        bm25: BM25Index,
        indexing: IndexingService,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repo, self._store, self._bm25 = repo, store, bm25
        self._indexing, self._clock = indexing, clock

    def all(self) -> list[Codebase]:
        return sorted(self._repo.list_codebases(), key=lambda c: (c.kind.value != "sample", c.id))

    def get(self, codebase: str) -> Codebase:
        record = self._repo.get_codebase(codebase)
        if record is None:
            raise CodebaseNotFound(codebase)
        return record

    def files(self, codebase: str) -> list[FileRecord]:
        self.get(codebase)
        return sorted(self._repo.files(codebase), key=lambda f: f.path)

    def chunks(self, codebase: str, path: str) -> list[Chunk]:
        self.get(codebase)
        return sorted(self._store.iter_chunks(codebase, path), key=lambda c: c.start_line)

    def delete(self, codebase: str, allow_samples: bool = False) -> None:
        record = self.get(codebase)
        if record.read_only and not allow_samples:
            raise ReadOnlyCodebase(codebase)
        self._store.delete_codebase(codebase)
        self._bm25.remove_codebase(codebase)
        self._repo.delete_codebase(codebase)

    def sweep_expired(self) -> list[str]:
        """Delete user codebases past their expiry (samples never expire)."""
        now = self._clock()
        expired = [
            c.id
            for c in self._repo.list_codebases()
            if c.kind is CodebaseKind.USER
            and c.expires_at
            and datetime.fromisoformat(c.expires_at) <= now
        ]
        for codebase in expired:
            self.delete(codebase)
            logger.info("expired codebase=%s", codebase)
        return expired

    def rebuild_keyword_index(self) -> int:
        count = 0
        for chunk in self._store.iter_chunks():
            self._bm25.add(chunk.id, chunk.codebase, chunk.embed_text, chunk.path)
            count += 1
        return count

    def reconcile(self) -> list[str]:
        """After a crash between the vector store and SQLite, a file's record and its stored
        chunks can disagree. Such files are dropped, so their next index redoes them."""
        repaired = []
        for codebase in self._repo.list_codebases():
            records = self._repo.files(codebase.id)
            for record in records:  # per file: opposite errors could cancel out in a total
                stored = sum(1 for _ in self._store.iter_chunks(codebase.id, record.path))
                if stored != record.chunk_count:
                    self._store.delete_file(codebase.id, record.path)
                    self._repo.delete_file(codebase.id, record.path)
                    repaired.append(f"{codebase.id}/{record.path}")
            known = {r.path for r in records}
            orphans = {c.path for c in self._store.iter_chunks(codebase.id)} - known
            for path in sorted(orphans):  # chunks written, record never saved
                self._store.delete_file(codebase.id, path)
                repaired.append(f"{codebase.id}/{path}")
            self._indexing.refresh_stats(codebase.id)
        return repaired
