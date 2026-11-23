"""Parse the Planalto compiled texts into legal provisions (artigo, parágrafo, inciso, alínea).

Rules taken from how Planalto publishes compiled law:
- superseded wording is kept but struck through (`text-decoration: line-through` or <strike>);
  it is dropped here, only the current wording survives;
- amendment notes such as "(Redação dada pela Lei Complementar nº 227, de 2026)" or
  "(Incluído pela ...)" are moved out of the text into `notas`;
- a provision whose whole text is "(Revogado ...)" is kept with `revogado=True` so retrieval can
  exclude it while the corpus still records it;
- in an amendment (EC 132/2023), articles quoted between quotes are the new wording of the
  Constitution or of the ADCT and are attributed to them, not to the amendment itself;
- body ends at "Brasília, ..."; the annexes that follow (LC 214 food lists, etc.) are kept as
  annex lines.
"""

from __future__ import annotations

import gzip
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup, Tag

ART = re.compile(
    r'^[“"]?\s*Art\.\s*(\d+(?:\.\d+)?)\s*(?:º|o)?\s*(-[A-Z])?\s*[.ºo]?\s*[-–—]?\s*(.*)$'
)
PAR = re.compile(
    r"^[“\"]?\s*(?:§\s*(\d+)\s*(?:º|o)?\s*(-[A-Z])?\.?|(Parágrafo único)\.?)\s*[-–—]?\s*(.*)$", re.I
)
INC = re.compile(r"^[“\"]?\s*([IVXLC]+)\s*[-–—]\s*(.*)$")
ALI = re.compile(r"^[“\"]?\s*([a-z])\)\s*(.*)$")
HEAD = re.compile(
    r"^(LIVRO|TÍTULO|CAPÍTULO|Seção|SEÇÃO|Subseção|SUBSEÇÃO)\s+([IVXLC]+|ÚNIC[OA]|\w+)\b", re.U
)
NOTE = re.compile(
    r"\((?:Redação dada|Incluíd[oa]|Acrescid[oa]|Revogad[oa]|Vide|Produção de efeito|Vigência|"
    r"Regulamento|Promulgação|Renumerad[oa])[^)]*\)",
    re.I,
)
REVOKED = re.compile(r"^\s*(?:[^()]*\s)?\(?\s*revogad[oa]", re.I)
DOTS = re.compile(r"^[.\s…\"”“(NR)]*$")
AMENDS = re.compile(r"(?:^|[.\s])(?:A|O|As|Os)\s+(.+?),?\s+passa(?:m)?\s+a\s+vigorar", re.I)
ONLY_DOTS_TEXT = re.compile(r"^[.…\s\"”“A-Z]{0,3}[.…]{5,}.*$")


def short_name(name: str) -> str:
    """'Lei Complementar nº 123, de 14 de dezembro de 2006' -> 'LC 123/2006'."""
    n = name.strip()
    if "Constituição Federal" in n:
        return "CF"
    if "Disposições Constitucionais Transitórias" in n:
        return "ADCT"
    m = re.search(
        r"(Lei Complementar|Lei|Decreto-Lei|Decreto|Medida Provisória)\s+n[ºo°]\s*([\d.\-]+).*?(\d{4})",  # noqa: E501
        n,
    )
    if m:
        kind = {
            "Lei Complementar": "LC",
            "Lei": "Lei",
            "Decreto-Lei": "DL",
            "Decreto": "Decreto",
            "Medida Provisória": "MP",
        }[m.group(1)]
        return f"{kind} {m.group(2)}/{m.group(3)}"
    return n[:40]


@dataclass
class Provision:
    lei: str  # "LC 214/2025", "CF (EC 132/2023)", ...
    artigo: str  # "26", "156-A"
    paragrafo: str | None = None  # "1", "unico"
    inciso: str | None = None
    alinea: str | None = None
    texto: str = ""
    caminho: list[str] = field(default_factory=list)  # LIVRO I > TÍTULO II > ...
    notas: list[str] = field(default_factory=list)
    revogado: bool = False
    ordem: int = 0
    artigo_origem: str | None = None  # article of the parsed law that carries it

    @property
    def citacao(self) -> str:
        parts = [f"art. {self.artigo}"]
        if self.paragrafo:
            if self.paragrafo == "unico":
                parts.append("parágrafo único")
            else:
                num, _, suf = self.paragrafo.partition("-")
                parts.append(f"§ {num}º" + (f"-{suf}" if suf else ""))
        if self.inciso:
            parts.append(f"inciso {self.inciso}")
        if self.alinea:
            parts.append(f"alínea {self.alinea}")
        return f"{self.lei}, " + ", ".join(parts)


def _struck(el: Tag) -> bool:
    for node in [el, *el.parents]:
        if not isinstance(node, Tag):
            continue
        if node.name in ("strike", "s", "del"):
            return True
        if "line-through" in (node.get("style") or "").replace(" ", "").lower():
            return True
    return False


def paragraphs(html: str) -> list[str]:
    """Visible paragraph texts in order, with struck-through wording removed."""
    soup = BeautifulSoup(html, "lxml")
    struck = [
        el
        for el in soup.find_all(True)
        if el.name in ("strike", "s", "del")
        or "line-through" in (el.get("style") or "").replace(" ", "").lower()
    ]
    for el in struck:
        if el.attrs is not None:  # not already removed with a struck ancestor
            el.decompose()
    out = []
    for p in soup.find_all("p"):
        if _struck(p):
            continue
        t = re.sub(r"\s+", " ", p.get_text(" ", strip=True)).strip()
        t = t.replace(" ,", ",").replace(" .", ".").replace(" ;", ";").replace(" :", ":")
        if t:
            out.append(t)
    return out


