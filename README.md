# reforma-tributaria-assistant

Brazil is replacing five consumption taxes with a dual VAT (CBS + IBS) between 2026 and 2033, one
of the largest VAT transitions in the world. This assistant answers questions with the exact legal
article and computes amounts by calling the Federal Revenue's official open-source tax engine,
never by letting the model do the math.

> Status: milestone 2. `rtc-tools`, an MCP server over the official calculator (pinned 1.7.2),
> passes 14/14 checks over stdio against the live calculator; tests replay recorded answers, so CI
> needs no Java. See [docs/PLAN.md](docs/PLAN.md).
>
> Not tax advice: answers come from official documents and tools and do not replace an accountant.

## rtc-tools: the official calculator as an MCP server

Five tools, each requiring the operation date: `calcular_regime_geral`, `consultar_ncm`,
`consultar_classificacao`, `consultar_aliquota`, `consultar_fundamentacao`. Every result is
`{ok, dados | erro, fonte}`; `fonte` carries the calculator and database versions, the endpoint
and the exact request, so any number can be traced to the call that produced it. Refusals from
the calculator (no reference rate for 2027 yet, Imposto Seletivo data missing) come back as
`erro`, never as a made-up number.

```bash
scripts/setup_calculadora.sh run          # official calculator on :8080 (portable JDK 25 in tools/)
uv run rtc-tools                          # MCP server over stdio
uv run python scripts/mcp_smoke.py        # 14 end-to-end checks over the protocol
```

Use it from any MCP client, e.g. Claude Desktop (`claude_desktop_config.json`):

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
