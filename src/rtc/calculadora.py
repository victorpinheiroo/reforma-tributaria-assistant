"""Typed client for the Federal Revenue's official calculator (regime geral), pinned version.

Inputs are validated with Pydantic before any call. Every result carries `fonte`: the calculator
version, the endpoint and the exact request sent, so a number in an answer can always be traced to
the call that produced it. A 4xx from the calculator is a legitimate answer ("missing X", "no
reference rate yet") and comes back as `erro`, not as an exception.

The municipality is resolved name -> IBGE code here, from the calculator's own open data; the
model only ever says "Porto Alegre", never a code it might invent.
"""

from __future__ import annotations

import json
import os
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, field_validator

DEFAULT_URL = os.environ.get("RTC_CALCULADORA_URL", "http://localhost:8080/api/calculadora")


# --- inputs -----------------------------------------------------------------------------------


def _digits(v: str) -> str:
    return "".join(ch for ch in str(v) if ch.isdigit())


class AliquotasNominais(BaseModel):
    """Rates in percent. Required from 2027 on: no reference rate is published yet."""

    cbs: float = Field(ge=0, le=100)
    ibs_estadual: float = Field(ge=0, le=100)
    ibs_municipal: float = Field(ge=0, le=100)


class ItemOperacao(BaseModel):
    ncm: str = Field(description="NCM do produto, 8 dígitos")
    valor: float = Field(gt=0, description="Base de cálculo em reais")
    cst: str = Field(default="000", description="CST da CBS/IBS; 000 = tributação integral")
    cclasstrib: str = Field(default="000001", description="Classificação tributária, 6 dígitos")
    quantidade: float = Field(default=1, gt=0)
    unidade: str = "UN"

    @field_validator("ncm")
    @classmethod
    def _ncm(cls, v: str) -> str:
        d = _digits(v)
        if len(d) != 8:
            raise ValueError("NCM deve ter 8 dígitos")
        return d

    @field_validator("cclasstrib", "cst")
    @classmethod
    def _codes(cls, v: str) -> str:
        return _digits(v)


class Operacao(BaseModel):
    data_operacao: date
    uf: str = Field(min_length=2, max_length=2)
    municipio: str = Field(description="Nome do município (resolvido para o código IBGE)")
    itens: list[ItemOperacao] = Field(min_length=1)
    aliquotas_nominais: AliquotasNominais | None = None

    @field_validator("uf")
    @classmethod
    def _uf(cls, v: str) -> str:
        return v.upper()


# --- outputs ----------------------------------------------------------------------------------


class Fonte(BaseModel):
    calculadora: str
    banco: str
    endpoint: str
    requisicao: dict[str, Any] | None = None


class Erro(BaseModel):
    status: int
    titulo: str
    detalhe: str


class Resultado(BaseModel):
    ok: bool
    dados: Any = None
    erro: Erro | None = None
    fonte: Fonte


# --- transports (record / replay for tests) -----------------------------------------------------


def _key(request: httpx.Request) -> str:
    q = "&".join(sorted(str(request.url.query, "utf-8").split("&"))) if request.url.query else ""
    body = request.content.decode("utf-8") if request.content else ""
    return f"{request.method} {request.url.path}?{q} {body}"


