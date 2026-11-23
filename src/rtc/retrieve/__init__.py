"""Hybrid retrieval over the legal corpus: BM25 + dense, fused with RRF, filtered by vigência
before reranking.

    r = Retriever.load("dispositivo")
    hits = r.search("Qual a alíquota da CBS em 2026?", ref=date(2026, 6, 1), k=5)

Every stage is a plain function over chunk indices, so the evaluation can switch each one on and
off (bm25 only, dense only, hybrid, + vigência filter, + reranker) and compare.
"""

from rtc.retrieve.pipeline import Hit, Retriever

__all__ = ["Hit", "Retriever"]
