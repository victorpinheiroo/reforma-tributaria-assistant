"""Milestone 1 spike: which free Databricks-hosted models do native tool calling well?

    uv run python scripts/spike_toolcalling.py [--models m1 m2 ...]

Eight Portuguese questions, each with the expected tool (or none) and the parameters that must be
right. Native OpenAI-style `tools`; temperature 0; responses cached in .cache/spike. Reports per
model: right tool (or correctly no tool), arguments valid against the Pydantic schema, key
parameters right. Writes docs/spike_toolcalling.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import date
from pathlib import Path
from typing import Literal

import httpx
from databricks.sdk import WorkspaceClient
from pydantic import BaseModel, Field, ValidationError

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache" / "spike"
TODAY = "2026-11-23"

MODELS = [
    "databricks-meta-llama-3-3-70b-instruct",
    "databricks-llama-4-maverick",
    "databricks-meta-llama-3-1-8b-instruct",
    "databricks-gpt-oss-120b",
    "databricks-gpt-oss-20b",
    "databricks-qwen3-next-80b-a3b-instruct",
    "databricks-qwen35-122b-a10b",
    "databricks-gemma-3-12b",
]


class CalcularRegimeGeral(BaseModel):
    """Calcula CBS, IBS e IS de uma operação com a calculadora oficial da Receita."""

    data_operacao: date = Field(description="Data do fato gerador, AAAA-MM-DD")
    uf: str = Field(description="Sigla da UF, ex.: SP", min_length=2, max_length=2)
    municipio: str = Field(description="Nome do município")
    ncm: str = Field(description="NCM do produto, 8 dígitos, sem pontos")
    valor: float = Field(description="Valor da operação em reais (base de cálculo)", gt=0)


class ConsultarNcm(BaseModel):
    """Consulta a descrição oficial de um NCM em uma data."""

    ncm: str = Field(description="NCM, 8 dígitos, sem pontos")
    data: date = Field(description="Data de referência, AAAA-MM-DD")


class ConsultarAliquota(BaseModel):
    """Consulta a alíquota de referência da CBS (união) ou do IBS (uf/municipio) em uma data."""

    esfera: Literal["uniao", "uf", "municipio"]
    data: date = Field(description="Data de referência, AAAA-MM-DD")
    uf: str | None = Field(default=None, description="Sigla da UF, se esfera = uf")
    municipio: str | None = Field(default=None, description="Município, se esfera = municipio")


class ConsultarClassificacao(BaseModel):
    """Consulta uma classificação tributária (cClassTrib) da CBS/IBS em uma data."""

    cclasstrib: str = Field(description="Código cClassTrib, 6 dígitos")
    data: date = Field(description="Data de referência, AAAA-MM-DD")


TOOLS = {
    "calcular_regime_geral": CalcularRegimeGeral,
    "consultar_ncm": ConsultarNcm,
    "consultar_aliquota": ConsultarAliquota,
    "consultar_classificacao": ConsultarClassificacao,
}


def tool_specs() -> list[dict]:
    def clean(s):
        if isinstance(s, dict):
            return {k: clean(v) for k, v in s.items() if k not in ("title",)}
        if isinstance(s, list):
            return [clean(v) for v in s]
        return s

    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": model.__doc__.strip(),
                "parameters": clean(model.model_json_schema()),
            },
        }
        for name, model in TOOLS.items()
    ]


SYSTEM = (
    f"You help with questions about Brazil's consumption tax reform (CBS, IBS, IS). Today is "
    f"{TODAY}. Never compute taxes yourself: call a tool for any amount, rate, NCM or "
    "classification. For conceptual questions that need no data, answer briefly without tools. "
    "Answer in Portuguese."
)

# (id, question, expected tool or None, key params that must match)
CASES = [
    (
        "t1",
        "Quanto de CBS e IBS incide numa venda de R$ 1.000 de camisetas (NCM 6109.10.00) em "
        "Porto Alegre em 15 de junho de 2026?",
        "calcular_regime_geral",
        {"ncm": "61091000", "valor": 1000, "uf": "RS", "data_operacao": "2026-06-15"},
    ),
    (
        "t2",
        "Calcule os tributos de R$ 500 de arroz, NCM 1006.30.21, vendido em São Paulo (SP) no dia "
        "2 de março de 2026.",
        "calcular_regime_geral",
        {"ncm": "10063021", "valor": 500, "uf": "SP", "data_operacao": "2026-03-02"},
    ),
    ("t3", "O que é o NCM 8517.13.00?", "consultar_ncm", {"ncm": "85171300"}),
    (
        "t4",
        "Qual a alíquota de referência da CBS hoje?",
        "consultar_aliquota",
        {"esfera": "uniao", "data": TODAY},
    ),
    (
        "t5",
        "Qual a alíquota do IBS estadual no Rio Grande do Sul em julho de 2026?",
        "consultar_aliquota",
        {"esfera": "uf", "uf": "RS", "data": "2026-07"},
    ),
    (
        "t6",
        "O que muda com a reforma tributária para quem presta serviços? Explique em poucas linhas.",
        None,
        {},
    ),
    (
        "t7",
        "Quanto pago de imposto numa venda de R$ 2.000 de notebook (NCM 8471.30.12) em Belo "
        "Horizonte, MG, no dia 10/03/2027?",
        "calcular_regime_geral",
        {"ncm": "84713012", "valor": 2000, "uf": "MG", "data_operacao": "2027-03-10"},
    ),
    (
        "t8",
        "O que significa a classificação tributária 200003?",
        "consultar_classificacao",
        {"cclasstrib": "200003"},
    ),
]


def call(w: WorkspaceClient, http: httpx.Client, model: str, question: str) -> tuple[dict, int]:
    payload = {
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}],
        "tools": tool_specs(),
        "tool_choice": "auto",
        "temperature": 0,
        "max_tokens": 1200,
    }
    key = hashlib.sha256(json.dumps([model, payload], sort_keys=True).encode()).hexdigest()
    path = CACHE / f"{key}.json"
    if path.exists():
        d = json.loads(path.read_text(encoding="utf-8"))
        return d["body"], d["ms"]
    url = f"{w.config.host}/serving-endpoints/{model}/invocations"
    t0 = time.perf_counter()
    for attempt in range(7):
        try:
            r = http.post(url, headers=w.config.authenticate(), json=payload)
        except httpx.TransportError:
            time.sleep(2 ** (attempt + 1))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(min(2 ** (attempt + 1), 60))
            continue
        break
    ms = int((time.perf_counter() - t0) * 1000)
    body = (
        r.json()
        if r.headers.get("content-type", "").startswith("application/json")
        else {"error": r.text[:300], "status": r.status_code}
    )
    if r.status_code != 200:
        body = {"error": body, "status": r.status_code}
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"body": body, "ms": ms}, ensure_ascii=False), encoding="utf-8")
    return body, ms


def norm(v) -> str:
    s = str(v).strip()
    return re.sub(r"[.\s-]", "", s) if re.fullmatch(r"[\d.\s-]+", s) and len(s) > 7 else s


def score(body: dict, expected_tool, key: dict) -> dict:
    if "error" in body:
        return {
            "tool_ok": False,
            "args_valid": False,
            "params_ok": False,
            "detail": f"provider error {body.get('status')}: {str(body['error'])[:80]}",
        }
    msg = body["choices"][0]["message"]
    calls = msg.get("tool_calls") or []
    if expected_tool is None:
        ok = not calls
        return {
            "tool_ok": ok,
            "args_valid": ok,
            "params_ok": ok,
            "detail": "" if ok else f"called {calls[0]['function']['name']}",
        }
    if not calls:
        text = msg.get("content") or ""
        return {
            "tool_ok": False,
            "args_valid": False,
            "params_ok": False,
            "detail": f"no tool call; text: {str(text)[:60]!r}",
        }
    fn = calls[0]["function"]
    name = fn["name"]
    try:
        args = json.loads(fn["arguments"]) if isinstance(fn["arguments"], str) else fn["arguments"]
    except json.JSONDecodeError:
        return {
            "tool_ok": name == expected_tool,
            "args_valid": False,
            "params_ok": False,
            "detail": "arguments are not JSON",
        }
    if name != expected_tool:
        return {
            "tool_ok": False,
            "args_valid": False,
            "params_ok": False,
            "detail": f"called {name}",
        }
    try:
        TOOLS[name].model_validate(args)
        valid = True
    except ValidationError as e:
        valid = False
        err = e.errors()[0]
    wrong = []
    for k, v in key.items():
        got = args.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            okk = got is not None and abs(float(str(got).replace(",", ".")) - v) < 0.005
        elif k in ("data", "data_operacao"):
            okk = got is not None and str(got).startswith(v)
        else:
            okk = norm(got).upper() == norm(v).upper()
        if not okk:
            wrong.append(f"{k}={got!r}")
    detail = "" if valid else f"invalid: {err['loc']} {err['msg']}"
    if wrong:
        detail = (detail + "; " if detail else "") + "wrong " + ", ".join(wrong)
    return {"tool_ok": True, "args_valid": valid, "params_ok": not wrong, "detail": detail}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--models", nargs="+", default=MODELS)
    args = p.parse_args()
    w, http = WorkspaceClient(), httpx.Client(timeout=120)
    rows = []
    for m in args.models:
        for cid, q, tool, key in CASES:
            body, ms = call(w, http, m, q)
            rows.append({"model": m, "id": cid, "ms": ms, **score(body, tool, key)})
    out = [
        f"Native tool calling, {len(CASES)} questions (7 need a tool, 1 must not call one), "
        f"4 tools, temperature 0, {TODAY}.",
        "",
        "| model | right tool | valid arguments | key params right | median s |",
        "| --- | --- | --- | --- | --- |",
    ]
    for m in args.models:
        rs = [r for r in rows if r["model"] == m]
        med = sorted(r["ms"] for r in rs)[len(rs) // 2] / 1000
        out.append(
            f"| {m} | {sum(r['tool_ok'] for r in rs)}/{len(rs)} | "
            f"{sum(r['args_valid'] for r in rs)}/{len(rs)} | "
            f"**{sum(r['params_ok'] for r in rs)}/{len(rs)}** | {med:.1f} |"
        )
    misses = [r for r in rows if not r["params_ok"]]
    if misses:
        out += ["", "| model | case | what went wrong |", "| --- | --- | --- |"]
        out += [f"| {r['model']} | {r['id']} | {r['detail'].replace('|', '/')} |" for r in misses]
    text = "\n".join(out)
    (ROOT / "docs" / "spike_toolcalling.md").write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)


if __name__ == "__main__":
    main()
