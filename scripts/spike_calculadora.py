"""Milestone 1 spike: five calculations against the official calculator, saved as fixtures.

    uv run python scripts/spike_calculadora.py      (calculator on localhost:8080)

Each case is a request we can explain by hand plus what we expect from the law. The response is
saved verbatim to tests/fixtures/calculadora/<case>.json so the MCP server and the tests can run
without the calculator. The expectations below are checked here and printed as a table.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

BASE = "http://localhost:8080/api/calculadora"
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "calculadora"
ROOT_DOC = Path(__file__).resolve().parents[1] / "vendor" / "calculadora" / "docs" / "exemplos.md"


def op(id_: str, when: str, itens: list[dict]) -> dict:
    return {
        "id": id_,
        "versao": "1.0.0",
        "dhFatoGerador": when,
        "municipio": 4314902,  # Porto Alegre
        "uf": "RS",
        "itens": itens,
    }


def item(
    n: int,
    cst: str,
    ctrib: str,
    base: float,
    ncm: str | None = None,
    nbs: str | None = None,
    aliq: dict | None = None,
) -> dict:
    it = {"numero": n, "cst": cst, "cClassTrib": ctrib, "baseCalculo": base}
    if ncm:
        it |= {"ncm": ncm, "quantidade": 1, "unidade": "UN"}
    if nbs:
        it["nbs"] = nbs
    if aliq:
        it["aliquotasNominais"] = aliq
    return it


NOMINAL_2027 = {"cbs": 8.8, "ibsEstadual": 0.05, "ibsMunicipal": 0.05}  # hypothetical, as in docs

CASES = {
    # 1. The calculator's own documented example; its README response is the oracle.
    "c1_doc_example_2027": (
        "observabilidade/regime-geral",
        "doc example: education service, 60% reduction, nominal rates given",
        op(
            "c1",
            "2027-03-10T10:00:00-03:00",
            [
                item(3, "200", "200028", 1200.00, nbs="122011200", aliq=NOMINAL_2027),
            ],
        ),
        {"vCBS": "42.24", "vIBS": "0.48"},
    ),
    # 2. 2026 test year, full taxation, reference rates from the database (CBS 0.9%, IBS 0.1%).
    "c2_full_2026": (
        "regime-geral",
        "2026, full taxation (000001), base 1000, reference rates",
        op("c2", "2026-06-01T10:00:00-03:00", [item(1, "000", "000001", 1000.00, ncm="22030000")]),
        {"vCBS": "9.00", "vIBS": "1.00"},
    ),
    # 3. 2027, full taxation, with nominal rates: the reference rate does not exist yet.
    #    T-shirt (61091000): no Imposto Seletivo, so only CBS/IBS apply.
    "c3_full_2027_nominal": (
        "regime-geral",
        "2027, T-shirt, full taxation, base 1000, hypothetical nominal rates 8.8 / 0.05 / 0.05",
        op(
            "c3",
            "2027-03-10T10:00:00-03:00",
            [
                item(1, "000", "000001", 1000.00, ncm="61091000", aliq=NOMINAL_2027),
            ],
        ),
        {"vCBS": "88.00", "vIBS": "1.00"},
    ),
    # 4. Basic food basket (rice): 100% reduction.
    "c4_cesta_basica_2026": (
        "regime-geral",
        "2026, rice (NCM 10063021), cesta básica 200003, 100% reduction",
        op("c4", "2026-06-01T10:00:00-03:00", [item(1, "200", "200003", 500.00, ncm="10063021")]),
        {"vCBS": "0.00", "vIBS": "0.00"},
    ),
    # 5. 2027 without nominal rates: expect a clear error, not a number.
    "c5_2027_without_rates": (
        "regime-geral",
        "2027 without nominal rates: must fail, there is no reference rate yet",
        op("c5", "2027-03-10T10:00:00-03:00", [item(1, "000", "000001", 1000.00, ncm="22030000")]),
        {"error": True},
    ),
    # 6. Beer in 2027: Imposto Seletivo starts in 2027, so the calculator demands IS data.
    #    The same item in 2026 (case 2) needed none. A date-dependent rule enforced by the engine.
    "c6_beer_2027_needs_is": (
        "regime-geral",
        "2027, beer (22030000) without IS data: must fail, IS applies from 2027",
        op(
            "c6",
            "2027-03-10T10:00:00-03:00",
            [
                item(1, "000", "000001", 1000.00, ncm="22030000", aliq=NOMINAL_2027),
            ],
        ),
        {"error": True},
    ),
}


def find(obj, key):
    """First value of `key` anywhere in a nested JSON."""
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


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(timeout=60)
    print("| case | what | status | got | expected | ok |\n| --- | --- | --- | --- | --- | --- |")
    for name, (path, what, body, expect) in CASES.items():
        r = client.post(f"{BASE}/{path}", json=body)
        payload = r.json()
        (OUT / f"{name}.json").write_text(
            json.dumps(
                {"endpoint": path, "request": body, "status": r.status_code, "response": payload},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if "error" in expect:
            got = f"{r.status_code} {payload.get('title') or find(payload, 'title')}"
            ok = r.status_code >= 400 or find(payload, "erros") is not None
        else:
            got_vals = {k: find(payload, k) for k in expect}
            got = ", ".join(f"{k}={v}" for k, v in got_vals.items())
            ok = all(str(got_vals[k]) == v for k, v in expect.items())
        exp = ", ".join(f"{k}={v}" for k, v in expect.items())
        print(f"| {name} | {what} | {r.status_code} | {got} | {exp} | {'yes' if ok else 'NO'} |")


if __name__ == "__main__":
    main()
