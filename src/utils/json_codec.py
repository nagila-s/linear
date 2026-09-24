import codecs
import json
import logging
import re
from typing import Any

_UNICODE_ESCAPE_RE = re.compile(r"\\u[0-9a-fA-F]{4}|\\U[0-9a-fA-F]{8}")
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)
_TRAILING_COMMA_EOF_RE = re.compile(r",\s*$")

logger = logging.getLogger(__name__)


def normalize_unicode_in_json(value: Any) -> Any:
    """Converte sequencias literais \\uXXXX ainda presentes em strings apos parse."""
    if isinstance(value, dict):
        return {k: normalize_unicode_in_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_unicode_in_json(v) for v in value]
    if isinstance(value, str) and _UNICODE_ESCAPE_RE.search(value):
        try:
            return codecs.decode(value, "unicode_escape")
        except (UnicodeError, ValueError):
            return value
    return value


def _strip_fences_and_commas(text: str) -> str:
    cleaned = text.strip().lstrip("\ufeff")
    cleaned = _FENCE_RE.sub("", cleaned).strip()
    cleaned = _TRAILING_COMMA_RE.sub(r"\1", cleaned)
    return cleaned


_WS = " \t\r\n"
# Aspas que o modelo usa como delimitador JSON fora da string.
_STRUCTURAL_CURLY = {
    "\u201c": '"',
    "\u201d": '"',
    "\u2018": '"',
    "\u2019": '"',
}


def _next_nonspace(text: str, i: int) -> int:
    n = len(text)
    while i < n and text[i] in _WS:
        i += 1
    return i


def _quote_closes_string(text: str, i: int) -> bool:
    """True se text[i] for a aspa que fecha a string JSON, não citação interna.

    Vírgula só fecha a string quando o que vem depois é outro valor JSON
    (`"`, `{`, `[`, número, true/false/null). Em `disse "sim", e continuou`
    a vírgula faz parte da frase.
    """
    j = _next_nonspace(text, i + 1)
    if j >= len(text):
        return True
    nxt = text[j]
    if nxt in "}]:" :
        return True
    if nxt != ",":
        return False
    k = _next_nonspace(text, j + 1)
    if k >= len(text):
        return True
    return _json_value_follows(text, k)


def _json_value_follows(text: str, k: int) -> bool:
    """True se text[k] inicia um valor JSON (não a continuação da frase)."""
    after = text[k]
    if after in "}]":
        return True
    if after in '"[{' or after in _STRUCTURAL_CURLY or after == "-" or after.isdigit():
        return True
    for word in ("true", "false", "null"):
        if not text.startswith(word, k):
            continue
        end = k + len(word)
        if end >= len(text) or text[end] in _WS + ",}]":
            return True
    return False


def escape_interior_ascii_quotes(text: str) -> str:
    """Escapa `"` de citação que o modelo deixou cru dentro de uma string JSON.

    A aspa que de fato fecha o valor continua sendo delimitador. Se a citação
    termina exatamente nessa aspa (`"Todos usaram?"}`), ela entra no texto e
    uma aspa extra fecha o JSON — senão o reparador engole os itens seguintes
    ou trata `//` e `#` como comentário.
    """
    out: list[str] = []
    in_string = False
    open_citations = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if not in_string:
            if ch == '"':
                in_string = True
                open_citations = 0
            out.append(ch)
            i += 1
            continue
        if ch == "\\":
            out.append(ch)
            if i + 1 < n:
                out.append(text[i + 1])
                i += 2
            else:
                i += 1
            continue
        if ch != '"':
            out.append(ch)
            i += 1
            continue
        if _quote_closes_string(text, i):
            if open_citations > 0:
                out.append('\\"')
                open_citations = 0
            out.append(ch)
            in_string = False
            i += 1
            continue
        out.append('\\"')
        if open_citations == 0:
            open_citations += 1
        else:
            open_citations -= 1
        i += 1
    return "".join(out)


def _replace_structural_curly_quotes(text: str) -> str:
    """Troca aspas tipográficas por `"` só fora de strings já delimitadas por ASCII.

    “olá” dentro de um valor permanece aspa tipográfica. Delimitadores do tipo
    {“chave”: “valor”} viram JSON válido.
    """
    out: list[str] = []
    in_string = False
    escape = False
    for ch in text:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            out.append(ch)
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            continue
        out.append(_STRUCTURAL_CURLY.get(ch, ch))
    return "".join(out)


def _protect_editorial_quotes(text: str) -> str:
    protected = escape_interior_ascii_quotes(text)
    structural = _replace_structural_curly_quotes(protected)
    if structural != protected:
        structural = escape_interior_ascii_quotes(structural)
    return structural


