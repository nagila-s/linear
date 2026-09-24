"""Detecta texto do PDF ausente no JSON e valida o patch sem mudar a classificação."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from src.pipeline.steps.image_credits import is_image_credit, strip_image_credits
from src.pipeline.steps.page_completeness import editorial_plain_text

MIN_PDF_CHARS = 80
MIN_SPAN_CHARS = 16
MIN_TOTAL_MISSING = 40
REPLACE_KEEP_RATIO = 0.75
MAX_SNIPPETS = 24
MAX_SNIPPET_CHARS = 500
MAX_PDF_IN_PROMPT = 12000
MAX_JSON_IN_PROMPT = 50000

_WS_RE = re.compile(r"\s+")
_NOISE_RE = re.compile(
    r"(shutterstock|getty\s*images|alamy|istock|acervo\s+da\s+editora|"
    r"acervo\s+pessoal|reprodu[cç][aã]o)",
    re.IGNORECASE,
)
_PAGE_NUM_RE = re.compile(r"^[\d\s.\-/]+$")


def collapse_for_diff(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").replace("\u00ad", "")).strip()


def _is_noise_span(text: str) -> bool:
    raw = (text or "").strip()
    if len(raw) < MIN_SPAN_CHARS:
        return True
    if _PAGE_NUM_RE.fullmatch(raw):
        return True
    if is_image_credit(raw):
        return True
    if _NOISE_RE.search(raw) and len(raw) < 80:
        return True
    letters = sum(1 for ch in raw if ch.isalpha())
    if letters < 8:
        return True
    return False


@dataclass
class TextGapReport:
    pdf_chars: int = 0
    json_chars: int = 0
    missing_spans: list[str] = field(default_factory=list)

    @property
    def missing_chars(self) -> int:
        return sum(len(span) for span in self.missing_spans)

    @property
    def needs_fill(self) -> bool:
        if self.pdf_chars < MIN_PDF_CHARS:
            return False
        if self.missing_chars >= MIN_TOTAL_MISSING:
            return True
        return any(len(span) >= 40 for span in self.missing_spans)


def find_missing_pdf_spans(pdf_text: str, json_text: str) -> list[str]:
    """Trechos do PDF que não aparecem (nem de forma próxima) no JSON editorial."""
    pdf_flat = collapse_for_diff(strip_image_credits(pdf_text))
    json_flat = collapse_for_diff(json_text)
    if not pdf_flat:
        return []
    if not json_flat:
        span = pdf_flat.strip()
        return [] if _is_noise_span(span) else [span[:MAX_SNIPPET_CHARS]]

    missing: list[str] = []
    sm = SequenceMatcher(None, json_flat, pdf_flat, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        pdf_chunk = pdf_flat[j1:j2].strip()
        if not pdf_chunk:
            continue
        if tag == "replace":
            json_chunk = json_flat[i1:i2]
            if SequenceMatcher(None, json_chunk, pdf_chunk).ratio() >= REPLACE_KEEP_RATIO:
                continue
        if _is_noise_span(pdf_chunk):
            continue
        missing.append(pdf_chunk[:MAX_SNIPPET_CHARS])
        if len(missing) >= MAX_SNIPPETS:
            break
    return missing


def analyze_text_gaps(page_structure: dict[str, Any] | None, pdf_text: str) -> TextGapReport:
    pdf = (pdf_text or "").strip()
    json_plain = editorial_plain_text(page_structure) if isinstance(page_structure, dict) else ""
    spans = find_missing_pdf_spans(pdf, json_plain)
    return TextGapReport(pdf_chars=len(pdf), json_chars=len(json_plain), missing_spans=spans)


def collect_tipo_fingerprint(node: Any) -> list[str]:
    """Lista de 'tipo' na ordem da árvore — a classificação editorial a preservar."""
    out: list[str] = []

    def walk(n: Any) -> None:
        if isinstance(n, dict):
            tipo = n.get("tipo")
            if isinstance(tipo, str) and tipo.strip():
                out.append(tipo.strip())
            for value in n.values():
                walk(value)
            return
        if isinstance(n, list):
            for item in n:
                walk(item)

    walk(node)
    return out


def is_subsequence(small: list[str], big: list[str]) -> bool:
    if not small:
        return True
    i = 0
    for item in big:
        if item == small[i]:
            i += 1
            if i >= len(small):
                return True
    return False


def preserves_classification(original: dict[str, Any], patched: dict[str, Any]) -> bool:
    """True se os tipos originais continuam presentes, na mesma ordem (inserções ok)."""
    if not isinstance(original, dict) or not isinstance(patched, dict):
        return False
    orig_page = str(original.get("tipo_pagina") or "").strip()
    new_page = str(patched.get("tipo_pagina") or "").strip()
    if orig_page and new_page and orig_page != new_page:
        return False
    orig_tipos = collect_tipo_fingerprint(original)
    new_tipos = collect_tipo_fingerprint(patched)
    if not orig_tipos:
        return True
    return is_subsequence(orig_tipos, new_tipos)


def build_gap_fill_prompt(
    page_structure: dict[str, Any],
    pdf_text: str,
    missing_spans: list[str],
) -> str:
    try:
        json_dump = json.dumps(page_structure, ensure_ascii=False)
    except (TypeError, ValueError):
        json_dump = str(page_structure)
    if len(json_dump) > MAX_JSON_IN_PROMPT:
        json_dump = json_dump[: MAX_JSON_IN_PROMPT - 20] + "\n...[json cortado]..."

    pdf = collapse_for_diff(pdf_text)
    if len(pdf) > MAX_PDF_IN_PROMPT:
        pdf = pdf[: MAX_PDF_IN_PROMPT - 20] + " ...[texto cortado]..."

    snippets = "\n".join(f"- {span}" for span in missing_spans[:MAX_SNIPPETS]) or "- (trechos não listados)"

    return (
        "Você corrige um JSON já linearizado de uma página de livro didático.\n"
        "Há trechos do PDF que NÃO estão no JSON. Insira esse texto no local correto.\n\n"
        "REGRAS ABSOLUTAS:\n"
        "- NÃO altere o campo \"tipo\" de nenhum bloco já existente.\n"
        "- NÃO reclassifique, não funda, não renomeie e não reordene os blocos atuais.\n"
        "- NÃO invente títulos, explicações ou conteúdo que não esteja no PDF.\n"
        "- Só complete ou insira o texto faltante. Novos blocos só se o trecho for um bloco distinto; "
        "aí use o tipo adequado (paragrafo, titulo_3, item, etc.) sem mudar os tipos já presentes.\n"
        "- Mantenha a ordem de leitura. Retorne o JSON COMPLETO da página "
        '(raiz com "tipo_pagina", "pagina", "conteudo").\n'
        "- Use string simples em \"texto\". Não marque negrito/itálico.\n\n"
        "Trechos do PDF ausentes no JSON:\n"
        f"{snippets}\n\n"
        "Texto nativo do PDF:\n"
        f"{pdf}\n\n"
        "JSON atual (preserve os tipos):\n"
        f"{json_dump}\n"
    )
