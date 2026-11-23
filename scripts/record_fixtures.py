"""Record the calculator's HTTP answers for the MCP tests (needs the calculator on :8080).

    uv run python scripts/record_fixtures.py

Runs every scenario in tests/scenarios.py through the real client with a recording transport.
Re-run after bumping the calculator version: the diff of tests/fixtures/calculadora/http.json is
exactly what changed in the official answers.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from scenarios import SCENARIOS, run  # noqa: E402

from rtc.calculadora import Calculadora, RecordingTransport  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "calculadora" / "http.json"


def main() -> None:
    if OUT.exists():
        OUT.unlink()  # start clean so removed scenarios do not linger
    calc = Calculadora(transport=RecordingTransport(OUT))
    for name, sc in SCENARIOS.items():
        res = run(calc, sc)
        status = "ok" if res.ok else f"erro {res.erro.status}: {res.erro.titulo}"
        print(f"{name:32} {status}")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
