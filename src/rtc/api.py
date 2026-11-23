"""HTTP API. All logic lives here and below; the Streamlit app only renders.

    uvicorn rtc.api:app --port 8000

POST /v1/ask        question -> verified answer (agent: route, law, calculator over MCP, verify)
POST /v1/search     question + reference date -> law excerpts in effect (no model needed)
POST /v1/calculate  operation -> official calculator result (no model needed)
GET  /v1/history    last answers served by this process
GET  /healthz

Env: RTC_CALCULADORA_URL (official calculator), DATABRICKS_HOST / DATABRICKS_TOKEN (model
provider, only for /v1/ask). The API starts and serves search and calculate without any model
credentials.
"""

from __future__ import annotations

import asyncio
from collections import deque
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import date
from functools import lru_cache

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from rtc.calculadora import AliquotasNominais, Calculadora, ItemOperacao, Operacao
from rtc.graph import ROOT, Agent, Answer, Toolbox
from rtc.llm import make_client
from rtc.retrieve import Retriever

HISTORY: deque[Answer] = deque(maxlen=200)
STATE: dict = {}
LOCK = asyncio.Lock()


@lru_cache(maxsize=1)
def retriever() -> Retriever:
    return Retriever.load("dispositivo")


@lru_cache(maxsize=1)
def calculadora() -> Calculadora:
    return Calculadora()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        STATE["stack"] = stack
        yield
    STATE.clear()


app = FastAPI(title="reforma-tributaria-assistant", version="0.1.0", lifespan=lifespan)


async def agent() -> Agent:
    """Created on first use: needs model credentials and spawns the MCP server."""
    if "agent" not in STATE:
        model = yaml.safe_load((ROOT / "config" / "models.yml").read_text())["agent"]
        llm = make_client(model)  # raises without Databricks credentials
        tools = await STATE["stack"].enter_async_context(Toolbox.open())
        STATE["agent"] = Agent(llm, retriever(), tools)
    return STATE["agent"]


class AskIn(BaseModel):
    pergunta: str = Field(min_length=3, max_length=600)
    hoje: date | None = None


class SearchIn(BaseModel):
    pergunta: str = Field(min_length=3, max_length=600)
    data_referencia: date
    k: int = Field(default=5, ge=1, le=20)


class CalcIn(BaseModel):
    data_operacao: date
    uf: str
    municipio: str
    itens: list[ItemOperacao] = Field(min_length=1)
    aliquotas_nominais: AliquotasNominais | None = None


@app.get("/healthz")
def healthz() -> dict:
    try:
        v = calculadora().versao()
        calc = {"ok": True, "versao": v.get("versaoApp"), "banco": v.get("versaoDb")}
    except Exception as e:  # calculator down is reported, not fatal
        calc = {"ok": False, "erro": type(e).__name__}
    return {"ok": True, "calculadora": calc}


@app.post("/v1/search")
async def search(req: SearchIn) -> dict:
    hits = await asyncio.to_thread(retriever().search, req.pergunta, req.data_referencia, req.k)
    return {
        "data_referencia": req.data_referencia,
        "trechos": [
            {
                "citacao": h.citacao,
                "score": round(h.score, 3),
                "texto": h.chunk["texto"],
                "vigencia_inicio": h.chunk.get("vigencia_inicio"),
                "vigencia_fonte": h.chunk.get("vigencia_fonte"),
            }
            for h in hits
        ],
    }


@app.post("/v1/calculate")
async def calculate(req: CalcIn) -> dict:
    op = Operacao(**req.model_dump())
    return (await asyncio.to_thread(calculadora().calcular_regime_geral, op)).model_dump(
        mode="json"
    )


@app.post("/v1/ask", response_model=Answer)
async def ask(req: AskIn) -> Answer:
    try:
        ag = await agent()
    except Exception as e:
        raise HTTPException(503, f"model provider not configured: {type(e).__name__}: {e}") from e
    async with LOCK:  # one MCP session; questions are answered one at a time
        a = await ag.ask(req.pergunta, req.hoje)
    HISTORY.append(a)
    return a


@app.get("/v1/history")
def history(limit: int = 20) -> list[Answer]:
    return list(HISTORY)[-limit:][::-1]
