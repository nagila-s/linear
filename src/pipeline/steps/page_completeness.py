"""Texto nativo da página + heurísticas de completude da linearização."""

from __future__ import annotations

import re
import unicodedata
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
        "termo",
        "valor",
        "legenda",
        "fonte",
        "titulo_1",
        "titulo_2",
        "titulo_3",
        "titulo_4",
        "titulo_5",
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


# Pontilhado de sumário/índice ("Capítulo 1 ........ 16"): 4+ pontos seguidos, para não
# descontar reticências comuns ("...").
_DOT_LEADER_RE = re.compile(r"(?:[.…·]\s?){4,}")


def pdf_text_char_count(plain_text: str | None) -> int:
    """Tamanho do texto nativo para a checagem de completude, sem pontilhados.

    Em sumários os pontilhados chegam a ~65% dos caracteres e a IA (corretamente)
    não os transcreve; contá-los faria toda transcrição parecer incompleta.
    """
    text = _DOT_LEADER_RE.sub(" ", plain_text or "")
    return len(text.strip())


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
        "[TEXTO NATIVO DO PDF — APOIO, SUBORDINADO ÀS REGRAS ACIMA]\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "O texto abaixo foi extraído da camada de texto do PDF, na ordem em que o arquivo o "
        "guarda (que pode não ser a ordem de leitura). Use-o só como apoio: para conferir a "
        "grafia e para não deixar de fora nenhum trecho que as regras acima mandam transcrever.\n"
        "- A imagem define o que é conteúdo, a hierarquia, os tipos de bloco e a ordem de leitura.\n"
        "- As regras acima prevalecem sobre este texto. Ele pode conter itens que essas regras "
        "mandam omitir — números de página, cabeçalhos e rodapés, créditos de imagem, "
        "pontilhados de sumário, texto de miniaturas de páginas. Não os transcreva.\n"
        "- Não acrescente nada que não esteja visível na página.\n\n"
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


def _quote_depth(text: str) -> int:
    depth = 0
    for ch in text or "":
        if ch in "\u201c\u00ab":
            depth += 1
        elif ch in "\u201d\u00bb":
            depth = max(0, depth - 1)
        elif ch == '"':
            depth = 1 - depth
    return depth


def _unclosed_quotes(text: str) -> bool:
    return _quote_depth(text) > 0


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
    if _unclosed_quotes(tail):
        return True
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
        if _unclosed_quotes(value):
            search_from = min(len(value), min_keep)
            for closer in ("\u201d", "\u00bb", '"'):
                close_at = window.find(closer, search_from)
                if close_at >= 0:
                    window = window[: close_at + 1]
                    return window.strip() or value
        if not _unclosed_quotes(window):
            for sep in ("\n\n", ".\n", "? ", "! ", ". "):
                pos = window.rfind(sep)
                if pos >= min_keep:
                    if _unclosed_quotes(window[:pos]):
                        continue
                    window = window[: pos + (1 if sep.startswith(".") else len(sep))]
                    break
        return window.strip() or value

    # Passo 1: todos os textos da página, na ordem da árvore, para saber o que
    # vem depois de cada campo.
    ordered: list[str] = []
    _walk_strings(page_structure, lambda s, _expandable: ordered.append(s) or s)
    norm_fields = [_norm_words(s) for s in ordered]
    joined_parts: list[str] = []
    ends: list[int] = []
    pos = 0
    for nf in norm_fields:
        if nf:
            joined_parts.append(nf)
            pos += len(nf) + 1
        ends.append(pos)
    joined = " ".join(joined_parts)

    # Passo 2: expande só quando a continuação ainda não está nos campos seguintes.
    counter = [0]

    def visit(value: str, expandable: bool) -> str:
        i = counter[0]
        counter[0] += 1
        if not expandable:
            return value
        new_value = expand_string(value)
        if new_value == value:
            return value
        following = joined[ends[i] : ends[i] + _FOLLOWING_WINDOW]
        if _continuation_already_present(value, new_value, following):
            return value
        return new_value

    return _walk_strings(page_structure, visit)


# Quantos caracteres (normalizados) depois do campo procurar a continuação.
_FOLLOWING_WINDOW = 1000
_PROBE_MIN_CHARS = 20
_PROBE_MIN_WORDS = 3
_PROBE_TOO_SHORT = 12
_NON_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)


def _norm_words(text: str) -> str:
    """Casefold, sem acento, só letras/números separados por espaço — para comparar trechos."""
    s = unicodedata.normalize("NFKD", text or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = _NON_WORD_RE.sub(" ", s.casefold())
    return " ".join(s.split())


def _continuation_already_present(old: str, new: str, following_norm: str) -> bool:
    """
    True se o texto que a expansão acrescentaria já está transcrito logo depois
    deste campo no JSON (ex.: nome da ficha técnica seguido do próximo cargo,
    termo de glossário seguido da definição). Nesses casos o campo não estava
    cortado — expandir duplicaria texto.
    """
    old_n = _norm_words(old)
    new_n = _norm_words(new)
    if new_n.startswith(old_n):
        tail = new_n[len(old_n) :]
    else:
        tail = new_n[len(old_n) :] if len(new_n) > len(old_n) else ""
    words = tail.split()
    if not words:
        return False
    probe_words: list[str] = []
    for w in words:
        probe_words.append(w)
        probe = " ".join(probe_words)
        if len(probe) >= _PROBE_MIN_CHARS and len(probe_words) >= _PROBE_MIN_WORDS:
            break
    probe = " ".join(probe_words)
    if len(probe) < _PROBE_TOO_SHORT:
        return False
    return probe in following_norm


def _walk_strings(node: Any, visit: Any, *, expandable_ctx: bool = False) -> Any:
    """
    Percorre a árvore e chama visit(texto, expandable) em cada string, na ordem.
    `expandable` é True para campos textuais (_TEXT_KEYS) e itens/trechos dentro deles.
    Chaves de metadado (_SKIP_COUNT_KEYS) são preservadas sem visita.
    """
    if isinstance(node, dict):
        # Itens de sumário são curtos e terminam sem pontuação: parecem "cortados", mas
        # completá-los com o texto nativo cola pontilhados e as entradas seguintes.
        in_toc = str(node.get("tipo") or "").strip().lower() == "sumario"
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in _SKIP_COUNT_KEYS:
                out[key] = value
                continue
            if in_toc:
                out[key] = _walk_strings(value, lambda s, _e: visit(s, False))
                continue
            out[key] = _walk_strings(value, visit, expandable_ctx=key in _TEXT_KEYS)
        return out
    if isinstance(node, list):
        return [_walk_strings(item, visit, expandable_ctx=expandable_ctx) for item in node]
    if isinstance(node, str):
        return visit(node, expandable_ctx)
    return node


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
    page_type: str | None = None,
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
        # Mantém a classificação já feita (sumário, ficha…); só cai em conteudo sem ela.
        "tipo_pagina": (page_type or "").strip() or "conteudo",
        "conteudo": blocks,
        "linearizacao_fallback": "texto_nativo_pdf",
    }
    if printed_page is not None:
        page["pagina"] = printed_page
    elif page_number is not None:
        page["pagina"] = page_number
    return page
