"""The graph's wiring and deterministic decisions, with a scripted LLM, retriever and toolbox."""

import asyncio
import json
from datetime import date
from pathlib import Path

from rtc.graph import Agent, load_prompt
from rtc.llm import Response, ToolCall, parse_json

ROOT = Path(__file__).resolve().parents[1]
HOJE = date(2026, 11, 23)


class FakeLLM:
    provider, model = "fake", "fake-1"

    def __init__(
        self, router: dict, synth: dict | None = None, calls: list[ToolCall] | None = None
    ):
        self.router, self.synth, self.calls = router, synth, calls or []
        self.seen: dict[str, list] = {}

    def complete(self, messages, schema=None, tools=None, cache_key=None):
        self.seen.setdefault(cache_key.split("@")[0], []).append(messages)
        name = cache_key.split("@")[0]
        if name == "tools":
            return Response(tool_calls=self.calls, provider="fake", model="fake-1", latency_ms=1)
        text = json.dumps(self.router if name == "router" else self.synth)
        parsed, err = parse_json(text, schema)
        return Response(
            text=text, parsed=parsed, parse_error=err, provider="fake", model="fake-1", latency_ms=1
        )


class Hit:
    def __init__(self, citacao, vig, score):
        self.citacao, self.score = citacao, score
        self.chunk = {"citacao": citacao, "texto": f"texto de {citacao}", "vigencia_inicio": vig}


class FakeRetriever:
    def __init__(self, vigentes, todos):
        self.vigentes, self.todos = vigentes, todos

    def search(self, q, ref, k=5, mode="hybrid", filter_vigencia=True, rerank=True):
        return (self.vigentes if filter_vigencia else self.todos)[:k]


class FakeTools:
    specs = [{"type": "function", "function": {"name": "calcular_regime_geral", "parameters": {}}}]

    def __init__(self):
        self.called = []

    async def call(self, name, args):
        self.called.append((name, args))
        return {
            "ok": True,
            "dados": {"vCBS": "9.00"},
            "erro": None,
            "fonte": {"calculadora": "1.7.2"},
        }


def run(agent, q):
    return asyncio.run(agent.ask(q, HOJE))


def router(rota, data="", explicita=False, calculo=False):
    return {
        "rota": rota,
        "data_referencia": data,
        "data_explicita": explicita,
        "calculo_de_operacao": calculo,
    }


def test_out_of_scope_ends_without_retrieval_or_tools():
    tools = FakeTools()
    a = run(Agent(FakeLLM(router("fora_escopo")), FakeRetriever([], []), tools), "IRPF?")
    assert a.desfecho == "fora_escopo" and not tools.called and "contador" in a.resposta


def test_calculation_without_date_asks_back_deterministically():
    tools = FakeTools()
    llm = FakeLLM(router("numerica", calculo=True))
    a = run(Agent(llm, FakeRetriever([], []), tools), "Quanto de CBS em R$ 1.000?")
    assert a.desfecho == "pergunta_de_volta" and not tools.called
    assert "synth" not in llm.seen  # no model call composes this answer


def test_numeric_route_calls_tool_and_synth_sees_the_result():
    tools = FakeTools()
    call = ToolCall(id="1", name="calcular_regime_geral", arguments={"data_operacao": "2026-06-15"})
    llm = FakeLLM(
        router("numerica", "2026-06-15", True, True),
        {"resposta": "CBS de R$ 9,00 [T1].", "citacoes": [], "desfecho": "resposta"},
        [call],
    )
    a = run(Agent(llm, FakeRetriever([], []), tools), "Quanto de CBS ... 15/06/2026?")
    assert tools.called == [("calcular_regime_geral", {"data_operacao": "2026-06-15"})]
    assert a.data_referencia == "2026-06-15" and a.calculos[0]["dados"] == {"vCBS": "9.00"}
    synth_system = llm.seen["synth"][0][0].content
    assert "[T1] calculadora oficial" in synth_system and '"vCBS": "9.00"' in synth_system


def test_future_rule_is_flagged_not_hidden():
    vig = [Hit("LC 214/2025, art. 47", "2026-01-01", 1.0)]
    todos = [Hit("LC 214/2025, art. 169", "2027-01-01", 6.0), *vig]
    llm = FakeLLM(
        router("conceitual"),
        {"resposta": "Só a partir de 2027 [2].", "citacoes": [2], "desfecho": "nao_vigente"},
    )
    a = run(Agent(llm, FakeRetriever(vig, todos), FakeTools()), "crédito presumido transportador?")
    synth_system = llm.seen["synth"][0][0].content
    assert "NÃO VIGENTE na data (produz efeitos a partir de 2027-01-01)" in synth_system
    assert a.desfecho == "nao_vigente" and a.citacoes[0]["citacao"] == "LC 214/2025, art. 169"
    assert a.data_origem.startswith("hoje")  # no date in the question -> today


def test_dates_the_router_invents_are_not_trusted():
    # Router says explicit=False: the reference date must be today, whatever it returned.
    llm = FakeLLM(
        router("conceitual", "2030-01-01", False),
        {"resposta": "x", "citacoes": [], "desfecho": "resposta"},
    )
    a = run(Agent(llm, FakeRetriever([], []), FakeTools()), "pergunta sem data")
    assert a.data_referencia == HOJE.isoformat()


def test_router_few_shots_do_not_leak_golden_questions():
    golden = [
        json.loads(x) for x in (ROOT / "evals" / "golden_qa.jsonl").read_text("utf-8").splitlines()
    ]
    shots = {s["user"] for s in load_prompt("router").few_shots}
    assert not shots & {g["pergunta"] for g in golden}
