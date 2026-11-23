"""Retriever: candidates from BM25 and dense, RRF fusion, vigência filter, cross-encoder rerank."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from rtc.ingest.vigencia import em_vigor
from rtc.retrieve.dense import Dense
from rtc.retrieve.sparse import Sparse

PROCESSED = Path(__file__).resolve().parents[3] / "corpus" / "processed"
RERANK_MODEL = os.environ.get("RTC_RERANK_MODEL", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
RRF_K = 60
CANDIDATES = 50  # per retriever, before fusion
RERANK_TOP = 30  # fused candidates passed to the cross-encoder

_reranker = None


def reranker():
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder

        _reranker = CrossEncoder(RERANK_MODEL, device="cpu", max_length=512)
    return _reranker


@dataclass
class Hit:
    chunk: dict
    score: float
    stage: str

    @property
    def citacao(self) -> str:
        return self.chunk["citacao"]


def rrf(rankings: list[list[int]], k: int = RRF_K) -> list[int]:
    score: dict[int, float] = {}
    for ranking in rankings:
        for pos, idx in enumerate(ranking):
            score[idx] = score.get(idx, 0.0) + 1.0 / (k + pos + 1)
    return sorted(score, key=score.get, reverse=True)


class Retriever:
    def __init__(self, chunks: list[dict], name: str):
        self.chunks = [c for c in chunks if not c.get("revogado")]
        texts = [f"{c['citacao']}\n{c['texto']}" for c in self.chunks]
        self.sparse = Sparse(texts)
        self.dense = Dense(texts, name)
        self.texts = texts

    @classmethod
    def load(cls, strategy: str = "dispositivo") -> Retriever:
        path = PROCESSED / f"chunks_{strategy}.jsonl"
        chunks = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]
        return cls(chunks, strategy)

    def search(
        self,
        query: str,
        ref: date | None = None,
        k: int = 5,
        mode: str = "hybrid",  # "bm25" | "dense" | "hybrid"
        filter_vigencia: bool = True,
        rerank: bool = True,
    ) -> list[Hit]:
        ranks = []
        if mode in ("bm25", "hybrid"):
            ranks.append(list(np.argsort(-self.sparse.scores(query))[:CANDIDATES]))
        if mode in ("dense", "hybrid"):
            ranks.append(list(np.argsort(-self.dense.scores(query))[:CANDIDATES]))
        order = rrf(ranks) if len(ranks) > 1 else ranks[0]
        if filter_vigencia and ref is not None:
            order = [i for i in order if em_vigor(self.chunks[i], ref)]
        if not rerank:
            return [Hit(self.chunks[i], 0.0, mode) for i in order[:k]]
        top = order[:RERANK_TOP]
        if not top:
            return []
        scores = reranker().predict([(query, self.texts[i]) for i in top], show_progress_bar=False)
        best = sorted(zip(top, scores, strict=True), key=lambda t: t[1], reverse=True)[:k]
        return [Hit(self.chunks[i], float(s), "rerank") for i, s in best]
