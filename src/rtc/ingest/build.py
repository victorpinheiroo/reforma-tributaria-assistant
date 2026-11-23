"""Build the processed corpus: provisions with vigência, then chunks under three strategies.

    uv run python -m rtc.ingest.build

Inputs: corpus/raw/*.htm.gz (Planalto compiled texts, pinned by sha256 in corpus/manifest.json).
Outputs in corpus/processed/:
  provisions.jsonl          one line per provision (artigo/§/inciso/alínea), with vigência
  chunks_dispositivo.jsonl  one chunk per article, split by paragraph when long (the default)
  chunks_fixo.jsonl         fixed 1000-character windows, 200 overlap (baseline)
  chunks_secao.jsonl        one chunk per section heading, capped (baseline)

Text amended by a later law is indexed once: LC 214 is read in its compiled form, so the copies
of LC 214 provisions quoted inside LC 227 are kept in provisions.jsonl but not chunked.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from rtc.ingest.parse import parse, to_dict
from rtc.ingest.vigencia import vigencia

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "corpus" / "raw"
OUT = ROOT / "corpus" / "processed"

SOURCES = [
    ("lcp214.htm.gz", "LC 214/2025", "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp214.htm"),
    ("lcp227.htm.gz", "LC 227/2026", "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp227.htm"),
    (
        "emc132.htm.gz",
        "EC 132/2023",
        "https://www.planalto.gov.br/ccivil_03/constituicao/emendas/emc/emc132.htm",
    ),
]
MAX_ARTICLE_CHARS = 1500
FIXED, OVERLAP = 1000, 200
SECTION_CAP = 4000


def provision_text(p: dict) -> str:
    label = {
        "paragrafo": lambda v: "Parágrafo único." if v == "unico" else f"§ {v}º",
        "inciso": lambda v: f"{v} -",
        "alinea": lambda v: f"{v})",
    }
    for k in ("alinea", "inciso", "paragrafo"):
        if p[k]:
            return f"{label[k](p[k])} {p['texto']}"
    return f"Art. {p['artigo']}. {p['texto']}"


def load_provisions() -> tuple[list[dict], list[dict]]:
    provs, annex_chunks = [], []
    for fname, lei, _ in SOURCES:
        ps, annex = parse(RAW / fname, lei)
        for p in ps:
            d = to_dict(p)
            base = lei  # the law whose effects clause governs this text
            art = p.artigo_origem or p.artigo if p.lei != lei else p.artigo
            sub = (p.paragrafo, p.inciso, p.alinea) if p.lei == lei else (None, None, None)
            d |= vigencia(base, art, *sub, notas=p.notas)
            d["redundante"] = p.lei.startswith("LC 214/2025 (red.")  # compiled LC 214 has it
            provs.append(d)
        by_annex = defaultdict(list)
        for title, line in annex:
            by_annex[title].append(line)
        for title, lines in by_annex.items():
            buf: list[str] = []
            for line in lines + [None]:
                if line is None or sum(len(x) for x in buf) + len(line) > MAX_ARTICLE_CHARS:
                    if buf:
                        name = "Anexo " + title.split(" ")[1].upper()
                        annex_chunks.append(
                            {
                                "citacao": f"{lei}, {name}",
                                "lei": lei,
                                "texto": f"{title}\n" + "\n".join(buf),
                                **vigencia(lei, "annex"),
                                "revogado": False,
                            }
                        )
                    buf = []
                if line is not None:
                    buf.append(line)
    return provs, annex_chunks


def chunk_dispositivo(provs: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for p in provs:
        if not p["redundante"]:
            groups[(p["lei"], p["artigo"], p["artigo_origem"])].append(p)
    chunks = []
    for (lei, art, _), ps in groups.items():
        caput = ps[0]
        head = f"{lei}, art. {art}"
        if sum(len(p["texto"]) for p in ps) <= MAX_ARTICLE_CHARS:
            parts = [ps]
        else:  # split by paragraph; caput (with its incisos) first
            parts, cur = [], []
            for p in ps:
                if p["paragrafo"] and not p["inciso"] and cur:
                    parts.append(cur)
                    cur = []
                cur.append(p)
            parts.append(cur)
        for part in parts:
            first = part[0]
            cit = first["citacao"] if first is not caput else head
            body = "\n".join(provision_text(p) for p in part)
            prefix = "" if first is caput else f"Art. {art} (caput: {caput['texto'][:200]})\n"
            chunks.append(
                {
                    "id": hashlib.sha1(f"{cit}|{first['ordem']}".encode()).hexdigest()[:12],
                    "citacao": cit,
                    "lei": lei,
                    "artigo": art,
                    "caminho": " > ".join(caput["caminho"]),
                    "texto": prefix + body,
                    "vigencia_inicio": min(
                        (p["vigencia_inicio"] for p in part if p["vigencia_inicio"]), default=None
                    ),
                    "vigencia_condicao": next(
                        (p["vigencia_condicao"] for p in part if p["vigencia_condicao"]), None
                    ),
                    "vigencia_fonte": first["vigencia_fonte"],
                    "revogado": all(p["revogado"] for p in part),
                    "dispositivos": [p["citacao"] for p in part],
                }
            )
    return chunks


def chunk_fixo(provs: list[dict]) -> list[dict]:
    chunks = []
    by_lei: dict[str, list[dict]] = defaultdict(list)
    for p in provs:
        if not p["redundante"]:
            by_lei[p["lei"]].append(p)
    for lei, ps in by_lei.items():
        text, spans = "", []
        for p in ps:
            start = len(text)
            text += provision_text(p) + "\n"
            spans.append((start, len(text), p))
        i = 0
        while i < len(text):
            window = text[i : i + FIXED]
            inside = [p for s, e, p in spans if s < i + FIXED and e > i]
            chunks.append(
                {
                    "id": hashlib.sha1(f"{lei}|{i}".encode()).hexdigest()[:12],
                    "citacao": inside[0]["citacao"],
                    "lei": lei,
                    "texto": window,
                    # a window mixes provisions: it inherits the most permissive start date
                    "vigencia_inicio": min(
                        (p["vigencia_inicio"] for p in inside if p["vigencia_inicio"]), default=None
                    ),
                    "revogado": all(p["revogado"] for p in inside),
                    "dispositivos": [p["citacao"] for p in inside],
                }
            )
            i += FIXED - OVERLAP
    return chunks


def chunk_secao(provs: list[dict]) -> list[dict]:
    chunks = []
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for p in provs:
        if not p["redundante"]:
            groups[(p["lei"], " > ".join(p["caminho"]))].append(p)
    for (lei, path), ps in groups.items():
        buf: list[dict] = []
        for p in ps + [None]:
            size = sum(len(x["texto"]) for x in buf)
            if p is None or (buf and size + len(p["texto"]) > SECTION_CAP):
                if buf:
                    chunks.append(
                        {
                            "id": hashlib.sha1(
                                f"{lei}|{path}|{buf[0]['ordem']}".encode()
                            ).hexdigest()[:12],
                            "citacao": buf[0]["citacao"],
                            "lei": lei,
                            "caminho": path,
                            "texto": (path + "\n" if path else "")
                            + "\n".join(provision_text(x) for x in buf),
                            "vigencia_inicio": min(
                                (x["vigencia_inicio"] for x in buf if x["vigencia_inicio"]),
                                default=None,
                            ),
                            "revogado": all(x["revogado"] for x in buf),
                            "dispositivos": [x["citacao"] for x in buf],
                        }
                    )
                buf = []
            if p is not None:
                buf.append(p)
    return chunks


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    provs, annex = load_provisions()
    write_jsonl(OUT / "provisions.jsonl", provs)
    for name, fn in (
        ("dispositivo", chunk_dispositivo),
        ("fixo", chunk_fixo),
        ("secao", chunk_secao),
    ):
        rows = fn(provs) + annex
        write_jsonl(OUT / f"chunks_{name}.jsonl", rows)
        print(f"chunks_{name}: {len(rows)} (annex {len(annex)})")
    print(
        f"provisions: {len(provs)} (redundant {sum(p['redundante'] for p in provs)}, "
        f"revoked {sum(p['revogado'] for p in provs)})"
    )


if __name__ == "__main__":
    main()
