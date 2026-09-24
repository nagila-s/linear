"""Merge de estilos tipográficos do PDF no JSON editorial da LLM."""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from src.pipeline.steps.pdf_text_styles import FONT_STYLES, PageTextStyles, TextRun

logger = logging.getLogger(__name__)

STYLE_KEYS = frozenset(
    {
        "texto",
        "trecho",
        "instrucao",
        "titulo_quadro",
        "titulo_boxe",
        "titulo_tabela",
        "cabecalho",
    }
)

# Não aplicar overlay de fonte sobre estas marcas visuais.
VISUAL_STYLES = frozenset({"circulado", "sublinhado", "tachado"})

_QUOTE_CHARS = frozenset("\"'“”„‟«»‹›‚‘’‛")
_QUOTE_SENTINEL = "\u0001"
_DASH_RE = re.compile(r"[\u2010-\u2015\u2212\-]+")
_WS_RE = re.compile(r"\s+")
_LIGATURES = str.maketrans(
    {
        "\ufb00": "ff",
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
        "\ufb05": "st",
        "\ufb06": "st",
    }
)

MIN_FUZZY_RATIO = 0.90
MIN_FUZZY_RATIO_SHORT = 0.95
MIN_FUZZY_NEEDLE = 4
MIN_SCANNED_CHARS = 20


@dataclass
class MergeStats:
    json_chars: int = 0
    aligned_chars: int = 0
    fields_total: int = 0
    fields_aligned: int = 0

    @property
    def coverage(self) -> float:
        if self.json_chars <= 0:
            return 0.0
        return self.aligned_chars / self.json_chars


