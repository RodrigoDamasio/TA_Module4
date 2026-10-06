"""Rebuild the sample snapshot (chunks + vectors of both sample codebases) — 0 API calls.

python -m eval.build_snapshot            # default model (EMBED_MODEL)
EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2 python -m eval.build_snapshot
"""

from app.chunking.registry import ChunkerRegistry
from app.infrastructure.samples import build_snapshot, snapshot_path

from .common import eval_settings, load_models


def main() -> None:
    settings = eval_settings()
    models = load_models(settings, rerank_model="")
    embedder = models.embedder()
    path = snapshot_path(embedder.name)
    chunks = build_snapshot(
        embedder,
        ChunkerRegistry(settings.chunk_max_chars, settings.chunk_overlap, settings.chunk_min_chars),
        path,
    )
    size = path.stat().st_size
    print(f"wrote {path.relative_to(path.parents[2])}: {chunks} chunks, {size:,} bytes")


if __name__ == "__main__":
    main()
