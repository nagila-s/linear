"""Texto nativo da página + heurísticas de completude da linearização."""

from __future__ import annotations

import re
from typing import Any

from src.pipeline.steps.image_credits import strip_image_credits
from src.pipeline.steps.pdf_text_styles import PageTextStyles

# Chaves editoriais usadas na contagem de cobertura.
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
    }
)

# Metadados que não entram na cobertura editorial.
_SKIP_COUNT_KEYS = frozenset(
    {
        "tipo",
        "tipo_pagina",
        "pagina",
        "prompt_version",
        "estilo",
        "letra",
        "marcador",
        "numero",
        "banca",
        "descricao",
        "figure_key",
        "arquivo_pdf",
        "pagina_indd",
        "data_hora",
        "colecao",
        "ordem_leitura",
    }
)

# Só avalia completude em páginas com bastante texto nativo.
MIN_PDF_CHARS_FOR_CHECK = 800
# JSON editorial costuma ser menor que o PDF (omite cabeçalho/rodapé); abaixo disso é falha.
MIN_COVERAGE_RATIO = 0.40
# Limite do bloco de texto injetado no prompt (evita estourar contexto).
MAX_PLAIN_TEXT_CHARS = 12000


def plain_text_from_page_styles(page: PageTextStyles | None) -> str:
    """Concatena runs tipográficos em texto plano para apoio à LLM."""
    if page is None or not page.runs:
        return ""
    return strip_image_credits("".join(run.text for run in page.runs))


def format_page_text_context(plain_text: str) -> str:
    """Bloco a anexar ao prompt de linearização."""
    text = (plain_text or "").strip()
    if not text:
        return ""
    if len(text) > MAX_PLAIN_TEXT_CHARS:
        text = text[: MAX_PLAIN_TEXT_CHARS - 20] + "\n...[texto cortado]..."
    return (
        "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "[TEXTO NATIVO EXTRAÍDO DO PDF — REFERÊNCIA OBRIGATÓRIA]\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "A imagem continua sendo a fonte da hierarquia editorial (tipos de bloco, ordem, "
        "quadros, figuras). O texto abaixo é a camada nativa do PDF: use-o para NÃO omitir "
        "trechos, especialmente em páginas de duas colunas, poemas e citações com aspas "
        "gráficas. Transcreva o conteúdo completo; não invente o que não estiver na página.\n\n"
        f"{text}\n"
    )


def editorial_plain_text(node: Any) -> str:
    """Concatena os campos textuais do JSON editorial na ordem da árvore."""
    parts: list[str] = []

    def walk(n: Any) -> None:
        if isinstance(n, dict):
            for key, value in n.items():
                if key in _SKIP_COUNT_KEYS:
                    continue
                if key in _TEXT_KEYS:
                    if isinstance(value, str):
                        if value.strip():
                            parts.append(value)
                    elif isinstance(value, list):
                        for item in value:
                            if isinstance(item, dict):
                                trecho = str(item.get("trecho") or item.get("texto") or "").strip()
                                if trecho:
                                    parts.append(trecho)
                                walk({k: v for k, v in item.items() if k not in {"trecho", "texto"}})
                            elif isinstance(item, str) and item.strip():
                                parts.append(item)
                    continue
                if isinstance(value, str):
                    if len(value) >= 8:
                        parts.append(value)
                    continue
                walk(value)
            return
        if isinstance(n, list):
            for item in n:
                walk(item)

    walk(node)
    return "\n".join(parts)