def repair_llm_json_text(text: str, *, replace_curly_quotes: bool = False) -> str:
    """Aplica correcoes comuns em JSON gerado por modelos de linguagem.

    Aspas de citação dentro do valor são escapadas. Aspas tipográficas internas
    permanecem. `replace_curly_quotes` é mantido por compatibilidade: a conversão
    global (que transformava citação em delimitador) não é mais feita.
    """
    del replace_curly_quotes
    cleaned = text.strip().lstrip("\ufeff")
    cleaned = _FENCE_RE.sub("", cleaned).strip()
    cleaned = _protect_editorial_quotes(cleaned)
    cleaned = _TRAILING_COMMA_RE.sub(r"\1", cleaned)
    return cleaned


def close_truncated_json(text: str, *, replace_curly_quotes: bool = False) -> str:
    """Fecha strings/objetos/arrays abertos em JSON truncado (best-effort)."""
    cleaned = repair_llm_json_text(text, replace_curly_quotes=replace_curly_quotes)
    start = cleaned.find("{")
    if start < 0:
        return cleaned
    s = cleaned[start:]

    in_string = False
    escape = False
    stack: list[str] = []
    for ch in s:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()

    if in_string:
        s += '"'
    s = _TRAILING_COMMA_EOF_RE.sub("", s)
    while stack:
        s += stack.pop()
    return s


def looks_truncated_json(text: str) -> bool:
    """Heuristica: JSON provavelmente cortado no meio."""
    cleaned = repair_llm_json_text(text or "")
    if not cleaned:
        return True
    try:
        json.loads(cleaned)
        return False
    except json.JSONDecodeError:
        pass
    # Fallback: tentar com aspas tipográficas convertidas
    cleaned_quotes = repair_llm_json_text(text or "", replace_curly_quotes=True)
    try:
        json.loads(cleaned_quotes)
        return False
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    if start < 0:
        return True
    body = cleaned[start:]
    in_string = False
    escape = False
    quote_open = False
    for ch in body:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
                quote_open = False
            continue
        if ch == '"':
            in_string = True
            quote_open = True
    if quote_open or in_string:
        return True
    return body.count("{") != body.count("}") or body.count("[") != body.count("]")


def _try_load_dict(payload: str) -> dict[str, Any] | None:
    stripped = payload.lstrip()
    if not stripped:
        return None
    decoder = json.JSONDecoder()
    try:
        parsed, _end = decoder.raw_decode(stripped)
    except json.JSONDecodeError:
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def parse_llm_json(content: str) -> dict[str, Any]:
    """Extrai e faz parse de JSON retornado por LLM, com reparo e anti-truncamento.

    Aspas de citação são escapadas antes do parse, para não fecharem a string
    cedo e caírem no removedor de comentários do json_repair.
    """
    if not content or not str(content).strip():
        raise json.JSONDecodeError("Resposta vazia.", content or "", 0)

    last_error: json.JSONDecodeError | None = None

    for replace_quotes in (False, True):
        cleaned = repair_llm_json_text(content, replace_curly_quotes=replace_quotes)
        candidates: list[str] = []
        if cleaned:
            candidates.append(cleaned)
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            sliced = cleaned[start : end + 1]
            if sliced not in candidates:
                candidates.append(sliced)
        closed = close_truncated_json(cleaned, replace_curly_quotes=replace_quotes)
        if closed and closed not in candidates:
            candidates.append(closed)

        for candidate in candidates:
            for payload in (
                candidate,
                repair_llm_json_text(candidate, replace_curly_quotes=replace_quotes),
                close_truncated_json(candidate, replace_curly_quotes=replace_quotes),
            ):
                try:
                    parsed = _try_load_dict(payload)
                except Exception:  # noqa: BLE001
                    parsed = None
                if parsed is not None:
                    return parsed
                try:
                    json.loads(payload)
                except json.JSONDecodeError as exc:
                    last_error = exc

        # Biblioteca especializada em JSON quebrado de LLM.
        try:
            from json_repair import repair_json

            repaired = repair_json(cleaned, return_objects=True)
            if isinstance(repaired, dict):
                return repaired
            if isinstance(repaired, str):
                parsed = _try_load_dict(repaired)
                if parsed is not None:
                    return parsed
        except Exception as exc:  # noqa: BLE001
            logger.debug("json_repair falhou (quotes=%s): %s", replace_quotes, exc)

    if last_error is not None:
        raise last_error
    raise json.JSONDecodeError("Nenhum objeto JSON encontrado na resposta.", content, 0)


def merge_json_fragments(partial: str, continuation: str) -> str:
    """Combina rascunho truncado + continuacao do modelo."""
    left = repair_llm_json_text(partial or "")
    right = repair_llm_json_text(continuation or "")
    if not left:
        return right
    if not right:
        return left
    # Continuacao que recomeça o objeto: NÃO concatenar (gera JSON aninhado no meio de strings).
    if right.lstrip().startswith("{"):
        return right
    # Junta direto e deixa o parser/reparo fechar.
    return left.rstrip() + right.lstrip()
