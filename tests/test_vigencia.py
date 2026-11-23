"""Vigência rules: transcription checked against the law's own effects clauses, plus spot checks."""

import json
import re
from datetime import date
from pathlib import Path

import pytest

from rtc.ingest.vigencia import REGRAS, em_vigor, vigencia

PROC = Path(__file__).resolve().parents[1] / "corpus" / "processed" / "provisions.jsonl"


@pytest.fixture(scope="module")
def provs():
    return [json.loads(x) for x in PROC.read_text(encoding="utf-8").splitlines()]


def clause_text(provs, lei, artigo):
    return " ".join(p["texto"] for p in provs if p["lei"] == lei and p["artigo"] == artigo)


@pytest.mark.parametrize(
    "lei, artigo", [("LC 214/2025", "544"), ("LC 227/2026", "182"), ("EC 132/2023", "23")]
)
def test_every_rule_number_appears_in_the_effects_clause(provs, lei, artigo):
    text = clause_text(provs, lei, artigo)
    numbers = set(re.findall(r"\d+", text))
    for regra in REGRAS[lei]:
        for spec in regra.artigos:
            for n in spec.split("-"):
                assert n in numbers, f"{lei} {regra.fonte}: art. {n} not in art. {artigo}"
        if regra.inicio:
            assert str(regra.inicio.year) in text or regra.inicio.year == 2025


def v(*args, **kw):
    return vigencia(*args, **kw)["vigencia_inicio"]


def test_spot_checks():
    assert v("LC 214/2025", "26") == "2026-01-01"  # default (art. 544, VI)
    assert v("LC 214/2025", "58") == "2025-01-01"  # "art. 58, caput"
    assert v("LC 214/2025", "58", "1") == "2026-01-01"  # its paragraphs are not listed
    assert v("LC 214/2025", "60", "3") == "2025-01-01"
    assert v("LC 214/2025", "450") == "2027-01-01"  # "450, exceto os §§ 1º e 5º"
    assert v("LC 214/2025", "450", "1") == "2029-01-01"  # "450, §§ 1º e 5º"
    assert v("LC 214/2025", "538") == "2025-05-01"
    assert v("LC 214/2025", "518") == "2033-01-01"
    assert v("LC 227/2026", "10") == "2026-01-14"  # publication
    assert v("LC 227/2026", "169") == "2027-01-01"
    assert v("LC 227/2026", "76", None, "II", "c") == "2027-01-01"
    assert v("LC 227/2026", "76", None, "II", "a") == "2026-01-14"
    cond = vigencia("LC 227/2026", "52", "4")
    assert cond["vigencia_inicio"] is None and "CGIBS" in cond["vigencia_condicao"]
    assert v("EC 132/2023", "1") == "2023-12-20"  # CF text inserted by art. 1
    assert v("EC 132/2023", "4") == "2033-01-01"


def test_insertions_by_lc227_cannot_predate_it():
    notas = ["(Incluído pela Lei Complementar nº 227, de 2026)"]
    assert v("LC 214/2025", "35", notas=notas) == "2026-01-14"  # rule says 2025; LC 227 is later


def test_filter():
    assert em_vigor({"vigencia_inicio": "2027-01-01"}, date(2027, 1, 1))
    assert not em_vigor({"vigencia_inicio": "2027-01-01"}, date(2026, 12, 31))
    assert not em_vigor({"vigencia_inicio": "2025-01-01", "revogado": True}, date(2030, 1, 1))
    assert em_vigor({"vigencia_inicio": None}, date(2026, 1, 1))  # conditional: kept, flagged


def test_corpus_counts(provs):
    own = {p["lei"] for p in provs}
    assert {"LC 214/2025", "LC 227/2026", "EC 132/2023", "CF (red. EC 132/2023)"} <= own
    lc214_arts = {int(p["artigo"].split("-")[0]) for p in provs if p["lei"] == "LC 214/2025"}
    assert lc214_arts == set(range(1, 545))
    assert any(p["lei"] == "LC 214/2025" and p["artigo"] == "217" and p["revogado"] for p in provs)
