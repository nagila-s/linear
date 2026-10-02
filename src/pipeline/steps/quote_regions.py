"""Regiões entre aspas no texto nativo do PDF e reinserção no JSON editorial."""

from __future__ import annotations

import re
from typing import Any

from src.pipeline.steps.page_completeness import editorial_plain_text
from src.pipeline.steps.pdf_text_styles import PageTextStyles, TextRun

_QUOTE_PAIRS: dict[str, str] = {
    "\u201c": "\u201d",
    "\u201e": "\u201c",
    "\u00ab": "\u00bb",
    '"': '"',
}
_QUOTE_CHARS = frozenset(_QUOTE_PAIRS.keys()) | frozenset(_QUOTE_PAIRS.values())
_WS_RE = re.compile(r"\s+")
MIN_QUOTE_CHARS = 40
_DIDACTIC_TIPOS = frozenset(
    {"atividade", "questao", "quadro", "boxe", "boxe_complementar", "tabela"}
)


def collapse_quotes(text: str) -> str:
    s = (text or "").replace("\u00ad", "")
    out: list[str] = []
    for ch in s:
        out.append('"' if ch in _QUOTE_CHARS else ch)
    return _WS_RE.sub(" ", "".join(out)).strip().casefold()


def extract_quote_regions(text: str, *, min_chars: int = MIN_QUOTE_CHARS) -> list[str]:
    """Blocos do glifo de abertura ao de fechamento, inclusive várias linhas."""
    raw = text or ""
    if not raw:
        return []
    regions: list[str] = []
    seen: set[str] = set()
    i = 0
    n = len(raw)
    while i < n:
        closer = _QUOTE_PAIRS.get(raw[i])
        if closer is None:
            i += 1
            continue
        j = raw.find(closer, i + 1)
        if j < 0:
            i += 1
            continue
        inner = raw[i + 1 : j].strip()
        if len(_WS_RE.sub(" ", inner)) >= min_chars:
            region = raw[i : j + 1].strip()
            key = collapse_quotes(region)
            if key and key not in seen:
                seen.add(key)
                regions.append(region)
        i = j + 1
    return regions


def extract_quote_regions_from_runs(runs: list[TextRun], *, min_chars: int = MIN_QUOTE_CHARS) -> list[str]:
    return extract_quote_regions("".join(run.text for run in runs), min_chars=min_chars)


def quote_region_present(region: str, editorial: str) -> bool:
    needle = collapse_quotes(region)
    if not needle:
        return True
    hay = collapse_quotes(editorial)
    if needle in hay:
        return True
    inner = collapse_quotes(region.strip().strip('"' + "".join(_QUOTE_CHARS)))
    if len(inner) >= 24 and inner in hay:
        return True
    words = inner.split()
    if len(words) >= 8:
        probe = " ".join(words[:8])
        if probe in hay:
            return True
    return False


def _block_tipo(*, literary: bool, page_structure: dict[str, Any]) -> str:
    if literary:
        return "paragrafo"
    tipos: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            tipo = node.get("tipo")
            if isinstance(tipo, str) and tipo.strip():
                tipos.append(tipo.strip())
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(page_structure)
    if any(t in _DIDACTIC_TIPOS for t in tipos):
        return "titulo_4"
    if "titulo_4" in tipos:
        return "titulo_4"
    return "titulo_4"


def _insert_index(conteudo: list[Any], region: str, pdf_text: str) -> int:
    pdf_flat = collapse_quotes(pdf_text)
    needle = collapse_quotes(region)[:48]
    pos = pdf_flat.find(needle) if needle else -1
    if pos < 0:
        return len(conteudo)
    prefix = pdf_flat[:pos]
    last = 0
    for i, block in enumerate(conteudo):
        snippet = collapse_quotes(editorial_plain_text(block) if isinstance(block, dict) else str(block or ""))
        if snippet and snippet[:36] in prefix:
            last = i + 1
    return last


def restore_missing_quote_regions(
    page_structure: dict[str, Any] | None,
    regions: list[str],
    *,
    pdf_text: str = "",
    literary: bool = False,
) -> dict[str, Any] | None:
    """Insere citações do PDF que a IA omitiu, sem reescrever blocos existentes."""
    if not isinstance(page_structure, dict):
        return page_structure
    if not regions:
        return page_structure
    conteudo = page_structure.get("conteudo")
    if not isinstance(conteudo, list):
        return page_structure

    editorial = editorial_plain_text(page_structure)
    missing = [region for region in regions if not quote_region_present(region, editorial)]
    if not missing:
        return page_structure

    tipo = _block_tipo(literary=literary, page_structure=page_structure)
    out = list(conteudo)
    acc_editorial = editorial
    pdf = pdf_text or ""
    for region in missing:
        if quote_region_present(region, acc_editorial):
            continue
        idx = _insert_index(out, region, pdf)
        block = {"tipo": tipo, "texto": region}
        out.insert(idx, block)
        acc_editorial = f"{acc_editorial} {region}"

    if out is conteudo:
        return page_structure
    updated = dict(page_structure)
    updated["conteudo"] = out
    return updated


def restore_quotes_from_page_styles(
    page_structure: dict[str, Any] | None,
    page_styles: PageTextStyles | None,
    *,
    pdf_text: str = "",
    literary: bool = False,
) -> dict[str, Any] | None:
    if page_styles is None or not page_styles.runs:
        regions = extract_quote_regions(pdf_text)
    else:
        regions = extract_quote_regions_from_runs(page_styles.runs)
        if pdf_text:
            extra = extract_quote_regions(pdf_text)
            seen = {collapse_quotes(r) for r in regions}
            for region in extra:
                key = collapse_quotes(region)
                if key not in seen:
                    regions.append(region)
                    seen.add(key)
    return restore_missing_quote_regions(
        page_structure,
        regions,
        pdf_text=pdf_text or ("".join(r.text for r in page_styles.runs) if page_styles else ""),
        literary=literary,
    )
