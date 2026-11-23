#!/usr/bin/env bash
# Smoke test for `docker compose up`: no account, no model provider.
set -euo pipefail
API="${API:-http://localhost:8000}"
APP="${APP:-http://localhost:8501}"

curl -fsS "$API/healthz" | tee /tmp/health.json; echo
python3 - <<'PY'
import json
h = json.load(open("/tmp/health.json"))
assert h["calculadora"]["ok"], h
print("calculator", h["calculadora"]["versao"], h["calculadora"]["banco"])
PY

curl -fsS -X POST "$API/v1/calculate" -H 'content-type: application/json' \
  -d '{"data_operacao":"2026-06-15","uf":"RS","municipio":"Porto Alegre","itens":[{"ncm":"6109.10.00","valor":1000}]}' \
  > /tmp/calc.json
python3 - <<'PY'
import json
def find(o, k):
    if isinstance(o, dict):
        if k in o:
            return o[k]
        o = list(o.values())
    if isinstance(o, list):
        for v in o:
            r = find(v, k)
            if r is not None:
                return r
d = json.load(open("/tmp/calc.json"))
assert d["ok"] and find(d["dados"], "vCBS") == "9.00" and find(d["dados"], "vIBS") == "1.00", d
print("calculate: CBS 9.00, IBS 1.00 (2026 test-year rates)")
PY

curl -fsS -X POST "$API/v1/search" -H 'content-type: application/json; charset=utf-8' \
  --data-binary @- > /tmp/search.json <<'JSON'
{"pergunta": "Qual a alíquota da CBS em 2026?", "data_referencia": "2026-06-01"}
JSON
python3 - <<'PY'
import json
t = [x["citacao"] for x in json.load(open("/tmp/search.json"))["trechos"]]
print("search:", t)
assert any(c.endswith("art. 346") for c in t), t
PY

code=$(curl -s -o /dev/null -w "%{http_code}" "$APP")
echo "app HTTP $code"
[ "$code" = "200" ]
echo "smoke test passed"
