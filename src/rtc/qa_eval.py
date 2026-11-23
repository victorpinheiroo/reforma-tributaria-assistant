"""End-to-end evaluation of the agent on evals/golden_qa.jsonl (committed before the graph).

    uv run python -m rtc.qa_eval            (calculator on :8080; Databricks auth for the model)

Per question, checks:
  route     the router's route equals the expected one (reported, not required to pass)
  outcome   desfecho equals the expected one (answer, ask back, no official number, not in
            effect yet, not found, out of scope)
  citation  when articles are expected: at least one cited article is among them
  values    when calculator values are expected: each appears in a tool result, and amounts
            appear in the answer text (Brazilian format)
A case passes when outcome, citation and values hold. Writes evals/results/qa.md and qa.jsonl
(with the full answers, for reading).
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import date
from pathlib import Path

from rtc.graph import Agent

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "evals" / "golden_qa.jsonl"
OUT = ROOT / "evals" / "results"
ART = re.compile(r"^(.*?, art\. [0-9A-Za-z.\-]+)")


def find(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        obj = list(obj.values())
    if isinstance(obj, list):
        for v in obj:
            r = find(v, key)
            if r is not None:
                return r
    return None


def br(v: str) -> str:
    """'176.00' -> '176,00'; '9.00' -> '9,00'."""
    try:
        return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except ValueError:
        return v


def check(case: dict, a) -> dict:
    outcome_ok = a.desfecho == case["desfecho"]
    cited = {ART.match(c["citacao"]).group(1) for c in a.citacoes if ART.match(c["citacao"])}
    cit_ok = None
    if case.get("artigos") and case["desfecho"] in ("resposta", "nao_vigente"):
        cit_ok = bool(cited & set(case["artigos"]))
    val_ok, val_detail = None, []
    if case.get("valores"):
        val_ok = True
        for k, v in case["valores"].items():
            got = next(
                (find(c["dados"], k) for c in a.calculos if find(c["dados"], k) is not None), None
            )
            ok = got is not None and str(got) == v
            if ok and k.startswith("v"):  # amounts must reach the user, in BR format
                ok = br(v) in a.resposta or v in a.resposta
            val_ok &= ok
            val_detail.append(f"{k}={got}")
    passed = outcome_ok and cit_ok is not False and val_ok is not False
    return {
        "route_ok": a.rota == case["rota"],
        "outcome_ok": outcome_ok,
        "citation_ok": cit_ok,
        "values_ok": val_ok,
        "passed": passed,
        "values": ", ".join(val_detail),
        "cited": sorted(cited),
    }


async def run(only: set[str] | None) -> int:
    cases = [json.loads(x) for x in GOLDEN.read_text(encoding="utf-8").splitlines() if x]
    if only:
        cases = [c for c in cases if c["id"] in only]
    rows = []
    async with Agent.open() as agent:
        for c in cases:
            a = await agent.ask(c["pergunta"], date.fromisoformat(c["hoje"]))
            r = {
                "id": c["id"],
                "expected": {k: c.get(k) for k in ("rota", "desfecho")},
                "got": {"rota": a.rota, "desfecho": a.desfecho, "data_ref": a.data_referencia},
                **check(c, a),
                "resposta": a.resposta,
                "calculos": [
                    {k: x[k] for k in ("ferramenta", "argumentos", "ok", "erro")}
                    for x in a.calculos
                ],
                "trace": a.trace,
            }
            rows.append(r)
            print(
                f"{c['id']} {'PASS' if r['passed'] else 'fail'} rota={a.rota} desfecho={a.desfecho} "
                f"cit={r['citation_ok']} val={r['values_ok']}",
                file=sys.stderr,
            )
    n = len(rows)

    def frac(key):
        xs = [r[key] for r in rows if r[key] is not None]
        return f"{sum(xs)}/{len(xs)}"

    md = [
        f"End to end on {n} golden questions (committed before the graph): live model, retrieval "
        "and the official calculator over MCP.",
        "",
        "| passed | outcome | citation | calculator values | route |",
        "| --- | --- | --- | --- | --- |",
        f"| **{frac('passed')}** | {frac('outcome_ok')} | {frac('citation_ok')} | {frac('values_ok')} | {frac('route_ok')} |",
        "",
        "| id | expected outcome | got | route (exp/got) | citation | values | pass |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        md.append(
            f"| {r['id']} | {r['expected']['desfecho']} | {r['got']['desfecho']} | "
            f"{r['expected']['rota']}/{r['got']['rota']} | {r['citation_ok']} | "
            f"{r['values_ok']} {r['values']} | {'yes' if r['passed'] else '**no**'} |"
        )
    OUT.mkdir(parents=True, exist_ok=True)
    if not only:
        (OUT / "qa.md").write_text("\n".join(md) + "\n", encoding="utf-8", newline="\n")
        with (OUT / "qa.jsonl").open("w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(set(sys.argv[1:]) or None)))
