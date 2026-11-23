"""The MCP server, called through the MCP layer, against recorded calculator answers.

No Java, no calculator: tests/fixtures/calculadora/http.json is replayed. The same scenarios run
over stdio against the live calculator in scripts/mcp_smoke.py.
"""

import asyncio
import json
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from scenarios import SCENARIOS

import rtc.mcp_server as srv
from rtc.calculadora import Calculadora, ReplayTransport

HTTP = Path(__file__).parent / "fixtures" / "calculadora" / "http.json"


@pytest.fixture(autouse=True)
def replay(monkeypatch):
    monkeypatch.setattr(srv, "_calc", Calculadora(transport=ReplayTransport(HTTP)))


def call(tool: str, args: dict) -> dict:
    res = asyncio.run(srv.server.call_tool(tool, args))
    assert not res.is_error, res.content
    return json.loads(res.content[0].text)


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


def test_lists_the_five_tools_with_required_dates():
    tools = {t.name: t for t in asyncio.run(srv.server.list_tools())}
    assert set(tools) == {
        "calcular_regime_geral",
        "consultar_ncm",
        "consultar_classificacao",
        "consultar_aliquota",
        "consultar_fundamentacao",
    }
    for name, t in tools.items():
        req = t.input_schema["required"]
        assert "data" in req or "data_operacao" in req, f"{name} must require a date"


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_scenario_through_mcp(name):
    sc = SCENARIOS[name]
    out = call(sc["tool"], sc["args"])
    assert set(out) == {"ok", "dados", "erro", "fonte"}
    if "erro" in sc["expect"]:
        assert out["ok"] is False and out["erro"]["titulo"] == sc["expect"]["erro"]
        assert out["dados"] is None  # a refusal never carries a number
    else:
        assert out["ok"] is True
        for k, v in sc["expect"].items():
            assert find(out["dados"], k) == v, (k, find(out["dados"], k))


def test_every_answer_names_its_source():
    out = call(**{"tool": "calcular_regime_geral", "args": SCENARIOS["calc_2026_camiseta"]["args"]})
    f = out["fonte"]
    assert f["calculadora"] == "1.7.2" and f["banco"].startswith("V0073")
    req = f["requisicao"]
    assert req["municipio"] == 4314902  # Porto Alegre, resolved by the tool, not the model
    assert req["itens"][0]["ncm"] == "61091000"  # dots stripped before the call
    assert req["dhFatoGerador"].startswith("2026-06-01")


def test_bad_parameters_are_refused_before_any_call():
    # Not recorded in http.json: if the client called the calculator, replay would raise.
    out = call("consultar_ncm", {"ncm": "123", "data": "2026-06-01"})
    assert out["ok"] is False and out["erro"]["titulo"] == "Parâmetro inválido"
    out = call("consultar_classificacao", {"cclasstrib": "12", "data": "2026-06-01"})
    assert out["ok"] is False and out["erro"]["titulo"] == "Parâmetro inválido"


def test_schema_violations_are_rejected_before_the_tool_runs():
    # In process the server raises ToolError; over the protocol it reaches the client as
    # is_error=True (checked end to end by scripts/mcp_smoke.py over stdio).
    with pytest.raises(ToolError, match="at least 1 item"):
        asyncio.run(
            srv.server.call_tool(
                "calcular_regime_geral",
                {
                    "data_operacao": "2026-06-01",
                    "uf": "RS",
                    "municipio": "Porto Alegre",
                    "itens": [],
                },
            )
        )
