"""MCP server "rtc-tools": the official tax calculator as tools any MCP client can call.

    uv run rtc-tools                       # stdio (Claude Desktop, MCP Inspector, the graph)
    RTC_CALCULADORA_URL=http://host:8080/api/calculadora uv run rtc-tools

Every tool returns {ok, dados | erro, fonte}. `fonte` names the calculator and database versions,
the endpoint and the exact request, so any number in an answer can be traced to the call that
produced it. A calculator refusal (e.g. no reference rate for 2027 yet) comes back as `erro` with
the calculator's own wording: it is information for the user, not a crash.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from rtc.calculadora import AliquotasNominais, Calculadora, ItemOperacao, Operacao

INSTRUCTIONS = (
    "Ferramentas da calculadora oficial da Receita Federal para a reforma tributária do consumo "
    "(CBS, IBS, IS; LC 214/2025). Use-as para qualquer valor, alíquota, NCM ou classificação; "
    "nunca calcule tributos por conta própria. Toda consulta depende da data da operação. A partir "
    "de 2027 não há alíquota de referência publicada: informe alíquotas nominais e diga que são "
    "hipóteses. Não substitui orientação de um contador."
)

server = MCPServer(name="rtc-tools", version="0.1.0", instructions=INSTRUCTIONS)
_calc: Calculadora | None = None


def calc() -> Calculadora:
    global _calc
    if _calc is None:
        _calc = Calculadora()
    return _calc


Data = Annotated[date, Field(description="Data de referência (fato gerador), AAAA-MM-DD")]


@server.tool()
def calcular_regime_geral(
    data_operacao: Data,
    uf: Annotated[str, Field(description="Sigla da UF, ex.: RS")],
    municipio: Annotated[str, Field(description="Nome do município, ex.: Porto Alegre")],
    itens: Annotated[list[ItemOperacao], Field(description="Itens da operação", min_length=1)],
    aliquotas_nominais: Annotated[
        AliquotasNominais | None,
        Field(description="Obrigatório a partir de 2027 (sem alíquota de referência publicada)"),
    ] = None,
) -> dict:
    """Calcula CBS, IBS e Imposto Seletivo de uma operação do regime geral pela calculadora
    oficial da Receita. Devolve os valores por item e a requisição exata enviada."""
    op = Operacao(
        data_operacao=data_operacao,
        uf=uf,
        municipio=municipio,
        itens=itens,
        aliquotas_nominais=aliquotas_nominais,
    )
    return calc().calcular_regime_geral(op).model_dump(mode="json")


@server.tool()
def consultar_ncm(
    ncm: Annotated[str, Field(description="NCM, 8 dígitos (pontos são ignorados)")],
    data: Data,
) -> dict:
    """Descrição oficial de um NCM na data e se ele é tributado pelo Imposto Seletivo."""
    return calc().consultar_ncm(ncm, data).model_dump(mode="json")


@server.tool()
def consultar_classificacao(
    cclasstrib: Annotated[
        str, Field(description="Classificação tributária (cClassTrib), 6 dígitos")
    ],
    data: Data,
) -> dict:
    """Classificação tributária da CBS/IBS na data: descrição, tratamento e percentuais de
    redução."""
    return calc().consultar_classificacao(cclasstrib, data).model_dump(mode="json")


@server.tool()
def consultar_aliquota(
    esfera: Annotated[
        Literal["uniao", "uf", "municipio"],
        Field(description="uniao = CBS; uf = IBS estadual; municipio = IBS municipal"),
    ],
    data: Data,
    uf: Annotated[str | None, Field(description="Sigla da UF (esfera uf ou municipio)")] = None,
    municipio: Annotated[
        str | None, Field(description="Nome do município (esfera municipio)")
    ] = None,
) -> dict:
    """Alíquota de referência publicada para a data. A partir de 2027 ainda não há alíquota de
    referência: a resposta é um erro explicando isso."""
    return calc().consultar_aliquota(esfera, data, uf, municipio).model_dump(mode="json")


@server.tool()
def consultar_fundamentacao(
    cclasstrib: Annotated[str, Field(description="Classificação tributária (cClassTrib)")],
    data: Data,
) -> dict:
    """Fundamentação legal (dispositivos da LC 214/2025) de uma classificação tributária."""
    return calc().consultar_fundamentacao(cclasstrib, data).model_dump(mode="json")


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
