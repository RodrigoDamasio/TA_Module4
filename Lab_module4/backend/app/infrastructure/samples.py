"""Sample codebases (read-only, pre-indexed) and their snapshot (§7.5).

The snapshot holds the samples' chunks and vectors for one embedding model, so a server
start loads them in seconds instead of embedding ~110 chunks on a small CPU. It is rebuilt
with `python -m eval.build_snapshot` whenever the samples or the chunker change."""

import gzip
import json
import logging
import re
from pathlib import Path

from app.application.indexing import IndexingService, size
from app.chunking.registry import ChunkerRegistry
from app.domain.chunks import CHUNKER_VERSION, Chunk, sha256
from app.domain.codebases import CodebaseKind
from app.domain.files import SourceFile
from app.domain.ports import Embedder, IndexRepository

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
SAMPLES_DIR = ROOT / "samples" / "codebases"
SNAPSHOT_DIR = ROOT / "samples" / "snapshot"
SAMPLES = ("shopflow", "ledger")


def sample_files(codebase: str, root: Path = SAMPLES_DIR) -> list[SourceFile]:
    base = root / codebase
    return [
        SourceFile(p.relative_to(base).as_posix(), p.read_text())
        for p in sorted(base.rglob("*"))
        if p.is_file()
    ]


def read_sample(codebase: str, path: str, root: Path = SAMPLES_DIR) -> str | None:
    if codebase not in SAMPLES:
        return None
    file = (root / codebase / path).resolve()
    if not file.is_file() or not file.is_relative_to((root / codebase).resolve()):
        return None
    return file.read_text()


def snapshot_path(model: str, directory: Path = SNAPSHOT_DIR) -> Path:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", model).strip("-").lower()
    return directory / f"{slug}.jsonl.gz"


def build_snapshot(
    embedder: Embedder, chunkers: ChunkerRegistry, path: Path, root: Path = SAMPLES_DIR
) -> int:
    """Chunk and embed every sample file; one JSON line per file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with gzip.open(path, "wt") as out:
        for codebase in SAMPLES:
            for file in sample_files(codebase, root):
                result = chunkers.chunk(codebase, file.path, file.content)
                vectors = embedder.embed_documents([c.embed_text for c in result.chunks])
                out.write(
                    json.dumps(
                        {
                            "codebase": codebase,
                            "path": file.path,
                            "content_hash": sha256(file.content),
                            "bytes": size(file.content),
                            "language": result.language.value,
                            "fallback": result.fallback,
                            "chunker_version": CHUNKER_VERSION,
                            "model": embedder.name,
                            "chunks": [
                                {"id": c.id, "code": c.code, "meta": c.to_metadata()}
                                for c in result.chunks
                            ],
                            "vectors": [[round(x, 6) for x in v] for v in vectors],
                        }
                    )
                    + "\n"
                )
                count += len(result.chunks)
    return count


def samples_current(repo: IndexRepository, root: Path = SAMPLES_DIR) -> bool:
    for codebase in SAMPLES:
        files = {f.path: f for f in sample_files(codebase, root)}
        records = {r.path: r for r in repo.files(codebase)}
        if set(files) != set(records):
            return False
        for path, file in files.items():
            r = records[path]
            if r.content_hash != sha256(file.content) or r.chunker_version != CHUNKER_VERSION:
                return False
    return True


def ensure_samples(
    indexing: IndexingService,
    repo: IndexRepository,
    model: str,
    embed_now: bool,
    root: Path = SAMPLES_DIR,
    snapshot_dir: Path = SNAPSHOT_DIR,
) -> str:
    """Make sure both samples are indexed and current. Returns how: 'current', 'snapshot',
    'embedded', or 'pending' (no snapshot and the models are not ready yet)."""
    if samples_current(repo, root):
        return "current"
    snapshot = snapshot_path(model, snapshot_dir)
    if snapshot.is_file() and _load_snapshot(indexing, repo, snapshot, model, root):
        return "snapshot"
    if not embed_now:
        return "pending"
    for codebase in SAMPLES:
        files = sample_files(codebase, root)
        _drop_stale(indexing, repo, codebase, {f.path for f in files})
        indexing.index(codebase, files, CodebaseKind.SAMPLE)
    return "embedded"


def _drop_stale(indexing: IndexingService, repo: IndexRepository, codebase: str, keep: set[str]):
    for record in repo.files(codebase):
        if record.path not in keep:
            indexing.store_file(codebase, record.path, "", 0, record.language.value, [], [], False)
            repo.delete_file(codebase, record.path)


def _load_snapshot(
    indexing: IndexingService, repo: IndexRepository, snapshot: Path, model: str, root: Path
) -> bool:
    with gzip.open(snapshot, "rt") as handle:
        entries = [json.loads(line) for line in handle if line.strip()]
    current = {(cb, f.path): sha256(f.content) for cb in SAMPLES for f in sample_files(cb, root)}
    snap = {(e["codebase"], e["path"]): e for e in entries}
    stale = (
        set(current) != set(snap)
        or any(snap[k]["content_hash"] != h for k, h in current.items())
        or any(e["chunker_version"] != CHUNKER_VERSION or e["model"] != model for e in entries)
    )
    if stale:
        logger.warning("sample snapshot %s is stale; re-embedding instead", snapshot.name)
        return False
    for codebase in SAMPLES:
        indexing.ensure_codebase(codebase, CodebaseKind.SAMPLE)
        _drop_stale(indexing, repo, codebase, {p for cb, p in current if cb == codebase})
    for e in entries:
        chunks = [Chunk.from_metadata(c["id"], c["code"], c["meta"]) for c in e["chunks"]]
        indexing.store_file(
            e["codebase"], e["path"], e["content_hash"], e["bytes"], e["language"],
            chunks, e["vectors"], e["fallback"],
        )  # fmt: skip
    for codebase in SAMPLES:
        indexing.refresh_stats(codebase)
    return True
