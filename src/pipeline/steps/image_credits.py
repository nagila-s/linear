"""Créditos de imagem (fotógrafo, agência, banco) não entram no JSON editorial."""

from __future__ import annotations

import re
from typing import Any

_AGENCY_RE = re.compile(
    r"\b(?:shutterstock|getty(?:\s+images)?|alamy|istock(?:photo)?|adobe\s+stock|"
    r"dreamstime|123rf|acervo\s+da\s+editora|acervo\s+pessoal|arquivo\s+da\s+editora)\b",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\w'’.\-]*")
_LABEL_RE = re.compile(
    r"(?:foto|fotografia|cr[eé]ditos?)\s*:\s*[A-ZÁÉÍÓÚÂÊÔÃÕÇ][^.\n]{1,70}",
    re.IGNORECASE,
)
_WS_RE = re.compile(r"[ \t]+")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?])")

_TEXT_KEYS = frozenset(
    {
        "texto",
        "trecho",
        "instrucao",
        "enunciado",
        "titulo",
        "titulo_quadro",
        "titulo_boxe",
        "titulo_tabela",
        "cabecalho",
        "legenda",
        "fonte",
        "contexto_pedagogico",
    }
)


def _letters(text: str) -> str:
    return "".join(ch for ch in text if ch.isalpha())


def _is_slash_credit(fragment: str) -> bool:
    raw = fragment.strip(" \t.;,-")
    if not raw or len(raw) > 90 or raw.count("/") != 1 or "," in raw:
        return False
    if re.search(r"\b(?:19|20)\d{2}\b", raw):
        return False
    left, right = (part.strip() for part in raw.split("/", 1))
    if len(_letters(left)) < 2 or len(_letters(right)) < 2:
        return False
    if _AGENCY_RE.search(raw):
        return True
    letters = _letters(raw)
    if len(letters) < 6:
        return False
    upper = sum(1 for ch in letters if ch.isupper())
    return upper / len(letters) >= 0.7


def is_image_credit(text: str) -> bool:
    """True se o trecho inteiro é crédito de foto/agência, não fonte bibliográfica."""
    raw = _WS_RE.sub(" ", (text or "").replace("\n", " ")).strip(" \t.;,-")
    if not raw or len(raw) > 120:
        return False
    if re.search(r"\b(?:19|20)\d{2}\b", raw) and not _AGENCY_RE.search(raw):
        return False
    if _AGENCY_RE.fullmatch(raw):
        return True
    if _AGENCY_RE.search(raw) and len(raw) <= 80 and raw.count(".") <= 1:
        return True
    if _is_slash_credit(raw) and len(raw) <= 80:
        return True
    label = _LABEL_RE.fullmatch(raw)
    return bool(label and len(raw.split()) <= 8)


def _word_ending_at(text: str, end: int) -> tuple[int, int] | None:
    cursor = end
    while cursor > 0 and text[cursor - 1] in " \t":
        cursor -= 1
    start = cursor
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] in "'’.-"):
        start -= 1
    word = text[start:cursor]
    if not word or not _WORD_RE.fullmatch(word):
        return None
    return start, cursor


def _words_before(text: str, end: int, limit: int) -> tuple[int, int, int] | None:
    spans: list[tuple[int, int]] = []
    cursor = end
    while len(spans) < limit:
        found = _word_ending_at(text, cursor)
        if not found:
            break
        spans.append(found)
        cursor = found[0]
    if not spans:
        return None
    return spans[-1][0], spans[0][1], len(spans)  # type: ignore[return-value]


def _words_after(text: str, start: int, limit: int) -> tuple[int, int] | None:
    i = start
    while i < len(text) and text[i] in " \t":
        i += 1
    abs_start = i
    count = 0
    end = i
    while count < limit and i < len(text):
        match = _WORD_RE.match(text, i)
        if not match:
            break
        end = match.end()
        count += 1
        i = match.end()
        if count >= limit:
            break
        if i < len(text) and text[i] in " \t":
            while i < len(text) and text[i] in " \t":
                i += 1
            continue
        break
    if count == 0:
        return None
    return abs_start, end


def _slash_credit_spans(text: str) -> list[tuple[int, int]]:
    """Nome/agência. O lado direito não engole o título em caixa-alta que vem depois."""
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r"/", text):
        left = _words_before(text, match.start(), 4)
        if not left:
            continue
        left_start, _, left_count = left
        right = _words_after(text, match.end(), max(left_count, 2))
        if not right:
            continue
        fragment = text[left_start : right[1]]
        if _is_slash_credit(fragment):
            spans.append((left_start, right[1]))
    return spans


def strip_image_credits(text: str) -> str:
    """Remove créditos de imagem embutidos numa frase, preservando o resto."""
    if not text:
        return text
    cleaned = text
    for start, end in reversed(_slash_credit_spans(cleaned)):
        cleaned = cleaned[:start] + " " + cleaned[end:]
    cleaned = _AGENCY_RE.sub(" ", cleaned)
    cleaned = _LABEL_RE.sub(" ", cleaned)
    cleaned = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", cleaned)
    cleaned = _WS_RE.sub(" ", cleaned)
    return cleaned.strip()


def _clean_text_value(key: str, value: str) -> str | None:
    if is_image_credit(value):
        return None if key == "fonte" else ""
    cleaned = strip_image_credits(value)
    if key == "fonte" and (not cleaned or is_image_credit(cleaned)):
        return None
    return cleaned


def _block_text(node: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("texto", "trecho", "legenda", "fonte"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    parts.append(item.strip())
                elif isinstance(item, dict):
                    trecho = item.get("trecho") or item.get("texto")
                    if isinstance(trecho, str) and trecho.strip():
                        parts.append(trecho.strip())
    return " ".join(parts).strip()


def omit_image_credits(node: Any) -> Any:
    """Tira créditos de imagem de campos textuais. Fonte bibliográfica permanece."""
    if isinstance(node, list):
        kept: list[Any] = []
        for item in node:
            cleaned = omit_image_credits(item)
            if isinstance(cleaned, dict) and str(cleaned.get("tipo") or "") == "fonte":
                if not _block_text(cleaned) or is_image_credit(_block_text(cleaned)):
                    continue
            if isinstance(cleaned, dict) and "trecho" in cleaned and not str(cleaned.get("trecho") or "").strip():
                continue
            kept.append(cleaned)
        return kept
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in _TEXT_KEYS and isinstance(value, str):
                out[key] = _clean_text_value(key, value)
            else:
                out[key] = omit_image_credits(value)
        return out
    return node