def read_html(path: Path) -> str:
    data = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    return data.decode("cp1252", errors="replace")


def parse(path: Path, lei: str):
    """Return (provisions, annex_lines).

    Text quoted after "A Lei X passa a vigorar com..." is attributed to "X (red. <lei>)" until
    the next unquoted article of the law being parsed.
    """
    paras = paragraphs(read_html(path))
    provisions: list[Provision] = []
    annex: list[tuple[str, str]] = []
    heads: dict[str, str] = {}
    order = ["LIVRO", "TÍTULO", "CAPÍTULO", "SEÇÃO", "SUBSEÇÃO"]
    cur: Provision | None = None
    target: str | None = None  # law being amended by the current article
    last_own = 0
    current_own = ""
    pending_head: str | None = None
    in_body = False
    annex_title: str | None = None

    for t in paras:
        if not in_body:
            if ART.match(t):
                in_body = True
            else:
                continue
        if annex_title is not None:  # after "Brasília, ...": annexes
            if t.startswith("ANEXO"):
                annex_title = t
            elif annex_title:
                annex.append((annex_title, t))
            continue
        if t.startswith("Brasília,"):
            annex_title = ""  # body over; wait for "ANEXO"
            continue
        if DOTS.match(t):
            continue
        notes = NOTE.findall(t)
        clean = NOTE.sub("", t).strip(" ;")
        quoted = t.lstrip().startswith(("“", '"'))

        m = HEAD.match(clean)
        if m and len(clean) < 60:
            level = m.group(1).upper().replace("SECAO", "SEÇÃO")
            pending_head = level
            heads[level] = clean
            for lower in order[order.index(level) + 1 :] if level in order else []:
                heads.pop(lower, None)
            continue
        if pending_head and clean.isupper() and not ART.match(clean):
            heads[pending_head] = f"{heads[pending_head]} - {clean}"
            pending_head = None
            continue
        pending_head = None

        if m := ART.match(clean):
            artigo = m.group(1) + (m.group(2) or "")
            num = int(m.group(1).split(".")[0])
            # Inside an amendment block, an unquoted article is still amended text unless it is
            # the next article of the law being parsed (Planalto omits some opening quotes).
            own = not quoted and (target is None or num in (last_own + 1, last_own))
            if own:
                a = AMENDS.search(" " + m.group(3))
                target = short_name(a.group(1)) if a else None
                lei_now = lei
                last_own = num
            else:
                lei_now = f"{target} (red. {lei})" if target else lei
            origem = artigo if own else (current_own or None)
            if own:
                current_own = artigo
            cur = Provision(
                lei=lei_now,
                artigo=artigo,
                artigo_origem=origem,
                texto=m.group(3).strip(),
                caminho=[heads[k] for k in order if k in heads],
                notas=notes,
            )
        elif cur is None:
            continue
        elif m := PAR.match(clean):
            par = "unico" if m.group(3) else m.group(1) + (m.group(2) or "")
            cur = Provision(
                lei=cur.lei,
                artigo=cur.artigo,
                paragrafo=par,
                texto=m.group(4).strip(),
                caminho=cur.caminho,
                notas=notes,
                artigo_origem=cur.artigo_origem,
            )
        elif m := INC.match(clean):
            cur = Provision(
                lei=cur.lei,
                artigo=cur.artigo,
                paragrafo=cur.paragrafo,
                inciso=m.group(1),
                texto=m.group(2).strip(),
                caminho=cur.caminho,
                notas=notes,
                artigo_origem=cur.artigo_origem,
            )
        elif (m := ALI.match(clean)) and cur.inciso:
            cur = Provision(
                lei=cur.lei,
                artigo=cur.artigo,
                paragrafo=cur.paragrafo,
                inciso=cur.inciso,
                alinea=m.group(1),
                texto=m.group(2).strip(),
                caminho=cur.caminho,
                notas=notes,
                artigo_origem=cur.artigo_origem,
            )
        else:
            # continuation of the previous provision (wrapped text, quoted tables)
            provisions[-1].texto += " " + clean
            provisions[-1].notas += notes
            continue
        cur.texto = cur.texto.strip(' "”“')
        if ONLY_DOTS_TEXT.match(cur.texto) or not cur.texto.strip(". …"):
            continue  # unchanged-text placeholder inside an amendment
        cur.revogado = bool(REVOKED.match(cur.texto)) or (
            not cur.texto and any("revogad" in n.lower() for n in notes)
        )
        cur.ordem = len(provisions)
        provisions.append(cur)
    return _fill_revoked_gaps(provisions, lei), annex


def _fill_revoked_gaps(provisions: list[Provision], lei: str) -> list[Provision]:
    """An article revoked as a whole is struck in full and followed by a bare "(Revogado ...)"
    paragraph that carries no number. Record each gap in the law's own numbering as revoked."""
    out: list[Provision] = []
    last = 0
    for p in provisions:
        if p.lei == lei and not (p.paragrafo or p.inciso or p.alinea):
            n = int(p.artigo.split("-")[0].split(".")[0])
            for gap in range(last + 1, n):
                out.append(
                    Provision(
                        lei=lei,
                        artigo=str(gap),
                        texto="(Revogado)",
                        revogado=True,
                        caminho=p.caminho,
                        notas=["texto riscado no compilado"],
                    )
                )
            last = max(last, n)
        out.append(p)
    for i, p in enumerate(out):
        p.ordem = i
    return out


def to_dict(p: Provision) -> dict:
    return {**asdict(p), "citacao": p.citacao}
