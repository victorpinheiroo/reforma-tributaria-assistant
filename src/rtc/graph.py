"""The agent: a LangGraph with typed nodes.

    async with Agent.open() as agent:
        answer = await agent.ask("Quanto de CBS ... em 15/06/2026?")

    router ──► fora_escopo ─────────────────────────────────────────► END
       │  ──► pergunta_de_volta (calculation without an operation date) ► END
       ├──► rag ──────────────► synth ► END            (conceitual)
       ├──► tools ────────────► synth ► END            (numerica)
       └──► rag ──► tools ────► synth ► END            (mista)

The model interprets (route, dates, tool arguments, wording); numbers come from the calculator via
the MCP server or from the cited law text. Decisions that can be deterministic are not left to the
model: asking back for a missing operation date, and spotting that the best-matching rule is not
in effect yet at the reference date (by searching with and without the vigência filter).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Literal, TypedDict

import yaml
from langgraph.graph import END, START, StateGraph
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from pydantic import BaseModel

from rtc.llm import LLMClient, Message, make_client, tool_spec
from rtc.retrieve import Retriever
from rtc.verify import (
    Report,
    check_numbers,
    check_vigencia,
    judge_excerpt,
    sentences_with_citations,
    support_check,
)

ROOT = Path(__file__).resolve().parents[2]
PROMPTS = ROOT / "prompts"
FUTURE_MARGIN = 1.0  # rerank score by which a not-yet-in-effect rule must beat in-force text
DISCLAIMER = "Consulta a documentos e ferramentas oficiais; não substitui um contador."


class Prompt(BaseModel):
    name: str
    version: int
    created_at: str
    system: str
    few_shots: list[dict[str, str]] = []

    @property
    def key(self) -> str:
        return f"{self.name}@{self.version}"


def load_prompt(name: str) -> Prompt:
    return Prompt.model_validate(yaml.safe_load((PROMPTS / f"{name}.yml").read_text("utf-8")))


# --- structured outputs -----------------------------------------------------------------------


class RouterOut(BaseModel):
    rota: Literal["conceitual", "numerica", "mista", "fora_escopo"]
    data_referencia: str
    data_explicita: bool
    calculo_de_operacao: bool


class SynthOut(BaseModel):
    resposta: str
    citacoes: list[int]
    desfecho: Literal["resposta", "sem_numero_oficial", "nao_vigente", "nao_encontrei"]


# --- state ------------------------------------------------------------------------------------


class Trecho(TypedDict):
    n: int
    citacao: str
    texto: str
    vigencia_inicio: str | None
    vigente: bool
    score: float


class Calculo(TypedDict):
    n: int
    ferramenta: str
    argumentos: dict
    resultado: dict


class State(TypedDict, total=False):
    pergunta: str
    hoje: str
    rota: str
    data_ref: str
    data_origem: str  # "explícita na pergunta" | "hoje"
    calculo_de_operacao: bool
    trechos: list[Trecho]
    calculos: list[Calculo]
    resposta: str
    citacoes: list[str]
    desfecho: str
    cited_n: list[int]
    feedback: str
    tentativas: int
    verificacao: dict
    trace: list[dict]


class Answer(BaseModel):
    pergunta: str
    resposta: str
    desfecho: str
    rota: str
    data_referencia: str | None
    data_origem: str | None
    citacoes: list[dict]
    calculos: list[dict]
    fontes: list[dict] = []  # every retrieved excerpt shown to the synthesizer
    verificacao: dict = {}
    trace: list[dict]


# --- tools over MCP ---------------------------------------------------------------------------


class Toolbox:
    """MCP client session to rtc-tools (spawned over stdio, as any MCP host would)."""

    def __init__(self, session: ClientSession, specs: list[dict]):
        self.session, self.specs = session, specs

    @classmethod
    @asynccontextmanager
    async def open(cls):
        # Full environment: the server needs RTC_CALCULADORA_URL (the MCP client otherwise passes
        # only a minimal set such as PATH and HOME).
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "rtc.mcp_server"],
            cwd=str(ROOT),
            env=dict(os.environ),
        )
        async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            specs = [tool_spec(t.name, t.description or "", t.input_schema) for t in tools]
            yield cls(session, specs)

    async def call(self, name: str, args: dict) -> dict:
        res = await self.session.call_tool(name, args)
        if res.is_error:
            text = res.content[0].text if res.content else "erro"
            return {
                "ok": False,
                "dados": None,
                "fonte": None,
                "erro": {"status": 422, "titulo": "Argumentos inválidos", "detalhe": text[:300]},
            }
        return json.loads(res.content[0].text)


# --- nodes ------------------------------------------------------------------------------------


def _messages(p: Prompt, system: str, user: str) -> list[Message]:
    msgs = [Message(role="system", content=system)]
    for s in p.few_shots:
        msgs += [
            Message(role="user", content=s["user"]),
            Message(role="assistant", content=s["assistant"]),
        ]
    return msgs + [Message(role="user", content=user)]


class Agent:
    def __init__(self, llm: LLMClient, retriever: Retriever, tools: Toolbox):
        self.llm, self.retriever, self.tools = llm, retriever, tools
        self.p_router, self.p_tools, self.p_synth, self.p_judge = (
            load_prompt(n) for n in ("router", "tools", "synth", "judge")
        )
        self.graph = self._build()

    @classmethod
    @asynccontextmanager
    async def open(cls, model: str | None = None, retriever: Retriever | None = None):
        model = model or yaml.safe_load((ROOT / "config" / "models.yml").read_text())["agent"]
        async with AsyncExitStack() as stack:
            tools = await stack.enter_async_context(Toolbox.open())
            yield cls(make_client(model), retriever or Retriever.load("dispositivo"), tools)

    def _trace(self, state: State, node: str, t0: float, **extra) -> list[dict]:
        return [
            *state.get("trace", []),
            {"node": node, "ms": int((time.perf_counter() - t0) * 1000), **extra},
        ]

    # router -----------------------------------------------------------------------------------
    async def router(self, s: State) -> State:
        t0 = time.perf_counter()
        p = self.p_router
        r = await asyncio.to_thread(
            self.llm.complete,
            _messages(p, p.system.format(hoje=s["hoje"]), s["pergunta"]),
            RouterOut,
            None,
            p.key,
        )
        out = (
            RouterOut.model_validate(r.parsed)
            if r.parsed
            else RouterOut(
                rota="conceitual",
                data_referencia="",
                data_explicita=False,
                calculo_de_operacao=False,
            )
        )
        try:
            ref = date.fromisoformat(out.data_referencia).isoformat() if out.data_referencia else ""
        except ValueError:
            ref = ""
        explicit = bool(ref) and out.data_explicita
        return {
            "rota": out.rota,
            "data_ref": ref if explicit else s["hoje"],
            "data_origem": "explícita na pergunta"
            if explicit
            else "hoje (a pergunta não traz data)",
            "calculo_de_operacao": out.calculo_de_operacao,
            "trace": self._trace(
                s,
                "router",
                t0,
                rota=out.rota,
                data_ref=ref,
                cached=r.cached,
                parse_error=r.parse_error,
            ),
        }

    def after_router(self, s: State) -> str:
        if s["rota"] == "fora_escopo":
            return "fora_escopo"
        if s["calculo_de_operacao"] and s["data_origem"].startswith("hoje"):
            return "pergunta_de_volta"  # deterministic: never calculate an operation on an assumed date
        return {"conceitual": "rag", "numerica": "tools", "mista": "rag"}[s["rota"]]

    async def fora_escopo(self, s: State) -> State:
        return {
            "desfecho": "fora_escopo",
            "citacoes": [],
            "resposta": (
                "Esta pergunta está fora do escopo do assistente: ele consulta a legislação da reforma "
                "tributária do consumo (CBS, IBS e Imposto Seletivo) e a calculadora oficial, mas não "
                f"trata de outros tributos nem dá orientação tributária. {DISCLAIMER}"
            ),
        }

    async def pergunta_de_volta(self, s: State) -> State:
        return {
            "desfecho": "pergunta_de_volta",
            "citacoes": [],
            "resposta": (
                "Para calcular, preciso da data da operação (data do fato gerador): as regras e "
                "alíquotas mudam a cada ano da transição entre 2026 e 2033. Em que data ocorre a venda?"
            ),
        }

    # rag ----------------------------------------------------------------------------------------
    async def rag(self, s: State) -> State:
        t0 = time.perf_counter()
        ref = date.fromisoformat(s["data_ref"])
        vig = await asyncio.to_thread(self.retriever.search, s["pergunta"], ref, 5)
        allx = await asyncio.to_thread(
            self.retriever.search, s["pergunta"], ref, 3, "hybrid", False
        )
        best = vig[0].score if vig else float("-inf")
        future = [
            h
            for h in allx
            if h.chunk.get("vigencia_inicio")
            and date.fromisoformat(h.chunk["vigencia_inicio"]) > ref
            and h.score > best + FUTURE_MARGIN
        ]
        hits = [(h, True) for h in vig] + [(h, False) for h in future[:2]]
        trechos = [
            Trecho(
                n=i + 1,
                citacao=h.citacao,
                texto=h.chunk["texto"][:1800],
                vigencia_inicio=h.chunk.get("vigencia_inicio"),
                vigente=ok,
                score=h.score,
            )
            for i, (h, ok) in enumerate(hits)
        ]
        return {
            "trechos": trechos,
            "trace": self._trace(
                s, "rag", t0, top=[t["citacao"] for t in trechos], futuros=len(future)
            ),
        }

    def after_rag(self, s: State) -> str:
        return "tools" if s["rota"] == "mista" else "synth"

    # tools --------------------------------------------------------------------------------------
    async def tool_node(self, s: State) -> State:
        t0 = time.perf_counter()
        p = self.p_tools
        sys_ = p.system.format(data_ref=s["data_ref"], hoje=s["hoje"])
        r = await asyncio.to_thread(
            self.llm.complete, _messages(p, sys_, s["pergunta"]), None, self.tools.specs, p.key
        )
        calculos: list[Calculo] = []
        for i, call in enumerate(r.tool_calls[:3], start=1):
            result = await self.tools.call(call.name, call.arguments)
            calculos.append(
                Calculo(n=i, ferramenta=call.name, argumentos=call.arguments, resultado=result)
            )
        return {
            "calculos": calculos,
            "trace": self._trace(
                s, "tools", t0, chamadas=[c["ferramenta"] for c in calculos], cached=r.cached
            ),
        }

    # synth --------------------------------------------------------------------------------------
    async def synth(self, s: State) -> State:
        t0 = time.perf_counter()
        parts = []
        for t in s.get("trechos", []):
            flag = (
                ""
                if t["vigente"]
                else f" — NÃO VIGENTE na data (produz efeitos a partir de {t['vigencia_inicio']})"
            )
            parts.append(f"[{t['n']}] {t['citacao']}{flag}\n{t['texto']}")
        for c in s.get("calculos", []):
            res = c["resultado"]
            body = {"ok": res.get("ok"), "dados": res.get("dados"), "erro": res.get("erro")}
            parts.append(
                f"[T{c['n']}] calculadora oficial: {c['ferramenta']}({json.dumps(c['argumentos'], ensure_ascii=False)})\n"
                f"{json.dumps(body, ensure_ascii=False)[:2500]}"
            )
        fontes = "\n\n".join(parts) if parts else "(nenhuma fonte encontrada)"
        p = self.p_synth
        sys_ = p.system.format(
            data_ref=s["data_ref"], data_origem=s["data_origem"], hoje=s["hoje"], fontes=fontes
        )
        key = p.key
        if s.get("feedback"):
            sys_ += (
                "\n\nA previous draft failed verification. Fix exactly these problems and keep "
                "everything else faithful to the sources:\n" + s["feedback"]
            )
            key += f"#fix{s.get('tentativas', 1)}"
        msgs = _messages(p, sys_, s["pergunta"])
        r = await asyncio.to_thread(self.llm.complete, msgs, SynthOut, None, key)
        if not r.parsed:
            # One retry with a distinct cache key: free-tier models occasionally return prose.
            retry = msgs + [
                Message(role="user", content="Responda apenas com o objeto JSON pedido.")
            ]
            r = await asyncio.to_thread(self.llm.complete, retry, SynthOut, None, key + "#retry")
        if r.parsed:
            out = SynthOut.model_validate(r.parsed)
        else:
            out = SynthOut(
                resposta=f"Não consegui compor a resposta ({r.parse_error}).",
                citacoes=[],
                desfecho="nao_encontrei",
            )
        by_n = {t["n"]: t["citacao"] for t in s.get("trechos", [])}
        markers = [int(x) for x in re.findall(r"\[(\d+)\]", out.resposta)]
        cited_n = [n for n in dict.fromkeys([*out.citacoes, *markers]) if n in by_n]
        return {
            "resposta": out.resposta,
            "citacoes": [by_n[n] for n in cited_n],
            "cited_n": cited_n,
            "desfecho": out.desfecho,
            "trace": self._trace(s, "synth", t0, cached=r.cached, parse_error=r.parse_error),
        }

    # verify -------------------------------------------------------------------------------------
    async def verify(self, s: State) -> State:
        t0 = time.perf_counter()
        trechos = {t["n"]: t for t in s.get("trechos", [])}
        cited = [trechos[n] for n in s.get("cited_n", []) if n in trechos]
        tools = [c["resultado"] for c in s.get("calculos", [])]
        rep_ = Report(
            sem_origem=check_numbers(
                s["resposta"],
                s["pergunta"],
                s["data_ref"],
                [t["texto"] for t in cited],
                tools,
                [t["vigencia_inicio"] for t in cited if t["vigencia_inicio"]],
            ),
            vigencia=check_vigencia(s["resposta"], s["desfecho"], s["data_ref"], cited),
        )
        sents = sentences_with_citations(s["resposta"])
        rep_.sem_suporte = await asyncio.to_thread(
            support_check,
            self.llm,
            sents,
            {
                n: judge_excerpt(t["citacao"], t["texto"], t["vigencia_inicio"])
                for n, t in trechos.items()
            },
            self.p_judge,
        )
        tent = s.get("tentativas", 0)
        v = {
            "ok": rep_.ok,
            "sem_origem": rep_.sem_origem,
            "vigencia": rep_.vigencia,
            "sem_suporte": rep_.sem_suporte,
            "tentativas": tent,
            "frases_citadas": len(sents),
        }
        upd: State = {
            "verificacao": v,
            "trace": self._trace(
                s,
                "verify",
                t0,
                ok=rep_.ok,
                tentativa=tent,
                sem_origem=len(rep_.sem_origem),
                vigencia=len(rep_.vigencia),
                sem_suporte=len(rep_.sem_suporte),
            ),
        }
        if not rep_.ok and tent < 1:
            upd |= {"feedback": rep_.feedback(), "tentativas": tent + 1}
        return upd

    def after_verify(self, s: State) -> str:
        v = s["verificacao"]
        if v["ok"]:
            return END
        if s.get("tentativas", 0) == 1 and v["tentativas"] == 0:
            return "synth"  # one repair pass with the verifier's feedback
        if v["sem_origem"] or v["vigencia"]:
            return "bloqueado"  # hard rules: never ship an unsourced number or a wrong vigência
        return END  # unsupported sentences after repair: shipped with the warning in verificacao

    async def bloqueado(self, s: State) -> State:
        motivos = []
        if s["verificacao"]["sem_origem"]:
            motivos.append("havia valores que não constam das fontes oficiais consultadas")
        if s["verificacao"]["vigencia"]:
            motivos.append("a resposta tratava como vigente uma regra que ainda não vale na data")
        return {
            "desfecho": "bloqueado",
            "citacoes": [],
            "cited_n": [],
            "resposta": (
                "Não vou mostrar a resposta gerada porque ela não passou na verificação: "
                + "; ".join(motivos)
                + ". Reformule a pergunta ou informe mais dados da operação. "
                + DISCLAIMER
            ),
        }

    # graph --------------------------------------------------------------------------------------
    def _build(self):
        g = StateGraph(State)
        g.add_node("router", self.router)
        g.add_node("fora_escopo", self.fora_escopo)
        g.add_node("pergunta_de_volta", self.pergunta_de_volta)
        g.add_node("rag", self.rag)
        g.add_node("tools", self.tool_node)
        g.add_node("synth", self.synth)
        g.add_node("verify", self.verify)
        g.add_node("bloqueado", self.bloqueado)
        g.add_edge(START, "router")
        g.add_conditional_edges(
            "router", self.after_router, ["fora_escopo", "pergunta_de_volta", "rag", "tools"]
        )
        g.add_conditional_edges("rag", self.after_rag, ["tools", "synth"])
        g.add_edge("tools", "synth")
        g.add_edge("synth", "verify")
        g.add_conditional_edges("verify", self.after_verify, ["synth", "bloqueado", END])
        g.add_edge("bloqueado", END)
        g.add_edge("fora_escopo", END)
        g.add_edge("pergunta_de_volta", END)
        return g.compile()

    async def ask(self, pergunta: str, hoje: date | None = None) -> Answer:
        s: State = await self.graph.ainvoke(
            {"pergunta": pergunta, "hoje": (hoje or date.today()).isoformat(), "trace": []}
        )
        trechos = {t["citacao"]: t for t in s.get("trechos", [])}
        return Answer(
            pergunta=pergunta,
            resposta=s.get("resposta", ""),
            desfecho=s.get("desfecho", ""),
            rota=s.get("rota", ""),
            data_referencia=s.get("data_ref"),
            data_origem=s.get("data_origem"),
            citacoes=[
                {
                    "citacao": c,
                    "trecho": trechos[c]["texto"][:400],
                    "texto": trechos[c]["texto"],  # full excerpt, for audits and the verifier
                    "n": trechos[c]["n"],
                    "vigencia_inicio": trechos[c]["vigencia_inicio"],
                }
                for c in s.get("citacoes", [])
                if c in trechos
            ],
            calculos=[
                {
                    "ferramenta": c["ferramenta"],
                    "argumentos": c["argumentos"],
                    "ok": c["resultado"].get("ok"),
                    "dados": c["resultado"].get("dados"),
                    "erro": c["resultado"].get("erro"),
                    "fonte": c["resultado"].get("fonte"),
                }
                for c in s.get("calculos", [])
            ],
            fontes=[
                {
                    "n": t["n"],
                    "citacao": t["citacao"],
                    "texto": t["texto"],
                    "vigencia_inicio": t["vigencia_inicio"],
                    "vigente": t["vigente"],
                }
                for t in s.get("trechos", [])
            ],
            verificacao=s.get("verificacao", {}),
            trace=s.get("trace", []),
        )
