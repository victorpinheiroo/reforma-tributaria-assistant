"""API without network or models: calculate replays recorded calculator answers; ask without
model credentials is a clear 503."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import rtc.api as api
from rtc.calculadora import Calculadora, ReplayTransport

HTTP = Path(__file__).parent / "fixtures" / "calculadora" / "http.json"


@pytest.fixture()
def client(monkeypatch):
    calc = Calculadora(transport=ReplayTransport(HTTP))
    monkeypatch.setattr(api, "calculadora", lambda: calc)
    with TestClient(api.app) as c:
        yield c


def test_healthz_reports_the_calculator_version(client):
    h = client.get("/healthz").json()
    assert h["ok"] and h["calculadora"]["versao"] == "1.7.2"


def test_calculate_needs_no_model(client):
    body = {
        "data_operacao": "2026-06-01",
        "uf": "RS",
        "municipio": "Porto Alegre",
        "itens": [{"ncm": "6109.10.00", "valor": 1000}],
    }
    r = client.post("/v1/calculate", json=body).json()
    assert r["ok"] and r["fonte"]["calculadora"] == "1.7.2"
    assert '"vCBS": "9.00"' in str(r).replace("'", '"')


def test_calculate_refusal_is_returned_not_raised(client):
    body = {
        "data_operacao": "2027-03-10",
        "uf": "MG",
        "municipio": "Belo Horizonte",
        "itens": [{"ncm": "84713012", "valor": 2000}],
    }
    r = client.post("/v1/calculate", json=body).json()
    assert r["ok"] is False and r["erro"]["titulo"] == "Alíquotas nominais não informadas"


def test_invalid_input_is_a_422(client):
    body = {"data_operacao": "2026-06-01", "uf": "RS", "municipio": "Porto Alegre", "itens": []}
    assert client.post("/v1/calculate", json=body).status_code == 422


def test_ask_without_model_credentials_is_503(client, monkeypatch):
    def no_creds(model):
        raise RuntimeError("no Databricks credentials")

    monkeypatch.setattr(api, "make_client", no_creds)
    api.STATE.pop("agent", None)
    r = client.post("/v1/ask", json={"pergunta": "O que é o IBS?"})
    assert r.status_code == 503 and "model provider not configured" in r.json()["detail"]