def normalize_for_align(text: str) -> str:
    """Normalização só para matching — não altera o texto de saída."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    s = s.translate(_LIGATURES)
    s = s.replace("\u00ad", "")  # soft hyphen
    out: list[str] = []
    for ch in s:
        if ch in _QUOTE_CHARS:
            out.append(_QUOTE_SENTINEL)
        else:
            out.append(ch)
    s = "".join(out)
    s = _DASH_RE.sub("-", s)
    s = _WS_RE.sub(" ", s)
    return s.casefold().strip()


def _flatten_runs(runs: list[TextRun]) -> tuple[str, list[str], list[str]]:
    """Retorna texto original, estilo por char, e char original (para aspas)."""
    parts: list[str] = []
    styles: list[str] = []
    for run in runs:
        for ch in run.text:
            parts.append(ch)
            styles.append(run.estilo if run.estilo in FONT_STYLES else "normal")
    text = "".join(parts)
    return text, styles, parts


def _build_norm_index(original: str) -> tuple[str, list[int]]:
    """
    Normaliza `original` e mapeia cada char normalizado → índice no original.
    Espaços colapsados apontam para o primeiro whitespace do grupo.
    """
    if not original:
        return "", []

    # Passo 1: NFKC + ligatures + soft hyphen + quotes/dashes char-a-char
    expanded: list[tuple[str, int]] = []  # (char_piece, orig_idx)
    for idx, ch in enumerate(original):
        if ch == "\u00ad":
            continue
        piece = unicodedata.normalize("NFKC", ch).translate(_LIGATURES)
        if not piece:
            continue
        for p in piece:
            if p in _QUOTE_CHARS:
                expanded.append((_QUOTE_SENTINEL, idx))
            elif _DASH_RE.fullmatch(p):
                expanded.append(("-", idx))
            else:
                expanded.append((p, idx))

    # Passo 2: colapsar whitespace e casefold
    norm_chars: list[str] = []
    norm_to_orig: list[int] = []
    prev_space = False
    for ch, orig_idx in expanded:
        if ch.isspace():
            if prev_space:
                continue
            if not norm_chars:
                continue  # leading
            norm_chars.append(" ")
            norm_to_orig.append(orig_idx)
            prev_space = True
            continue
        prev_space = False
        norm_chars.append(ch.casefold())
        norm_to_orig.append(orig_idx)

    # trailing space
    while norm_chars and norm_chars[-1] == " ":
        norm_chars.pop()
        norm_to_orig.pop()

    return "".join(norm_chars), norm_to_orig


def _find_exact(haystack: str, needle: str, start: int) -> int:
    if not needle:
        return -1
    return haystack.find(needle, start)


def _find_fuzzy(haystack: str, needle: str, start: int) -> tuple[int, int] | None:
    """Retorna (start, end) no haystack com melhor ratio ≥ limiar (mais rígido em textos curtos)."""
    if not needle or start >= len(haystack):
        return None
    nlen = len(needle)
    # Trechos muito curtos: só match exato (evita deslocar estilo para 1–2 chars).
    if nlen < MIN_FUZZY_NEEDLE:
        return None
    window = haystack[start:]
    if not window:
        return None

    threshold = MIN_FUZZY_RATIO_SHORT if nlen < 20 else MIN_FUZZY_RATIO
    # Janela com tolerância estreita — evita casar pedaço curto com campo longo.
    min_w = max(nlen - 2, int(nlen * 0.9), 1)
    max_w = min(len(window), int(nlen * 1.15) + 4)
    best: tuple[float, int, int] | None = None

    anchor = needle[: min(8, nlen)]
    candidates: list[int] = []
    if len(anchor) >= 3:
        pos = 0
        while True:
            found = window.find(anchor, pos)
            if found < 0:
                break
            candidates.append(found)
            pos = found + 1
            if len(candidates) > 40:
                break
    if not candidates:
        step = max(1, len(window) // 80)
        candidates = list(range(0, min(len(window), nlen * 3 + 50), step))

    for c in candidates:
        for w in range(min_w, max_w + 1):
            end = c + w
            if end > len(window):
                break
            chunk = window[c:end]
            ratio = SequenceMatcher(None, needle, chunk).ratio()
            if best is None or ratio > best[0]:
                best = (ratio, start + c, start + end)

    if best is None or best[0] < threshold:
        return None
    # Rejeita match que encolheu demais o trecho (causa projeção D|iversidade).
    matched_len = best[2] - best[1]
    if matched_len < int(nlen * 0.85):
        return None
    return best[1], best[2]


def _project_styles_by_opcodes(
    json_text: str,
    json_norm: str,
    json_norm_to_orig: list[int],
    pdf_norm_slice: str,
    pdf_styles: list[str],
    pdf_norm_to_orig: list[int],
    match_start: int,
) -> list[str]:
    """Projeta estilos PDF→JSON via opcodes (evita proporção linear que parte palavras)."""
    font_by_orig = ["normal"] * len(json_text)
    sm = SequenceMatcher(None, json_norm, pdf_norm_slice, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                ji = i1 + k
                pj = match_start + j1 + k
                if ji < len(json_norm_to_orig) and pj < len(pdf_norm_to_orig):
                    j_orig = json_norm_to_orig[ji]
                    pdf_oi = pdf_norm_to_orig[pj]
                    if 0 <= j_orig < len(font_by_orig) and 0 <= pdf_oi < len(pdf_styles):
                        font_by_orig[j_orig] = pdf_styles[pdf_oi]
        elif tag in ("replace", "insert", "delete"):
            # Para replace: mapeia pelo índice relativo na faixa.
            if tag == "replace" and (i2 > i1) and (j2 > j1):
                for k in range(i2 - i1):
                    ji = i1 + k
                    rel = k / max(i2 - i1, 1)
                    pj = match_start + j1 + min(int(rel * (j2 - j1)), j2 - j1 - 1)
                    if ji < len(json_norm_to_orig) and 0 <= pj < len(pdf_norm_to_orig):
                        j_orig = json_norm_to_orig[ji]
                        pdf_oi = pdf_norm_to_orig[pj]
                        if 0 <= j_orig < len(font_by_orig) and 0 <= pdf_oi < len(pdf_styles):
                            font_by_orig[j_orig] = pdf_styles[pdf_oi]
    return font_by_orig


def _is_word_char(ch: str) -> bool:
    return bool(ch) and (ch.isalnum() or ch in ("_", "\u00ad"))


def _coalesce_midword_style_breaks(text: str, styles: list[str]) -> list[str]:
    """Evita trocar estilo no meio de palavra (ex.: D|iversidade)."""
    if not text or len(styles) != len(text):
        return styles
    out = list(styles)
    i = 0
    n = len(text)
    while i < n:
        if not _is_word_char(text[i]):
            i += 1
            continue
        j = i
        while j < n and _is_word_char(text[j]):
            j += 1
        word_styles = out[i:j]
        if len(set(word_styles)) > 1:
            counts: dict[str, int] = {}
            for s in word_styles:
                counts[s] = counts.get(s, 0) + 1
            best = max(
                counts.keys(),
                key=lambda s: (counts[s], 0 if s == "normal" else 1),
            )
            for k in range(i, j):
                out[k] = best
        i = j
    return out


def _flatten_field_text(value: Any) -> tuple[str, list[str | None]]:
    """
    Achata string ou array de segmentos em texto + estilo visual por char.
    Estilos de fonte existentes são ignorados (serão sobrescritos); visuais são preservados.
    """
    if isinstance(value, str):
        return value, [None] * len(value)

    if isinstance(value, list):
        parts: list[str] = []
        visuals: list[str | None] = []
        for item in value:
            if isinstance(item, dict):
                trecho = str(item.get("trecho") or "")
                estilo = str(item.get("estilo") or "normal")
                visual = estilo if estilo in VISUAL_STYLES else None
                parts.append(trecho)
                visuals.extend([visual] * len(trecho))
            elif isinstance(item, str):
                parts.append(item)
                visuals.extend([None] * len(item))
        return "".join(parts), visuals

    return "", []


def _segments_from_styles(
    text: str,
    font_styles: list[str],
    visual_styles: list[str | None],
) -> str | list[dict[str, str]]:
    if not text:
        return text

    n = len(text)
    font_styles = (font_styles + ["normal"] * n)[:n]
    visual_styles = (visual_styles + [None] * n)[:n]

    effective: list[str] = []
    for i in range(n):
        if visual_styles[i]:
            effective.append(visual_styles[i] or "normal")
        else:
            estilo = font_styles[i]
            effective.append(estilo if estilo in FONT_STYLES else "normal")

    if all(s == "normal" for s in effective):
        return text

    segments: list[dict[str, str]] = []
    start = 0
    cur = effective[0]
    for i in range(1, n):
        if effective[i] != cur:
            segments.append({"trecho": text[start:i], "estilo": cur})
            start = i
            cur = effective[i]
    segments.append({"trecho": text[start:], "estilo": cur})
    return segments


def _leading_trailing_quotes(pdf_slice: str) -> tuple[str, str]:
    leading_q = ""
    trailing_q = ""
    i = 0
    while i < len(pdf_slice) and pdf_slice[i] in _QUOTE_CHARS:
        leading_q += pdf_slice[i]
        i += 1
    j = len(pdf_slice) - 1
    while j >= i and pdf_slice[j] in _QUOTE_CHARS:
        trailing_q = pdf_slice[j] + trailing_q
        j -= 1
    return leading_q, trailing_q


def _restore_quotes_with_styles(
    json_text: str,
    visual: list[str | None],
    font_by_orig: list[str],
    pdf_slice: str,
) -> tuple[str, list[str | None], list[str]]:
    """Reinsere aspas do PDF nos limites se o JSON as omitiu; estende estilos."""
    leading_q, trailing_q = _leading_trailing_quotes(pdf_slice)
    prefix = ""
    suffix = ""
    if leading_q and (not json_text or json_text[0] not in _QUOTE_CHARS):
        prefix = leading_q
    if trailing_q and (not json_text or json_text[-1] not in _QUOTE_CHARS):
        suffix = trailing_q
    if not prefix and not suffix:
        return json_text, visual, font_by_orig

    out_text = prefix + json_text + suffix
    inherit_start = font_by_orig[0] if font_by_orig else "normal"
    inherit_end = font_by_orig[-1] if font_by_orig else "normal"
    new_font = [inherit_start] * len(prefix) + list(font_by_orig) + [inherit_end] * len(suffix)
    new_visual = [None] * len(prefix) + list(visual) + [None] * len(suffix)
    return out_text, new_visual, new_font


def _unchanged_field(
    json_text: str,
    visual: list[str | None],
    cursor: int,
) -> tuple[str | list[dict[str, str]], int, int]:
    if all(v is None for v in visual):
        return json_text, cursor, 0
    return _segments_from_styles(json_text, ["normal"] * len(json_text), visual), cursor, 0


def _align_field(
    json_text: str,
    visual: list[str | None],
    pdf_text: str,
    pdf_styles: list[str],
    pdf_norm: str,
    pdf_norm_to_orig: list[int],
    cursor: int,
) -> tuple[str | list[dict[str, str]], int, int]:
    """
    Alinha um campo ao PDF. Retorna (valor_novo, novo_cursor, chars_alinhados).
    """
    if not json_text.strip():
        return _unchanged_field(json_text, visual, cursor)

    json_norm, json_norm_to_orig = _build_norm_index(json_text)
    if not json_norm or not pdf_norm:
        return _unchanged_field(json_text, visual, cursor)

    start_norm = 0
    if cursor > 0 and cursor < len(pdf_text):
        for ni, oi in enumerate(pdf_norm_to_orig):
            if oi >= cursor:
                start_norm = ni
                break
        else:
            start_norm = len(pdf_norm)

    match_start = _find_exact(pdf_norm, json_norm, start_norm)
    match_end = match_start + len(json_norm) if match_start >= 0 else -1

    if match_start < 0:
        fuzzy = _find_fuzzy(pdf_norm, json_norm, start_norm)
        if fuzzy is None and start_norm > 0:
            fuzzy = _find_fuzzy(pdf_norm, json_norm, 0)
        if fuzzy is None:
            return _unchanged_field(json_text, visual, cursor)
        match_start, match_end = fuzzy

    orig_indices = pdf_norm_to_orig[match_start:match_end]
    if not orig_indices:
        return _unchanged_field(json_text, visual, cursor)
    pdf_orig_start = orig_indices[0]
    pdf_orig_end = orig_indices[-1] + 1

    # Inclui aspas tipográficas imediatamente adjacentes ao match.
    while pdf_orig_start > 0 and pdf_text[pdf_orig_start - 1] in _QUOTE_CHARS:
        pdf_orig_start -= 1
    while pdf_orig_end < len(pdf_text) and pdf_text[pdf_orig_end] in _QUOTE_CHARS:
        pdf_orig_end += 1

    pdf_slice = pdf_text[pdf_orig_start:pdf_orig_end]
    pdf_norm_slice = pdf_norm[match_start:match_end]

    font_by_orig = _project_styles_by_opcodes(
        json_text,
        json_norm,
        json_norm_to_orig,
        pdf_norm_slice,
        pdf_styles,
        pdf_norm_to_orig,
        match_start,
    )

    mapped = [False] * len(json_text)
    for j_orig in json_norm_to_orig:
        if 0 <= j_orig < len(mapped):
            mapped[j_orig] = True
    last = "normal"
    for i in range(len(font_by_orig)):
        if mapped[i]:
            last = font_by_orig[i]
        else:
            font_by_orig[i] = last

    font_by_orig = _coalesce_midword_style_breaks(json_text, font_by_orig)

    out_text, visual, font_by_orig = _restore_quotes_with_styles(
        json_text, visual, font_by_orig, pdf_slice
    )
    if len(out_text) == len(font_by_orig):
        font_by_orig = _coalesce_midword_style_breaks(out_text, font_by_orig)
    new_value = _segments_from_styles(out_text, font_by_orig, visual)
    return new_value, pdf_orig_end, len(json_text)


def _walk_and_merge(
    node: Any,
    pdf_text: str,
    pdf_styles: list[str],
    pdf_norm: str,
    pdf_norm_to_orig: list[int],
    cursor: list[int],
    stats: MergeStats,
) -> Any:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            # Não processar descricao (Dorina)
            if key == "descricao":
                out[key] = value
                continue
            if key in STYLE_KEYS:
                flat, visual = _flatten_field_text(value)
                stats.fields_total += 1
                stats.json_chars += len(flat)
                new_val, new_cur, aligned = _align_field(
                    flat,
                    visual,
                    pdf_text,
                    pdf_styles,
                    pdf_norm,
                    pdf_norm_to_orig,
                    cursor[0],
                )
                if aligned > 0:
                    stats.fields_aligned += 1
                    stats.aligned_chars += aligned
                    cursor[0] = new_cur
                out[key] = new_val
            else:
                out[key] = _walk_and_merge(
                    value, pdf_text, pdf_styles, pdf_norm, pdf_norm_to_orig, cursor, stats
                )
        return out
    if isinstance(node, list):
        return [
            _walk_and_merge(item, pdf_text, pdf_styles, pdf_norm, pdf_norm_to_orig, cursor, stats)
            for item in node
        ]
    return node


def merge_styles_into_page(
    page_structure: dict[str, Any],
    page_styles: PageTextStyles | None,
    *,
    page_number: int | None = None,
) -> dict[str, Any]:
    """
    Enriquece o JSON da LLM com negrito/itálico extraídos do PDF.
    Retorna o mesmo objeto (mutado) para encadeamento.
    """
    if not isinstance(page_structure, dict):
        return page_structure
    if page_styles is None or page_styles.char_count < MIN_SCANNED_CHARS or not page_styles.runs:
        return page_structure

    pdf_text, pdf_styles, _ = _flatten_runs(page_styles.runs)
    pdf_norm, pdf_norm_to_orig = _build_norm_index(pdf_text)
    if not pdf_norm:
        return page_structure

    stats = MergeStats()
    cursor = [0]
    merged = _walk_and_merge(
        page_structure, pdf_text, pdf_styles, pdf_norm, pdf_norm_to_orig, cursor, stats
    )
    logger.info(
        "style_merge page=%s coverage=%.1f%% fields=%s/%s chars=%s/%s",
        page_number if page_number is not None else page_styles.page_number,
        stats.coverage * 100,
        stats.fields_aligned,
        stats.fields_total,
        stats.aligned_chars,
        stats.json_chars,
    )
    return merged if isinstance(merged, dict) else page_structure
