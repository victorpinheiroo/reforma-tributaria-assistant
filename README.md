# reforma-tributaria-assistant

Brazil is replacing five consumption taxes with a dual VAT (CBS + IBS) between 2026 and 2033, one
of the largest VAT transitions in the world. This assistant answers questions with the exact legal
article and computes amounts by calling the Federal Revenue's official open-source tax engine,
never by letting the model do the math.

> Not tax advice: answers come from official documents and tools and do not replace an accountant.

## Results

62 end-to-end questions written before the agent ran on them (expected values taken from the
official calculator called directly, expected articles found by reading the law), 8 free
Databricks-hosted models available, `qwen3.5-122b` used.

| | |
| --- | --- |
| End to end | **52/62 (84%)** |
| Safety outcomes: no official number for 2027+, ask for the operation date, rule not yet in effect, out of scope, not found | **15/15** |
| Wrong amounts shown to the user | **0** (4 numeric misses all ended with no number: 3 routing, 1 blocked) |
| Verifier on 47 mistakes seeded into real answers | **44/47**; unsourced or altered numbers **32/32, 0 false alarms** |
| Retrieval, golden set committed before the retriever | 22/26 article hits in the top 5; vigência filter: 2/2 → 0/2 rules cited before they take effect |
| MCP server over the official calculator | 14/14 checks over stdio |

Every golden set was committed before the code it measures (see git history and
[docs/PLAN.md](docs/PLAN.md), which also lists every miss and every change made after a run).

## How it works

```
question
   │
router (LLM, structured) ─► out of scope ───────────────────────► decline + disclaimer
   │                    ─► calculation with no date ─────────────► ask for the date (deterministic)
   ├─► law: BM25 + embeddings ─► RRF ─► vigência filter at the reference date ─► reranker
   ├─► tools: official calculator over MCP (rtc-tools), native tool calling
   └─► both
            │
         synthesis: cites law excerpts [n] and calculator results [Tn]
            │
         verify: every number has an origin · cited rules are in effect · citations support
            ├─ ok ─────────────────► answer, with sources and the exact calculator request
            ├─ problems ───────────► rewrite once with the exact problems
            └─ still unsourced ────► blocked: the user gets the reason, never the number
```

- **Numbers only from the calculator or the cited law.** Every amount, rate, percentage or date
  in an answer must appear in a calculator result, a cited excerpt or the user's question;
  otherwise the answer is rewritten once and then blocked. The model may not even add CBS and
  IBS: the calculator returns them separately, so a model-made total is blocked.
- **Time is first-class.** Each of the 6,977 legal provisions carries the date it starts producing
  effects, transcribed from the law's own effects clauses (LC 214 art. 544, LC 227 art. 182, EC 132
  art. 23) and tested against them. Retrieval filters by the reference date; a better-matching rule
  that only applies later is shown to the writer as "not in effect yet" instead of being hidden.
- **2027 and later have no official reference rate yet.** The calculator refuses without one; the
  assistant says so and gives no number, or computes with rates the user states and labels them
  as the user's hypothesis.

## Run it

```bash
docker compose up --build        # official calculator (Java 25, built from source) + API + app
```

- App: http://localhost:8501 · API: http://localhost:8000
- No account needed for `POST /v1/search` (law with vigência) and `POST /v1/calculate`
  (official calculator):

```bash
curl -X POST localhost:8000/v1/calculate -H 'content-type: application/json' \
  -d '{"data_operacao":"2026-06-15","uf":"RS","municipio":"Porto Alegre","itens":[{"ncm":"6109.10.00","valor":1000}]}'
```

- `POST /v1/ask` (the agent) needs a model provider:
  `DATABRICKS_HOST=... DATABRICKS_TOKEN=... docker compose up`.

## rtc-tools: the official calculator as an MCP server

Five tools, each requiring the operation date: `calcular_regime_geral`, `consultar_ncm`,
`consultar_classificacao`, `consultar_aliquota`, `consultar_fundamentacao`. Every result is
`{ok, dados | erro, fonte}`; `fonte` carries the calculator and database versions, the endpoint
and the exact request. Municipality names are resolved to IBGE codes by the tool, never by the
model. Calculator refusals come back as `erro`, never as a made-up number.

```json
{
  "mcpServers": {
    "rtc-tools": {
      "command": "uv",
      "args": ["--directory", "/path/to/reforma-tributaria-assistant", "run", "rtc-tools"]
    }
  }
}
```

## Develop and reproduce

```bash
uv sync --group app
scripts/setup_calculadora.sh run          # official calculator 1.7.2 on :8080 (portable JDK 25)
uv run pytest                             # 54 tests, no network: calculator answers are replayed
uv run python -m rtc.ingest.build         # corpus/processed from corpus/raw (pinned by sha256)
uv run python -m rtc.retrieval_eval       # evals/results/retrieval.md
uv run python -m rtc.qa_eval              # evals/results/qa.md (needs Databricks auth)
uv run python -m rtc.verify_eval          # evals/results/verify.md
uv run python scripts/mcp_smoke.py        # MCP over stdio against the live calculator
```

Pinned versions: calculator `receitafederal/calculadora-rtc-regime-regular` 1.7.2 (database V0073,
2026-11-09); law texts from Planalto retrieved 2026-11-23 (`corpus/manifest.json`).

## Layout

```
src/rtc/
  calculadora.py   typed client: validation before the call, IBGE codes, record/replay
  mcp_server.py    rtc-tools (official MCP SDK)
  ingest/          Planalto HTML -> provisions with vigência -> chunks (3 strategies)
  retrieve/        BM25, dense (multilingual-e5-small), RRF, reranker, vigência filter
  graph.py         LangGraph agent
  verify.py        number origin, vigência, citation support
  api.py           FastAPI
  *_eval.py        evaluations
app/               Streamlit (renders the API only)
prompts/           versioned prompts (router, tools, synth, judge)
evals/             golden sets and results
docker/            the official calculator's image
```

## Known limits

Listed with evidence in [docs/PLAN.md](docs/PLAN.md): the router sometimes sends a lookup to the
law instead of the calculator (q15, q29, q30) or the reverse (q02); "cashback" is not a word the
law uses and retrieval misses it; the citation judge is an LLM and is noisy (11/14 on seeded
citation errors). Simples Nacional's separate calculator is not wired in.
