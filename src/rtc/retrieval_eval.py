"""Retrieval evaluation on evals/golden_retrieval.jsonl (written before the retriever existed).

    uv run python -m rtc.retrieval_eval

Unit of relevance is the legal article (or annex): a hit means one of the expected articles is
among the top k results. Chunks that span several provisions (fixed windows, sections) count for
every article they contain, which is generous to those baselines.

Reports per configuration:
  hit@5 / MRR@5   on the answerable questions
  leak@5          share of date questions whose top 5 shows an article not yet in effect
  top score       reranker score of the best hit on the no-answer questions (diagnostic for the
                  "não encontrei" threshold of milestone 5)
Writes evals/results/retrieval.md and retrieval.jsonl.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import time
from datetime import date
from pathlib import Path

from rtc.retrieve import Hit, Retriever

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "evals" / "golden_retrieval.jsonl"
OUT = ROOT / "evals" / "results"
K = 5
ART = re.compile(r"^(.*?, art\. [0-9A-Za-z.\-]+)")

CONFIGS = [
    # (name, strategy, mode, filter, rerank)
    ("bm25", "dispositivo", "bm25", True, False),
    ("dense", "dispositivo", "dense", True, False),
    ("hybrid (RRF)", "dispositivo", "hybrid", True, False),
    ("hybrid + rerank", "dispositivo", "hybrid", True, True),
    ("hybrid + rerank, no vigência filter", "dispositivo", "hybrid", False, True),
    ("chunking: fixed 1000 chars", "fixo", "hybrid", True, True),
    ("chunking: by section", "secao", "hybrid", True, True),
]


def article_keys(chunk: dict) -> set[str]:
    if "Anexo" in chunk["citacao"]:
        return {chunk["citacao"]}
    if chunk.get("artigo"):
        return {f"{chunk['lei']}, art. {chunk['artigo']}"}
    keys = set()
    for cit in chunk.get("dispositivos", [chunk["citacao"]]):
        m = ART.match(cit)
        if m:
            keys.add(m.group(1))
    return keys


def evaluate(case: dict, hits: list[Hit]) -> dict:
    ranked = [article_keys(h.chunk) for h in hits[:K]]
    rel = set(case["relevantes"])
    rank = next((i + 1 for i, keys in enumerate(ranked) if keys & rel), None)
    fut = set(case.get("futuros", []))
    return {
        "hit": rank is not None if rel else None,
        "rr": (1 / rank if rank else 0.0) if rel else None,
        "leak": any(keys & fut for keys in ranked) if fut else None,
        "top_score": hits[0].score if hits else None,
        "top": [h.citacao for h in hits[:K]],
    }


def main() -> int:
    cases = [json.loads(x) for x in GOLDEN.read_text(encoding="utf-8").splitlines() if x]
    retrievers: dict[str, Retriever] = {}
    rows, table = [], []
    for name, strategy, mode, filt, rer in CONFIGS:
        if strategy not in retrievers:
            t0 = time.perf_counter()
            retrievers[strategy] = Retriever.load(strategy)
            print(f"loaded {strategy} in {time.perf_counter() - t0:.0f}s", file=sys.stderr)
        r = retrievers[strategy]
        res = []
        for c in cases:
            hits = r.search(
                c["pergunta"], date.fromisoformat(c["data_referencia"]), K, mode, filt, rer
            )
            e = evaluate(c, hits)
            res.append(e)
            rows.append({"config": name, "id": c["id"], "tipo": c["tipo"], **e})
        ans = [e for e in res if e["hit"] is not None]
        dated = [e for e in res if e["leak"] is not None]
        noans = [e for c, e in zip(cases, res, strict=True) if c["tipo"] == "sem_resposta"]
        ansd = [e for c, e in zip(cases, res, strict=True) if c["relevantes"]]
        top_no = [e["top_score"] for e in noans if e["top_score"] is not None]
        top_yes = [e["top_score"] for e in ansd if e["top_score"] is not None]
        table.append(
            f"| {name} | **{sum(e['hit'] for e in ans)}/{len(ans)}** | "
            f"{statistics.mean(e['rr'] for e in ans):.2f} | "
            f"{sum(e['leak'] for e in dated)}/{len(dated)} | "
            + (f"{max(top_no):.2f} vs {statistics.median(top_yes):.2f} |" if rer else "n/a |")
        )
    by_type = {}
    full = [r for r in rows if r["config"] == "hybrid + rerank" and r["hit"] is not None]
    for r in full:
        by_type.setdefault(r["tipo"], []).append(r["hit"])
    md = [
        f"Retrieval on {len(cases)} golden questions (written before the retriever), top {K}, "
        "unit = legal article.",
        "",
        "| configuration | hit@5 | MRR@5 | leak@5 (not yet in effect) | best score: no-answer max vs answerable median |",  # noqa: E501
        "| --- | --- | --- | --- | --- |",
        *table,
        "",
        "Full pipeline (hybrid + rerank) by question type: "
        + ", ".join(f"{t} {sum(v)}/{len(v)}" for t, v in sorted(by_type.items())),
    ]
    misses = [r for r in full if not r["hit"]]
    if misses:
        md += [
            "",
            "Misses of the full pipeline:",
            "",
            "| id | type | top 5 |",
            "| --- | --- | --- |",
        ]
        md += [f"| {r['id']} | {r['tipo']} | {'; '.join(r['top'])} |" for r in misses]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "retrieval.md").write_text("\n".join(md) + "\n", encoding="utf-8", newline="\n")
    with (OUT / "retrieval.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
