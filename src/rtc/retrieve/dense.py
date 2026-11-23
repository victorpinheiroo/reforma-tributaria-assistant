"""Dense retrieval with a local multilingual embedding model (CPU), cached to disk.

The store is a numpy matrix behind a two-method interface; for a few thousand chunks that is
exact, deterministic and dependency-light. A Chroma (or Databricks Vector Search) store can
implement the same interface.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np

EMBED_MODEL = os.environ.get("RTC_EMBED_MODEL", "intfloat/multilingual-e5-small")
CACHE = Path(__file__).resolve().parents[3] / ".cache" / "embeddings"

_model = None


def model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(EMBED_MODEL, device="cpu")
    return _model


def _prefix(kind: str) -> str:
    # e5 models are trained with these prefixes; harmless for others.
    return f"{kind}: " if "e5" in EMBED_MODEL else ""


def embed(texts: list[str], kind: str) -> np.ndarray:
    return (
        model()
        .encode(
            [_prefix(kind) + t for t in texts],
            batch_size=32,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        .astype(np.float32)
    )


class Dense:
    def __init__(self, texts: list[str], name: str):
        key = hashlib.sha1(("\n".join(texts) + EMBED_MODEL).encode()).hexdigest()[:16]
        path = CACHE / f"{name}-{key}.npy"
        if path.exists():
            self.matrix = np.load(path)
        else:
            self.matrix = embed(texts, "passage")
            CACHE.mkdir(parents=True, exist_ok=True)
            np.save(path, self.matrix)

    def scores(self, query: str) -> np.ndarray:
        return self.matrix @ embed([query], "query")[0]
