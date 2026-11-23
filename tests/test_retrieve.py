"""Retrieval pieces that need no model: tokenization, fusion, the vigência filter."""

from datetime import date

from rtc.ingest.vigencia import em_vigor
from rtc.retrieve.pipeline import rrf
from rtc.retrieve.sparse import tokens


def test_tokens_keep_legal_identifiers():
    t = tokens("Art. 138 e NCM 1006.30.21, cClassTrib 000001")
    assert "138" in t and "10063021" in t and "1006.30.21" in t and "000001" in t
    assert "e" not in t  # stopword


def test_tokens_fold_accents():
    assert tokens("alíquota redução") == ["aliquota", "reducao"]


def test_rrf_rewards_agreement():
    # doc 7 is second in both lists, doc 1 and 9 first in only one: 7 wins
    assert rrf([[1, 7, 3], [9, 7, 4]])[0] == 7


def test_filter_drops_future_provisions():
    chunks = [{"vigencia_inicio": "2026-01-01"}, {"vigencia_inicio": "2027-01-01"}]
    kept = [c for c in chunks if em_vigor(c, date(2026, 6, 1))]
    assert kept == [chunks[0]]
