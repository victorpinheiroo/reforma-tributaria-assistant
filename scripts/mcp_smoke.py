"""End-to-end check of rtc-tools over the real MCP protocol (stdio), against the live calculator.

    uv run python scripts/mcp_smoke.py            (calculator on localhost:8080)

Spawns `rtc-tools` as a subprocess exactly as Claude Desktop or the LangGraph agent would, lists
the tools, runs every scenario in tests/scenarios.py, and checks that a schema violation comes
back as an MCP error result, not a crash.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from scenarios import SCENARIOS  # noqa: E402


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


async def main() -> int:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "rtc.mcp_server"], cwd=str(ROOT)
    )
    failures = 0
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        init = await session.initialize()
        print(f"server: {init.server_info.name} {init.server_info.version}")
        tools = await session.list_tools()
        print("tools:", ", ".join(t.name for t in tools.tools))
        for name, sc in SCENARIOS.items():
            res = await session.call_tool(sc["tool"], sc["args"])
            out = json.loads(res.content[0].text)
            if "erro" in sc["expect"]:
                ok = out["ok"] is False and out["erro"]["titulo"] == sc["expect"]["erro"]
                shown = f"erro: {out['erro']['titulo'] if out['erro'] else None}"
            else:
                got = {k: find(out["dados"], k) for k in sc["expect"]}
                ok = out["ok"] and got == sc["expect"]
                shown = ", ".join(f"{k}={v}" for k, v in got.items())
            failures += not ok
            print(f"  {'ok ' if ok else 'XX '} {name:28} {shown}")
        bad = await session.call_tool(
            "calcular_regime_geral",
            {"data_operacao": "2026-06-01", "uf": "RS", "municipio": "Porto Alegre", "itens": []},
        )
        ok = bad.is_error
        failures += not ok
        print(f"  {'ok ' if ok else 'XX '} schema violation -> is_error={bad.is_error}")
    print(f"\n{len(SCENARIOS) + 1 - failures}/{len(SCENARIOS) + 1} checks passed over stdio")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
