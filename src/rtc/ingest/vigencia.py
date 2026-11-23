"""When each provision starts producing effects, taken from each law's own effects clause.

The rules below are transcribed from:
  LC 214/2025, art. 544 (wording given by LC 227/2026)
  LC 227/2026, art. 182 (published DOU 14.1.2026)
  EC 132/2023, art. 23 (promulgated 20.12.2023, date line of the text)
tests/test_vigencia.py checks every article number listed here against the parsed text of those
clauses, so a transcription error fails the build.

Two different things change over time and only the first is handled here:
- whether a provision is in effect at a date (this module; used as a retrieval filter);
- what a provision in effect says about each year ("em 2029, ..."): that is content, retrieved and
  applied to the reference date by the answer, never filtered out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Regra:
    inicio: date | None  # None = conditional, see `condicao`
    artigos: tuple[str, ...]  # "537-540" ranges allowed
    so_caput: tuple[str, ...] = ()  # article listed as "art. X, caput"
    paragrafos: dict | None = None  # {"450": ("1", "5")}: only these paragraphs
    exceto_paragrafos: dict | None = None  # {"450": ("1", "5")}: all but these
    condicao: str | None = None
    fonte: str = ""


LC214 = "LC 214/2025"
LC227 = "LC 227/2026"
EC132 = "EC 132/2023"

PUBLICACAO = {LC214: date(2025, 1, 16), LC227: date(2026, 1, 14), EC132: date(2023, 12, 20)}

REGRAS: dict[str, list[Regra]] = {
    LC214: [
        Regra(date(2025, 5, 1), ("537-540",), fonte="art. 544, I"),
        Regra(
            date(2025, 1, 1),
            ("35", "58", "60", "62", "266", "317", "403", "480-484", "516", "541"),
            so_caput=("58",),
            paragrafos={"60": ("3",)},
            fonte="art. 544, II",
        ),
        Regra(
            date(2027, 1, 1),
            (
                "168-171",
                "309-315",
                "444",
                "450",
                "461",
                "462",
                "467",
                "499",
                "500",
                "502",
                "504-507",
                "509-515",
                "517",
                "519-534",
                "542",
            ),
            exceto_paragrafos={"450": ("1", "5")},
            fonte="art. 544, III (red. LC 227/2026)",
        ),
        Regra(
            date(2029, 1, 1),
            ("446", "447", "449", "450", "464", "465", "474"),
            paragrafos={"450": ("1", "5")},
            fonte="art. 544, IV",
        ),
        Regra(date(2033, 1, 1), ("518", "543"), fonte="art. 544, V"),
    ],
    LC227: [
        Regra(date(2027, 1, 1), ("169",), fonte="art. 182, I, b"),
        Regra(date(2027, 1, 1), ("76",), fonte="art. 182, I, a (alínea c do inciso II)"),
        Regra(
            None,
            ("52",),
            paragrafos={"52": ("4", "5")},
            condicao="a partir da eleição do Presidente do CGIBS (LC 214/2025, art. 483, § 1º, III)",  # noqa: E501
            fonte="art. 182, II",
        ),
    ],
    EC132: [
        Regra(date(2027, 1, 1), ("3", "11"), fonte="art. 23, I"),
        Regra(date(2033, 1, 1), ("4", "5"), fonte="art. 23, II"),
    ],
}
DEFAULT = {
    LC214: (date(2026, 1, 1), "art. 544, VI"),
    LC227: (PUBLICACAO[LC227], "art. 182, III"),
    EC132: (PUBLICACAO[EC132], "art. 23, III"),
}


def _num(artigo: str) -> int:
    return int(artigo.split("-")[0].split(".")[0])


def _in(artigo: str, spec: str) -> bool:
    if not artigo[:1].isdigit():  # annexes and other non-article text
        return False
    if "-" in spec and spec.replace("-", "").isdigit():
        a, b = spec.split("-")
        return artigo.split("-")[0] == artigo and int(a) <= _num(artigo) <= int(b)
    return artigo == spec


def _matches(
    r: Regra, artigo: str, paragrafo: str | None, inciso: str | None, alinea: str | None
) -> bool:
    if not any(_in(artigo, s) for s in r.artigos):
        return False
    par = (paragrafo or "").split("-")[0] or None
    if artigo in r.so_caput and (paragrafo or inciso or alinea):
        return False
    if r.paragrafos and artigo in r.paragrafos:
        return par in r.paragrafos[artigo]
    if r.exceto_paragrafos and artigo in r.exceto_paragrafos:
        return par not in r.exceto_paragrafos[artigo]
    if r.fonte.startswith("art. 182, I, a"):  # only alínea c of inciso II of art. 76
        return inciso == "II" and alinea == "c"
    return True


def vigencia(
    lei_base: str,
    artigo: str,
    paragrafo: str | None = None,
    inciso: str | None = None,
    alinea: str | None = None,
    notas: list[str] | None = None,
) -> dict:
    """Effect start for a provision of `lei_base`, identified by the article of `lei_base` that
    carries it (for amended text, the amending article: `artigo_origem`)."""
    found = None
    for r in REGRAS.get(lei_base, []):
        if _matches(r, artigo, paragrafo, inciso, alinea):
            found = r  # later, more specific rules win
    if found:
        inicio, fonte, condicao = found.inicio, f"{lei_base}, {found.fonte}", found.condicao
    else:
        inicio, fonte = DEFAULT[lei_base]
        fonte, condicao = f"{lei_base}, {fonte}", None
    # Text inserted into LC 214 by LC 227 cannot take effect before LC 227 was published.
    if notas and inicio and any("227" in n and "Incluíd" in n for n in notas):
        if inicio < PUBLICACAO[LC227]:
            inicio, fonte = PUBLICACAO[LC227], fonte + " + LC 227/2026 (inclusão)"
    return {
        "vigencia_inicio": inicio.isoformat() if inicio else None,
        "vigencia_condicao": condicao,
        "vigencia_fonte": fonte,
    }


def em_vigor(chunk: dict, ref: date) -> bool:
    """Retrieval filter: in effect at `ref`, not revoked. Conditional provisions are kept and
    flagged by the answer, never silently treated as in force."""
    if chunk.get("revogado"):
        return False
    ini = chunk.get("vigencia_inicio")
    return ini is None or date.fromisoformat(ini) <= ref
