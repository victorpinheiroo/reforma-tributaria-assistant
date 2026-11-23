"""Scenarios shared by the fixture recorder and the tests: (tool, arguments, what to expect)."""

from __future__ import annotations

from datetime import date

from rtc.calculadora import AliquotasNominais, Calculadora, ItemOperacao, Operacao, Resultado

D2026 = date(2026, 6, 1)
D2027 = date(2027, 3, 10)
NOMINAL = {"cbs": 8.8, "ibs_estadual": 0.05, "ibs_municipal": 0.05}  # hypothetical, as in the docs

SCENARIOS: dict[str, dict] = {
    "calc_2026_camiseta": {
        "tool": "calcular_regime_geral",
        "args": {
            "data_operacao": "2026-06-01",
            "uf": "RS",
            "municipio": "Porto Alegre",
            "itens": [{"ncm": "6109.10.00", "valor": 1000}],
        },
        "expect": {"vCBS": "9.00", "vIBS": "1.00"},
    },
    "calc_2026_arroz_cesta": {
        "tool": "calcular_regime_geral",
        "args": {
            "data_operacao": "2026-06-01",
            "uf": "SP",
            "municipio": "São Paulo",
            "itens": [{"ncm": "10063021", "valor": 500, "cst": "200", "cclasstrib": "200003"}],
        },
        "expect": {"vCBS": "0.00", "vIBS": "0.00"},
    },
    "calc_2027_nominal": {
        "tool": "calcular_regime_geral",
        "args": {
            "data_operacao": "2027-03-10",
            "uf": "MG",
            "municipio": "Belo Horizonte",
            "itens": [{"ncm": "84713012", "valor": 2000}],
            "aliquotas_nominais": NOMINAL,
        },
        "expect": {"vCBS": "176.00", "vIBS": "2.00"},
    },
    "calc_2027_sem_aliquota": {
        "tool": "calcular_regime_geral",
        "args": {
            "data_operacao": "2027-03-10",
            "uf": "MG",
            "municipio": "Belo Horizonte",
            "itens": [{"ncm": "84713012", "valor": 2000}],
        },
        "expect": {"erro": "Alíquotas nominais não informadas"},
    },
    "calc_2027_cerveja_sem_is": {
        "tool": "calcular_regime_geral",
        "args": {
            "data_operacao": "2027-03-10",
            "uf": "RS",
            "municipio": "Porto Alegre",
            "itens": [{"ncm": "22030000", "valor": 1000}],
            "aliquotas_nominais": NOMINAL,
        },
        "expect": {"erro": "Dados do Imposto Seletivo não informados"},
    },
    "calc_municipio_inexistente": {
        "tool": "calcular_regime_geral",
        "args": {
            "data_operacao": "2026-06-01",
            "uf": "RS",
            "municipio": "Gotham",
            "itens": [{"ncm": "61091000", "valor": 100}],
        },
        "expect": {"erro": "Município não encontrado"},
    },
    "ncm_celular": {
        "tool": "consultar_ncm",
        "args": {"ncm": "8517.13.00", "data": "2026-06-01"},
        "expect": {"tributadoPeloImpostoSeletivo": False},
    },
    "ncm_cerveja": {
        "tool": "consultar_ncm",
        "args": {"ncm": "22030000", "data": "2027-03-10"},
        "expect": {"tributadoPeloImpostoSeletivo": True},
    },
    "classificacao_cesta": {
        "tool": "consultar_classificacao",
        "args": {"cclasstrib": "200003", "data": "2026-06-01"},
        "expect": {"codigo": "200003"},
    },
    "aliquota_cbs_2026": {
        "tool": "consultar_aliquota",
        "args": {"esfera": "uniao", "data": "2026-06-01"},
        "expect": {"aliquotaReferencia": 0.9},
    },
    "aliquota_ibs_rs_2026": {
        "tool": "consultar_aliquota",
        "args": {"esfera": "uf", "uf": "RS", "data": "2026-07-01"},
        "expect": {"aliquotaReferencia": 0.1},
    },
    "aliquota_cbs_2027": {
        "tool": "consultar_aliquota",
        "args": {"esfera": "uniao", "data": "2027-03-10"},
        "expect": {"erro": "Alíquota não encontrada"},
    },
    "fundamentacao_cesta": {
        "tool": "consultar_fundamentacao",
        "args": {"cclasstrib": "200003", "data": "2026-06-01"},
        "expect": {"codigoClassificacaoTributaria": "200003"},
    },
}


def run(calc: Calculadora, sc: dict) -> Resultado:
    """Call the client directly (same path the MCP tools use)."""
    a = sc["args"]
    tool = sc["tool"]
    if tool == "calcular_regime_geral":
        op = Operacao(
            data_operacao=date.fromisoformat(a["data_operacao"]),
            uf=a["uf"],
            municipio=a["municipio"],
            itens=[ItemOperacao(**i) for i in a["itens"]],
            aliquotas_nominais=AliquotasNominais(**a["aliquotas_nominais"])
            if a.get("aliquotas_nominais")
            else None,
        )
        return calc.calcular_regime_geral(op)
    d = date.fromisoformat(a["data"])
    if tool == "consultar_ncm":
        return calc.consultar_ncm(a["ncm"], d)
    if tool == "consultar_classificacao":
        return calc.consultar_classificacao(a["cclasstrib"], d)
    if tool == "consultar_aliquota":
        return calc.consultar_aliquota(a["esfera"], d, a.get("uf"), a.get("municipio"))
    if tool == "consultar_fundamentacao":
        return calc.consultar_fundamentacao(a["cclasstrib"], d)
    raise ValueError(tool)
