"""Verification of a drafted answer, before it reaches the user.

Three checks, the first two deterministic:

1. Origin of numbers. Every number in the answer (amounts, rates, percentages, years, dates)
   must appear in a source the answer is allowed to use: a calculator result, the text of a law
   excerpt the answer cites, the user's own question, or the reference date. Article and
   paragraph numbers, law identifiers and citation markers are not claims and are skipped.
   A number without an origin blocks the answer.
2. Vigência. A cited excerpt that is not in effect on the reference date may only be cited by an
   answer that says so (outcome "nao_vigente", or a sentence that states when it applies).
3. Support. Each sentence that cites [n] must be supported by excerpt n (LLM judge, see
   `support_check`); reported and used to trigger a repair, never to invent a fix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

# Things that look like numbers but are identifiers, not claims.
IDENTIFIERS = re.compile(
    r"(?:\[T?\d+\])"  # citation markers
    r"|(?:\b(?:arts?|artigo)\.?\s*\d+(?:-[A-Z])?(?:\s*(?:,|e|a)\s*\d+(?:-[A-Z])?)*)"  # art. 26, arts. 31 a 35
    r"|(?:§+\s*\d+[ºo°]?(?:-[A-Z])?)"  # § 1º
    r"|(?:\b(?:LC|EC|Lei Complementar(?: nº)?|Emenda Constitucional(?: nº)?|Lei(?: nº)?|Decreto(?: nº)?)\s*\d[\d.]*(?:/\d{4})?(?:,\s*de\s*\d{4})?)"
    r"|(?:\bAnexo\s+[IVXL]+)"
    r"|(?:\b(?:NCM|NBS|cClassTrib|CST|código|codigo)\s*[\d.]+)"
    r"|(?:\bid\s*\d+)",
    re.I,
)
NUMBER = re.compile(
    r"(?<![\w/])(?:R\$\s*)?-?\d{1,3}(?:\.\d{3})+(?:,\d+)?%?|(?<![\w/])(?:R\$\s*)?-?\d+(?:[,.]\d+)?%?"
)
DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b")
YEARS = range(1988, 2101)


def _to_decimal(tok: str) -> Decimal | None:
    t = tok.replace("R$", "").replace("%", "").strip()
    if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+(?:,\d+)?", t):  # 1.234,56
        t = t.replace(".", "").replace(",", ".")
    else:
        t = t.replace(",", ".")
    try:
        return Decimal(t).normalize()
    except InvalidOperation:
        return None


def numbers_in(text: str) -> list[tuple[str, Decimal]]:
    """Claims-bearing numbers of a text, with their canonical value."""
    text = IDENTIFIERS.sub(" ", text)
    out = []
    for m in DATE.finditer(text):
        g = m.groups()
        d, mth, y = (g[0], g[1], g[2]) if g[0] else (g[5], g[4], g[3])
        out += [
            (m.group(0), Decimal(int(y))),
            (m.group(0), Decimal(int(mth))),
            (m.group(0), Decimal(int(d))),
        ]
    text = DATE.sub(" ", text)
    for m in NUMBER.finditer(text):
        v = _to_decimal(m.group(0))
        if v is not None:
            out.append((m.group(0).strip(), v))
    return out


def values_in(obj) -> set[Decimal]:
    """Every number inside a JSON value (calculator results), as canonical decimals."""
    found: set[Decimal] = set()
    if isinstance(obj, dict):
        for v in obj.values():
            found |= values_in(v)
    elif isinstance(obj, list):
        for v in obj:
            found |= values_in(v)
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        found.add(Decimal(str(obj)).normalize())
    elif isinstance(obj, str):
        found |= {v for _, v in numbers_in(obj)}
        d = _to_decimal(obj)
        if d is not None:
            found.add(d)
    return found


def _close(v: Decimal, pool: set[Decimal]) -> bool:
    if v in pool:
        return True
    # percent written as a fraction or vice versa (0.9 vs 0,90%), and 2-decimal rounding
    return any(abs(v - p) < Decimal("0.005") for p in pool)


@dataclass
class Report:
    sem_origem: list[str] = field(default_factory=list)
    vigencia: list[str] = field(default_factory=list)
    sem_suporte: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.sem_origem or self.vigencia or self.sem_suporte)

    def feedback(self) -> str:
        parts = []
        if self.sem_origem:
            parts.append(
                "Números sem origem nas fontes: "
                + ", ".join(self.sem_origem)
                + ". Remova-os ou use exatamente os valores das fontes."
            )
        if self.vigencia:
            parts += self.vigencia
        if self.sem_suporte:
            parts.append(
                "Frases não sustentadas pela fonte citada: " + " | ".join(self.sem_suporte)
            )
        return "\n".join(parts)


NOT_YET = re.compile(
    r"(a partir de|somente em|só (?:vale|produz|se aplica)|ainda não|não (?:está|é|se aplica|vale)[^.]*(?:vigente|vigor|aplica))",
    re.I,
)


def check_numbers(
    resposta: str,
    pergunta: str,
    ref: str,
    cited_texts: list[str],
    tool_results: list,
    extra_dates: list[str] = (),
) -> list[str]:
    pool: set[Decimal] = set()
    for t in cited_texts:
        pool |= {v for _, v in numbers_in(t)}
    for r in tool_results:
        pool |= values_in(r)
    pool |= {v for _, v in numbers_in(pergunta)}
    for iso in [ref, *extra_dates]:  # reference date and the vigência dates shown with sources
        d = date.fromisoformat(iso)
        pool |= {Decimal(d.year), Decimal(d.month), Decimal(d.day)}
    missing = []
    for tok, v in numbers_in(resposta):
        if not _close(v, pool):
            missing.append(tok)
    return list(dict.fromkeys(missing))


def check_vigencia(resposta: str, desfecho: str, ref: str, cited: list[dict]) -> list[str]:
    problems = []
    refd = date.fromisoformat(ref)
    for c in cited:
        ini = c.get("vigencia_inicio")
        if ini and date.fromisoformat(ini) > refd and desfecho != "nao_vigente":
            if not NOT_YET.search(resposta):
                problems.append(
                    f"{c['citacao']} só produz efeitos a partir de {ini}, depois da data "
                    f"de referência {ref}; a resposta não pode tratá-lo como vigente."
                )
            elif desfecho == "resposta" and re.match(r"\s*(sim|pode|é possível)\b", resposta, re.I):
                problems.append(
                    f"A resposta afirma que é possível, mas a regra específica "
                    f"({c['citacao']}) só vale a partir de {ini}; na data {ref} ela não "
                    "se aplica. Diga isso primeiro."
                )
    return problems


ABBREV = re.compile(r"\b(arts?|inc|al|n|nº|p|pág|Lei|LC|EC|Dec)\.(?=\s)", re.I)
SENTINEL = "⁣"  # invisible separator, never in legal text


def split_sentences(text: str) -> list[str]:
    """Sentence split that does not break legal abbreviations ("art. 169", "arts. 31 a 35")."""
    protected = ABBREV.sub(lambda m: m.group(1) + SENTINEL, text)
    parts = re.split(r"(?<=[.!?])\s+", protected)
    return [x.replace(SENTINEL, ".").strip() for x in parts if x.strip()]


def sentences_with_citations(resposta: str) -> list[tuple[str, list[int]]]:
    out = []
    for sent in split_sentences(resposta):
        refs = [int(n) for n in re.findall(r"\[(\d+)\]", sent)]
        if refs:
            out.append((sent.strip(), refs))
    return out


def support_check(
    llm, sentences: list[tuple[str, list[int]]], excerpts: dict[int, str], prompt
) -> list[str]:
    """Sentences whose cited excerpts do not support them, per the LLM judge."""
    from pydantic import BaseModel

    from rtc.llm import Message

    class Item(BaseModel):
        i: int
        sustentada: bool

    class JudgeOut(BaseModel):
        itens: list[Item]

    items = [(s, refs) for s, refs in sentences if any(r in excerpts for r in refs)]
    if not items:
        return []
    blocks = []
    for k, (s, refs) in enumerate(items, start=1):
        cites = "\n".join(f"  [{r}] {excerpts[r][:1500]}" for r in refs if r in excerpts)
        blocks.append(f"{k}. Frase: {s}\n  Trechos citados:\n{cites}")
    system = prompt.system.format(itens="\n\n".join(blocks))
    r = llm.complete(
        [Message(role="system", content=system), Message(role="user", content="Avalie os itens.")],
        JudgeOut,
        None,
        prompt.key,
    )
    if not r.parsed:
        return []  # judge unavailable: report nothing rather than block on noise
    verdict = {it["i"]: it["sustentada"] for it in r.parsed["itens"]}
    return [items[k - 1][0] for k in verdict if not verdict[k] and 0 < k <= len(items)]


def judge_excerpt(citacao: str, texto: str, vigencia_inicio: str | None) -> str:
    """What the judge sees for each excerpt: which provision it is and when it takes effect."""
    vig = f" (produz efeitos a partir de {vigencia_inicio})" if vigencia_inicio else ""
    return f"{citacao}{vig}: {texto}"