class RecordingTransport(httpx.BaseTransport):
    """Forwards to the live calculator and stores every exchange in a JSON file."""

    def __init__(self, path: Path):
        self.path, self.inner = path, httpx.HTTPTransport()
        self.store: dict[str, dict] = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        resp = self.inner.handle_request(request)
        resp.read()
        self.store[_key(request)] = {"status": resp.status_code, "body": resp.json()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.store, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return httpx.Response(resp.status_code, json=resp.json())


class ReplayTransport(httpx.BaseTransport):
    """Serves recorded exchanges; an unrecorded request fails loudly."""

    def __init__(self, path: Path):
        self.store = json.loads(path.read_text(encoding="utf-8"))

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        k = _key(request)
        if k not in self.store:
            raise KeyError(f"no recorded response for: {k[:200]}")
        rec = self.store[k]
        return httpx.Response(rec["status"], json=rec["body"])


# --- client -----------------------------------------------------------------------------------


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join(s.lower().replace("-", " ").split())


class Calculadora:
    def __init__(self, base_url: str = DEFAULT_URL, transport: httpx.BaseTransport | None = None):
        self.base = base_url.rstrip("/")
        self.http = httpx.Client(timeout=60, transport=transport)
        self._versao: dict | None = None
        self._municipios: dict[str, list[dict]] = {}

    # metadata
    def versao(self) -> dict:
        if self._versao is None:
            self._versao = self.http.get(f"{self.base}/dados-abertos/versao").json()
        return self._versao

    def _fonte(self, endpoint: str, req: dict | None = None) -> Fonte:
        v = self.versao()
        return Fonte(
            calculadora=v.get("versaoApp", "?"),
            banco=f"{v.get('versaoDb', '?')} ({v.get('dataVersaoDb', '?')})",
            endpoint=endpoint,
            requisicao=req,
        )

    def _get(self, endpoint: str, params: dict) -> Resultado:
        r = self.http.get(f"{self.base}/{endpoint}", params=params)
        return self._wrap(r, endpoint, params)

    def _wrap(self, r: httpx.Response, endpoint: str, req: dict) -> Resultado:
        body = r.json()
        if r.status_code >= 400:
            erro = Erro(
                status=r.status_code,
                titulo=str(body.get("title", "erro")),
                detalhe=str(body.get("detail", "")),
            )
            return Resultado(ok=False, erro=erro, fonte=self._fonte(endpoint, req))
        return Resultado(ok=True, dados=body, fonte=self._fonte(endpoint, req))

    # municipalities
    def codigo_municipio(self, uf: str, nome: str) -> int | None:
        uf = uf.upper()
        if uf not in self._municipios:
            r = self.http.get(f"{self.base}/dados-abertos/ufs/municipios", params={"siglaUf": uf})
            self._municipios[uf] = r.json() if r.status_code == 200 else []
        target = _fold(nome)
        for m in self._municipios[uf]:
            if _fold(m["nome"]) == target:
                return int(m["codigo"])
        return None

    # tools
    def calcular_regime_geral(self, op: Operacao) -> Resultado:
        endpoint = "regime-geral"
        cod = self.codigo_municipio(op.uf, op.municipio)
        if cod is None:
            return Resultado(
                ok=False,
                erro=Erro(
                    status=422,
                    titulo="Município não encontrado",
                    detalhe=f"'{op.municipio}' não consta na UF {op.uf}",
                ),
                fonte=self._fonte(endpoint),
            )
        itens = []
        for i, it in enumerate(op.itens, start=1):
            d: dict[str, Any] = {
                "numero": i,
                "ncm": it.ncm,
                "cst": it.cst,
                "cClassTrib": it.cclasstrib,
                "baseCalculo": round(it.valor, 2),
                "quantidade": it.quantidade,
                "unidade": it.unidade,
            }
            if op.aliquotas_nominais:
                a = op.aliquotas_nominais
                d["aliquotasNominais"] = {
                    "cbs": a.cbs,
                    "ibsEstadual": a.ibs_estadual,
                    "ibsMunicipal": a.ibs_municipal,
                }
            itens.append(d)
        body = {
            "id": "rtc-tools",
            "versao": "1.0.0",
            "dhFatoGerador": f"{op.data_operacao.isoformat()}T12:00:00-03:00",
            "municipio": cod,
            "uf": op.uf,
            "itens": itens,
        }
        r = self.http.post(f"{self.base}/{endpoint}", json=body)
        return self._wrap(r, endpoint, body)

    def _invalid(self, endpoint: str, detalhe: str) -> Resultado:
        """Refuse before calling: parameters are validated, never passed through on faith."""
        return Resultado(
            ok=False,
            erro=Erro(status=422, titulo="Parâmetro inválido", detalhe=detalhe),
            fonte=self._fonte(endpoint),
        )

    def consultar_ncm(self, ncm: str, data: date) -> Resultado:
        n = _digits(ncm)
        if len(n) != 8:
            return self._invalid("dados-abertos/ncm", f"NCM deve ter 8 dígitos (recebido '{ncm}')")
        return self._get("dados-abertos/ncm", {"ncm": n, "data": data.isoformat()})

    def consultar_classificacao(self, cclasstrib: str, data: date) -> Resultado:
        c = _digits(cclasstrib)
        if len(c) != 6:
            return self._invalid(
                "dados-abertos/classificacoes-tributarias",
                f"cClassTrib deve ter 6 dígitos (recebido '{cclasstrib}')",
            )
        return self._get(
            f"dados-abertos/classificacoes-tributarias/cbs-ibs/class-trib/{c}",
            {"data": data.isoformat()},
        )

    def consultar_aliquota(
        self,
        esfera: Literal["uniao", "uf", "municipio"],
        data: date,
        uf: str | None = None,
        municipio: str | None = None,
    ) -> Resultado:
        d = data.isoformat()
        if esfera == "uniao":
            return self._get("dados-abertos/aliquota-uniao", {"data": d})
        ufs = {
            u["sigla"]: u["codigo"] for u in self.http.get(f"{self.base}/dados-abertos/ufs").json()
        }
        if not uf or uf.upper() not in ufs:
            return Resultado(
                ok=False,
                erro=Erro(status=422, titulo="UF inválida", detalhe=f"UF '{uf}' não reconhecida"),
                fonte=self._fonte("dados-abertos/ufs"),
            )
        if esfera == "uf":
            return self._get("dados-abertos/aliquota-uf", {"codigoUf": ufs[uf.upper()], "data": d})
        cod = self.codigo_municipio(uf, municipio or "")
        if cod is None:
            return Resultado(
                ok=False,
                erro=Erro(
                    status=422,
                    titulo="Município não encontrado",
                    detalhe=f"'{municipio}' não consta na UF {uf}",
                ),
                fonte=self._fonte("dados-abertos/aliquota-municipio"),
            )
        return self._get("dados-abertos/aliquota-municipio", {"codigoMunicipio": cod, "data": d})

    def consultar_fundamentacao(self, cclasstrib: str, data: date) -> Resultado:
        """Legal grounds for one classification (the endpoint returns all; we filter)."""
        c = _digits(cclasstrib)
        res = self._get("dados-abertos/fundamentacoes-legais", {"data": data.isoformat()})
        if not res.ok:
            return res
        rows = [r for r in res.dados if r.get("codigoClassificacaoTributaria") == c]
        if not rows:
            return Resultado(
                ok=False,
                erro=Erro(
                    status=404,
                    titulo="Sem fundamentação",
                    detalhe=f"cClassTrib {c} sem fundamentação em {data}",
                ),
                fonte=res.fonte,
            )
        return Resultado(ok=True, dados=rows, fonte=res.fonte)
