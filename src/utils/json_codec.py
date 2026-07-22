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


def repair_llm_json_text(text: str) -> str:
    """Aplica correcoes comuns em JSON gerado por modelos de linguagem."""
    cleaned = text.strip().lstrip("\ufeff")
    cleaned = _FENCE_RE.sub("", cleaned).strip()
    for old, new in (
        ("\u201c", '"'),
        ("\u201d", '"'),
        ("\u2018", "'"),
        ("\u2019", "'"),
    ):
        cleaned = cleaned.replace(old, new)
    cleaned = _TRAILING_COMMA_RE.sub(r"\1", cleaned)
    return cleaned


def close_truncated_json(text: str) -> str:
    """Fecha strings/objetos/arrays abertos em JSON truncado (best-effort)."""
    cleaned = repair_llm_json_text(text)
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
    start = cleaned.find("{")
    if start < 0:
        return True
    body = cleaned[start:]
    # Aspas nao balanceadas (aproximacao ignorando escapes simples)
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
    """Extrai e faz parse de JSON retornado por LLM, com reparo e anti-truncamento."""
    if not content or not str(content).strip():
        raise json.JSONDecodeError("Resposta vazia.", content or "", 0)

    cleaned = repair_llm_json_text(content)
    candidates: list[str] = []
    if cleaned:
        candidates.append(cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        sliced = cleaned[start : end + 1]
        if sliced not in candidates:
            candidates.append(sliced)
    closed = close_truncated_json(cleaned)
    if closed and closed not in candidates:
        candidates.append(closed)

    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        for payload in (candidate, repair_llm_json_text(candidate), close_truncated_json(candidate)):
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
        logger.debug("json_repair falhou: %s", exc)

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
    # Continuacao ja e um objeto completo.
    if right.lstrip().startswith("{") and right.rstrip().endswith("}"):
        return right
    # Junta direto e deixa o parser/reparo fechar.
    return left.rstrip() + right.lstrip()
