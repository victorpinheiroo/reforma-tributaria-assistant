import asyncio
import json
from datetime import date

from test_graph import FakeTools, Hit, router

from rtc.graph import Agent
from rtc.llm import Response, parse_json
from rtc.verify import check_numbers, check_vigencia, numbers_in

TOOL = [{"ok": True, "dados": {"vCBS": "176.00", "vIBS": "2.00", "pCBS": "8.80"}}]


def test_identifiers_are_not_claims():
    t = "Conforme o art. 26, § 1º, da LC 214/2025 e a EC 132/2023 [2], NCM 8471.30.12 [T1]."
    assert numbers_in(t) == []


def test_amounts_rates_and_dates_are_claims():
    vals = [str(v) for _, v in numbers_in("R$ 1.234,56 e 8,8% em 10/03/2027")]
    assert vals == ["2027", "3", "10", "1234.56", "8.8"]


def test_numbers_from_tools_question_and_cited_text_pass():
    resp = (
        "Em 10/03/2027, sobre R$ 2.000,00 incide CBS de R$ 176,00 (8,80%) [T1]; redução de 60% [1]."
    )
    assert (
        check_numbers(
            resp,
            "R$ 2.000 em 10/03/2027",
            "2027-03-10",
            ["ficam reduzidas em 60% (sessenta por cento)"],
            TOOL,
        )
        == []
    )


def test_invented_or_altered_numbers_are_caught():
    assert check_numbers("CBS de R$ 167,00 [T1].", "", "2027-03-10", [], TOOL) == ["R$ 167,00"]
    assert check_numbers("A alíquota é de 12%.", "", "2026-06-01", [], TOOL) == ["12%"]


def test_numbers_only_count_from_cited_sources():
    # 60% exists in the law, but not in what this answer cites
    assert check_numbers("Há redução de 60%.", "", "2026-06-01", ["outro texto"], []) == ["60%"]


def test_future_rule_needs_to_be_flagged_as_such():
    cited = [{"citacao": "LC 214/2025, art. 169", "vigencia_inicio": "2027-01-01"}]
    assert check_vigencia("Pode tomar crédito [1].", "resposta", "2026-11-23", cited)
    assert check_vigencia(
        "Sim, é possível, mas só a partir de 2027 [1].", "resposta", "2026-11-23", cited
    )
    assert not check_vigencia(
        "Na data, a regra ainda não vale; só a partir de 2027 [1].",
        "nao_vigente",
        "2026-11-23",
        cited,
    )


class SeqLLM:
    """Router once, then synth drafts in sequence; the judge always agrees."""

    provider, model = "fake", "fake-1"

    def __init__(self, drafts):
        self.drafts, self.synth_calls = list(drafts), 0

    def complete(self, messages, schema=None, tools=None, cache_key=None):
        name = cache_key.split("@")[0]
        if name == "router":
            out = router("conceitual")
        elif name == "judge":
            out = {"itens": []}
        else:
            out = self.drafts[min(self.synth_calls, len(self.drafts) - 1)]
            self.synth_calls += 1
        text = json.dumps(out)
        parsed, err = parse_json(text, schema)
        return Response(
            text=text, parsed=parsed, parse_error=err, provider="fake", model="f", latency_ms=1
        )


class OneHit:
    def search(self, q, ref, k=5, mode="hybrid", filter_vigencia=True, rerank=True):
        return [Hit("LC 214/2025, art. 127", "2026-01-01", 3.0)]


def ask(drafts):
    llm = SeqLLM(drafts)
    a = asyncio.run(Agent(llm, OneHit(), FakeTools()).ask("pergunta", date(2026, 11, 23)))
    return a, llm


def test_unsourced_number_is_repaired_once():
    bad = {"resposta": "Redução de 45% [1].", "citacoes": [1], "desfecho": "resposta"}
    good = {"resposta": "Há redução prevista na lei [1].", "citacoes": [1], "desfecho": "resposta"}
    a, llm = ask([bad, good])
    assert llm.synth_calls == 2 and a.desfecho == "resposta" and a.verificacao["ok"]


def test_persistent_unsourced_number_blocks_the_answer():
    bad = {"resposta": "Redução de 45% [1].", "citacoes": [1], "desfecho": "resposta"}
    a, llm = ask([bad, bad])
    assert a.desfecho == "bloqueado" and "45" not in a.resposta and llm.synth_calls == 2


def test_sentence_split_keeps_legal_abbreviations():
    from rtc.verify import sentences_with_citations

    s = sentences_with_citations(
        "O art. 169 só vale em 2027 [1]. Os arts. 31 a 35 tratam do split [2]."
    )
    assert [x[0] for x in s] == [
        "O art. 169 só vale em 2027 [1].",
        "Os arts. 31 a 35 tratam do split [2].",
    ]
