"""Shared setup for the offline evaluation scripts (0 API calls unless stated)."""

import dataclasses
import logging
from pathlib import Path

from app.config import Settings, get_settings
from app.infrastructure.fastembed_models import OnnxModels

EVAL_DIR = Path(__file__).resolve().parent
EVAL_DB = EVAL_DIR / "eval.db"  # persistent caches: embeddings + LLM responses (git-ignored)
RESULTS = EVAL_DIR / "results"
BACKEND = EVAL_DIR.parent

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")


def eval_settings(**overrides) -> Settings:
    base = get_settings()
    defaults = {
        "database_path": str(EVAL_DB),
        "chroma_path": str(EVAL_DIR / "chroma"),
        "models_path": str(BACKEND / "models"),
        "runner_mode": "inline",
    }
    return dataclasses.replace(base, **(defaults | overrides))


def load_models(settings: Settings, rerank_model: str | None = None) -> OnnxModels:
    """Load the ONNX models synchronously (downloads ~150 MB the first time)."""
    models = OnnxModels(
        settings.embed_model,
        settings.rerank_model if rerank_model is None else rerank_model,
        settings.models_path,
        settings.onnx_threads,
        settings.embed_batch_size,
    )
    models.start()
    if not models.wait_ready(900):
        raise SystemExit("the embedding model did not load")
    models.wait_all(900)  # the reranker loads right after the embedder
    return models
