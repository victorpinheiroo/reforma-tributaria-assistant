"""How much does the verifier catch? Seeded mistakes on real answers, plus false alarms.

    uv run python -m rtc.verify_eval        (needs what qa_eval needs; LLM calls are cached)

Takes the agent's answers to the golden questions that end in an answer, keeps those the
verifier accepts as they are (the originals; a flag on one of them is a false alarm), and seeds
one mistake per operator into each applicable original:

  amount_altered     a calculator amount in the text is changed (176,00 -> 167,00)
  invented_rate      a sentence with a rate found in no source is appended
  invented_year      a sentence moving the rule to a year found in no source is appended
  unsupported_claim  a sentence citing [n] with a claim the excerpt does not make is appended
  citation_swap      a cited sentence is re-pointed to another retrieved excerpt
  future_as_present  an answer about a rule not yet in effect is rewritten as "Sim, é possível"

Each mutant runs through the same three checks the graph runs (numbers, vigência, support).
Writes evals/results/verify.md and verify.jsonl.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import date
from pathlib import Path

from rtc.graph import Agent, load_prompt
from rtc.verify import (
    check_numbers,
    check_vigencia,
    judge_excerpt,
    sentences_with_citations,
    support_check,
)

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "evals" / "golden_qa.jsonl"
OUT = ROOT / "evals" / "results"


def run_checks(agent: Agent, a, resposta: str, desfecho: str, excerpts: dict[int, dict]) -> dict:
    cited_n = [
        n
        for n in dict.fromkeys(int(x) for x in re.findall(r"\[(\d+)\]", resposta))
        if n in excerpts
    ]
    cited = [excerpts[n] for n in cited_n]
    tools = [{"ok": c["ok"], "dados": c["dados"], "erro": c["erro"]} for c in a.calculos]
    num = check_numbers(
        resposta,
        a.pergunta,
        a.data_referencia,
        [c["texto"] for c in cited],
        tools,
        [c["vigencia_inicio"] for c in cited if c["vigencia_inicio"]],
    )
    vig = check_vigencia(resposta, desfecho, a.data_referencia, cited)
    sup = support_check(
        agent.llm,
        sentences_with_citations(resposta),
        {
            n: judge_excerpt(e["citacao"], e["texto"], e["vigencia_inicio"])
            for n, e in excerpts.items()
        },
        load_prompt("judge"),
    )
    return {
        "numbers": bool(num),
        "vigencia": bool(vig),
        "support": bool(sup),
        "detail": {"num": num, "vig": vig, "sup": sup},
    }


def mutants(a, excerpts: dict[int, dict]) -> list[tuple[str, str, str]]:
    """(operator, mutated answer, desfecho)."""
    out = []
    text, desf = a.resposta, a.desfecho
    amounts = re.findall(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})", text)
    tool_amounts = {
        f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        for c in a.calculos
        if c["dados"]
        for v in _values(c["dados"])
    }
    for amt in amounts:
        if amt in tool_amounts and amt not in ("0,00",):
            whole, cents = amt.split(",")
            altered = (
                whole[:-2] + whole[-1] + whole[-2] + "," + cents
                if len(whole) > 1
                else (str(int(whole) + 1) + "," + cents)
            )
            if altered != amt:
                out.append(("amount_altered", text.replace(amt, altered, 1), desf))
                break
    out.append(("invented_rate", text + " A alíquota efetiva aplicável é de 12,5%.", desf))
    out.append(("invented_year", text + " Essa regra passa a valer integralmente em 2031.", desf))
    nums = sorted(excerpts)
    if nums:
        n = nums[0]
        out.append(
            (
                "unsupported_claim",
                text + f" Essa regra se aplica a todas as pessoas físicas, "
                f"sem exceção, inclusive às que não exercem atividade econômica [{n}].",
                desf,
            )
        )
    cited = [int(x) for x in re.findall(r"\[(\d+)\]", text)]
    others = [n for n in nums if n not in cited]
    if cited and others:
        out.append(("citation_swap", text.replace(f"[{cited[0]}]", f"[{others[-1]}]", 1), desf))
    fut = [
        n
        for n, e in excerpts.items()
        if e["vigencia_inicio"]
        and date.fromisoformat(e["vigencia_inicio"]) > date.fromisoformat(a.data_referencia)
    ]
    if fut:
        out.append(
            (
                "future_as_present",
                f"Sim, é possível tomar o crédito [{fut[0]}]. "
                "Consulta a documentos e ferramentas oficiais; não substitui um contador.",
                "resposta",
            )
        )
    return out


def _values(d):
    if isinstance(d, dict):
        for k, v in d.items():
            if k.startswith("v") and isinstance(v, str):
                try:
                    yield float(v)
                except ValueError:
                    pass
            yield from _values(v)
    elif isinstance(d, list):
        for v in d:
            yield from _values(v)


async def main() -> int:
    cases = [json.loads(x) for x in GOLDEN.read_text(encoding="utf-8").splitlines() if x]
    rows = []
    async with Agent.open() as agent:
        for c in cases:
            a = await agent.ask(c["pergunta"], date.fromisoformat(c["hoje"]))
            if a.desfecho not in ("resposta", "nao_vigente", "sem_numero_oficial"):
                continue
            ex = {e["n"]: e for e in a.fontes}
            # all retrieved excerpts (not only cited) are fair game for swaps
            trace_rag = next((t for t in a.trace if t["node"] == "rag"), None)
            orig = await asyncio.to_thread(run_checks, agent, a, a.resposta, a.desfecho, ex)
            flagged = orig["numbers"] or orig["vigencia"] or orig["support"]
            rows.append(
                {
                    "id": c["id"],
                    "operator": "original",
                    "flagged": flagged,
                    **orig,
                    "rag": bool(trace_rag),
                }
            )
            for op, text, desf in mutants(a, ex):
                res = await asyncio.to_thread(run_checks, agent, a, text, desf, ex)
                rows.append(
                    {
                        "id": c["id"],
                        "operator": op,
                        **res,
                        "flagged": res["numbers"] or res["vigencia"] or res["support"],
                    }
                )
            print(c["id"], "original flagged" if flagged else "original clean", file=sys.stderr)
    ops = [
        "amount_altered",
        "invented_rate",
        "invented_year",
        "unsupported_claim",
        "citation_swap",
        "future_as_present",
    ]
    md = [
        "Verifier on seeded mistakes in real agent answers (golden questions that end in an "
        "answer). A mutant counts as caught if any check flags it.",
        "",
        "| operator | mutants | numbers | vigência | support (judge) | caught |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    tot = [0, 0]
    for op in ops:
        rs = [r for r in rows if r["operator"] == op]
        if not rs:
            continue
        caught = sum(r["flagged"] for r in rs)
        tot[0] += caught
        tot[1] += len(rs)
        md.append(
            f"| {op} | {len(rs)} | {sum(r['numbers'] for r in rs)} | "
            f"{sum(r['vigencia'] for r in rs)} | {sum(r['support'] for r in rs)} | "
            f"**{caught}/{len(rs)}** |"
        )
    md.append(f"| **all** | {tot[1]} | | | | **{tot[0]}/{tot[1]}** |")
    origs = [r for r in rows if r["operator"] == "original"]
    fa = [r for r in origs if r["flagged"]]
    md += [
        "",
        f"False alarms on the {len(origs)} original answers: {len(fa)} "
        f"(numbers {sum(r['numbers'] for r in origs)}, vigência {sum(r['vigencia'] for r in origs)}, "
        f"support {sum(r['support'] for r in origs)}).",
    ]
    if fa:
        md += ["", "| original flagged | what |", "| --- | --- |"]
        md += [f"| {r['id']} | {json.dumps(r['detail'], ensure_ascii=False)[:300]} |" for r in fa]
    missed = [r for r in rows if r["operator"] != "original" and not r["flagged"]]
    if missed:
        md += ["", "Missed mutants: " + ", ".join(f"{r['id']}/{r['operator']}" for r in missed)]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "verify.md").write_text("\n".join(md) + "\n", encoding="utf-8", newline="\n")
    with (OUT / "verify.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