def editorial_char_count(node: Any) -> int:
    """Conta caracteres nos campos textuais do JSON editorial."""
    total = 0
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _SKIP_COUNT_KEYS:
                continue
            if key in _TEXT_KEYS:
                if isinstance(value, str):
                    total += len(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            total += len(str(item.get("trecho") or item.get("texto") or ""))
                            total += editorial_char_count(
                                {k: v for k, v in item.items() if k not in {"trecho", "texto"}}
                            )
                        elif isinstance(item, str):
                            total += len(item)
                continue
            if isinstance(value, str):
                # Campos textuais fora da lista canônica (ex.: enunciado legado).
                if len(value) >= 8:
                    total += len(value)
                continue
            total += editorial_char_count(value)
        return total
    if isinstance(node, list):
        for item in node:
            total += editorial_char_count(item)
        return total
    return 0


def normalize_page_structure(page_structure: dict[str, Any] | None) -> dict[str, Any] | None:
    """Garante raiz com 'conteudo'; achata coluna_esquerda/direita se vierem no schema errado."""
    if not isinstance(page_structure, dict):
        return page_structure
    data = dict(page_structure)
    conteudo = data.get("conteudo")
    if isinstance(conteudo, list) and conteudo:
        return data
    left = data.get("coluna_esquerda")
    right = data.get("coluna_direita")
    parts: list[Any] = []
    if isinstance(left, list):
        parts.extend(left)
    if isinstance(right, list):
        parts.extend(right)
    if parts:
        data["conteudo"] = parts
        data.pop("coluna_esquerda", None)
        data.pop("coluna_direita", None)
        data.pop("layout", None)
    return data


def has_usable_conteudo(page_structure: dict[str, Any] | None) -> bool:
    if not isinstance(page_structure, dict):
        return False
    conteudo = page_structure.get("conteudo")
    return isinstance(conteudo, list) and len(conteudo) > 0


def _last_editorial_snippet(node: Any) -> str:
    """Último trecho textual encontrado (ordem de walk) — para detectar corte no meio."""
    found = ""

    def walk(n: Any) -> None:
        nonlocal found
        if isinstance(n, dict):
            for key, value in n.items():
                if key in _TEXT_KEYS:
                    if isinstance(value, str) and value.strip():
                        found = value.strip()
                    elif isinstance(value, list):
                        parts: list[str] = []
                        for item in value:
                            if isinstance(item, dict):
                                parts.append(str(item.get("trecho") or ""))
                            elif isinstance(item, str):
                                parts.append(item)
                        joined = "".join(parts).strip()
                        if joined:
                            found = joined
                else:
                    walk(value)
            return
        if isinstance(n, list):
            for item in n:
                walk(item)

    walk(node)
    return found


def looks_cut_mid_sentence(page_structure: dict[str, Any]) -> bool:
    """True se o último texto parece cortado no meio (sem pontuação final)."""
    snippet = _last_editorial_snippet(page_structure)
    if len(snippet) < 40:
        return False
    tail = snippet.rstrip()
    if not tail:
        return False
    # Termina com letra/minúscula ou hífen → provável truncamento.
    if tail[-1].isalpha() and (tail[-1].islower() or tail.endswith((" e", " o", " a", " de", " do", " da"))):
        return True
    if tail.endswith(("-", "—", ",", ";", ":")):
        return True
    return False


def _text_looks_cut(value: str) -> bool:
    tail = (value or "").rstrip()
    if len(tail) < 30:
        return False
    if tail[-1].isalpha() and tail[-1].islower():
        return True
    if tail.endswith(("-", "—", ",", ";", ":", " e", " o", " a")):
        return True
    return False


def expand_cut_texts_from_plain(
    page_structure: dict[str, Any] | None,
    plain_text: str,
) -> dict[str, Any] | None:
    """Completa campos textuais cortados no meio usando o texto nativo do PDF."""
    if not isinstance(page_structure, dict):
        return page_structure
    plain = (plain_text or "").strip()
    if len(plain) < 80:
        return page_structure

    def _find_in_plain(needle: str) -> int:
        raw = (needle or "").strip()
        # Aspas tipográficas / marcas de citação no início atrapalham o match no PDF.
        raw = raw.lstrip("\u201c\u201d\u00ab\u00bb\"'").strip()
        if len(raw) < 20:
            return -1
        idx = plain.find(raw)
        if idx >= 0:
            return idx
        idx = plain.find(raw[:40])
        if idx >= 0:
            return idx
        words = raw.split()
        if len(words) < 4:
            return -1
        # Tenta a partir da 1ª e da 2ª palavra (pula título/aspas residuais).
        for start in (0, 1):
            chunk = words[start : start + 10]
            if len(chunk) < 4:
                continue
            pattern = r"\s+".join(re.escape(w) for w in chunk)
            match = re.search(pattern, plain)
            if match:
                return match.start()
        return -1

    def expand_string(value: str) -> str:
        if not _text_looks_cut(value):
            return value
        idx = _find_in_plain(value.strip()[:80])
        if idx < 0:
            idx = _find_in_plain(value.strip()[:40])
        if idx < 0:
            return value
        end = min(len(plain), idx + max(len(value) * 4, 900))
        window = plain[idx:end]
        # Evita engolir alternativas/questões seguintes.
        for stop_re in (r"\(\d{2}\)", r"\n\d{1,2}\.\s", r"\n\(\s*[A-Ea-e]\s*\)"):
            m = re.search(stop_re, window[max(len(value), 40) :])
            if m:
                window = window[: max(len(value), 40) + m.start()]
                break
        min_keep = max(len(value), 80)
        for sep in ("\n\n", ".\n", "? ", "! ", ". "):
            pos = window.rfind(sep)
            if pos >= min_keep:
                window = window[: pos + (1 if sep.startswith(".") else len(sep))]
                break
        return window.strip() or value

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            out: dict[str, Any] = {}
            for key, value in node.items():
                if key in _TEXT_KEYS and isinstance(value, str):
                    out[key] = expand_string(value)
                elif key in _TEXT_KEYS and isinstance(value, list):
                    new_list = []
                    for item in value:
                        if isinstance(item, dict) and isinstance(item.get("trecho"), str):
                            new_item = dict(item)
                            new_item["trecho"] = expand_string(item["trecho"])
                            new_list.append(new_item)
                        elif isinstance(item, str):
                            new_list.append(expand_string(item))
                        else:
                            new_list.append(walk(item))
                    out[key] = new_list
                else:
                    out[key] = walk(value)
            return out
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(page_structure)


def is_linearization_incomplete(
    page_structure: dict[str, Any] | None,
    *,
    pdf_char_count: int,
) -> bool:
    """Heurística: JSON válido mas muito curto vs texto nativo do PDF."""
    page_structure = normalize_page_structure(page_structure)
    if not isinstance(page_structure, dict):
        return True
    if not has_usable_conteudo(page_structure):
        return pdf_char_count >= MIN_PDF_CHARS_FOR_CHECK
    if pdf_char_count < MIN_PDF_CHARS_FOR_CHECK:
        return False

    json_chars = editorial_char_count(page_structure)
    if json_chars <= 0:
        return True
    ratio = json_chars / max(pdf_char_count, 1)
    if ratio < MIN_COVERAGE_RATIO:
        return True
    # Corte no meio (ex.: poema interrompido por content_filter) — incompleto mesmo com ratio ok.
    if looks_cut_mid_sentence(page_structure):
        return True
    return False


def split_plain_text_for_columns(plain_text: str) -> tuple[str, str]:
    """Divide texto nativo em duas metades (aprox. colunas) pelo meio em quebra de linha."""
    text = (plain_text or "").strip()
    if not text:
        return "", ""
    mid = len(text) // 2
    break_at = text.find("\n", mid)
    if break_at < 0 or break_at > len(text) - 200:
        break_at = text.rfind("\n", 0, mid)
    if break_at < 200:
        break_at = mid
    return text[:break_at].strip(), text[break_at:].strip()


def split_plain_text_chunks(plain_text: str, *, parts: int = 4) -> list[str]:
    """Divide o texto nativo em N pedaços em quebras de linha."""
    text = (plain_text or "").strip()
    if not text:
        return []
    parts = max(2, int(parts))
    if len(text) < 600:
        return [text]
    size = max(1, len(text) // parts)
    chunks: list[str] = []
    start = 0
    for i in range(parts - 1):
        target = start + size
        break_at = text.find("\n", target)
        if break_at < 0 or break_at > len(text) - 80:
            break_at = text.rfind("\n", start + 40, target)
        if break_at <= start:
            break_at = min(target, len(text))
        piece = text[start:break_at].strip()
        if piece:
            chunks.append(piece)
        start = break_at
    tail = text[start:].strip()
    if tail:
        chunks.append(tail)
    return chunks or [text]


def scaffold_page_from_plain_text(
    plain_text: str,
    *,
    page_number: int | None = None,
    printed_page: int | None = None,
) -> dict[str, Any]:
    """Fallback determinístico: monta conteudo a partir do texto nativo do PDF.

    Usado quando a API interrompe por content_filter / truncamento e a LLM
    não consegue devolver a página completa. Preferível a JSON vazio/parcial.
    """
    text = (plain_text or "").strip()
    blocks: list[dict[str, Any]] = []
    if text:
        # Agrupa por linhas em branco; se não houver, fatia por ~900 chars.
        raw_parts = [p.strip() for p in text.split("\n\n") if p.strip()]
        if len(raw_parts) <= 1:
            lines = [ln.rstrip() for ln in text.splitlines()]
            buf: list[str] = []
            for ln in lines:
                buf.append(ln)
                joined = "\n".join(buf)
                if len(joined) >= 900 and ln.strip() == "":
                    blocks.append({"tipo": "texto", "texto": joined.strip()})
                    buf = []
                elif len(joined) >= 1200:
                    blocks.append({"tipo": "texto", "texto": joined.strip()})
                    buf = []
            if buf:
                blocks.append({"tipo": "texto", "texto": "\n".join(buf).strip()})
        else:
            for part in raw_parts:
                blocks.append({"tipo": "texto", "texto": part})
    if not blocks and text:
        blocks = [{"tipo": "texto", "texto": text}]

    page: dict[str, Any] = {
        "tipo_pagina": "conteudo",
        "conteudo": blocks,
        "linearizacao_fallback": "texto_nativo_pdf",
    }
    if printed_page is not None:
        page["pagina"] = printed_page
    elif page_number is not None:
        page["pagina"] = page_number
    return page
