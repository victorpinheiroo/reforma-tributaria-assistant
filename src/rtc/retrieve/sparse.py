"""BM25 over accent-folded tokens. Keeps the exact identifiers dense search blurs: "art. 138",
"cClassTrib 000001", NCM codes like 1006.30.21 (indexed both with and without dots)."""

from __future__ import annotations

import re
import unicodedata

from rank_bm25 import BM25Okapi

STOP = set(
    "a o e de da do das dos em no na nos nas um uma para por com que se ao aos as os ou "
    "sobre pela pelo pelas pelos este esta deste desta isso como qual quais é são".split()
)


def fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def tokens(text: str) -> list[str]:
    t = fold(text)
    out = []
    for tok in re.findall(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*", t):
        if tok in STOP:
            continue
        out.append(tok)
        if "." in tok or "-" in tok:  # 1006.30.21 -> also 10063021 and its parts
            out.append(re.sub(r"[.\-]", "", tok))
            out.extend(p for p in re.split(r"[.\-]", tok) if p and p not in STOP)
    return out


class Sparse:
    def __init__(self, texts: list[str]):
        self.bm25 = BM25Okapi([tokens(t) for t in texts])

    def scores(self, query: str):
        return self.bm25.get_scores(tokens(query))
