"""The spike's calculator responses are the contract the MCP server will be tested against."""

import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures" / "calculadora"


def load(name):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


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


@pytest.mark.parametrize(
    "name, cbs, ibs",
    [
        ("c1_doc_example_2027", "42.24", "0.48"),  # the calculator's own documented example
        ("c2_full_2026", "9.00", "1.00"),  # 2026 test year: CBS 0.9%, IBS 0.1%
        ("c3_full_2027_nominal", "88.00", "1.00"),
        ("c4_cesta_basica_2026", "0.00", "0.00"),  # 100% reduction
    ],
)
def test_calculations(name, cbs, ibs):
    f = load(name)
    assert f["status"] == 200
    assert find(f["response"], "vCBS") == cbs and find(f["response"], "vIBS") == ibs


@pytest.mark.parametrize(
    "name, title",
    [
        ("c5_2027_without_rates", "Alíquotas nominais não informadas"),
        ("c6_beer_2027_needs_is", "Dados do Imposto Seletivo não informados"),
    ],
)
def test_date_dependent_rules_are_errors_not_numbers(name, title):
    f = load(name)
    assert f["status"] == 422 and f["response"]["title"] == title
