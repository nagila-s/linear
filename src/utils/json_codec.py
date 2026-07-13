import codecs
import json
import re
from typing import Any

_UNICODE_ESCAPE_RE = re.compile(r"\\u[0-9a-fA-F]{4}|\\U[0-9a-fA-F]{8}")
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


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


def parse_llm_json(content: str) -> dict[str, Any]:
    """Extrai e faz parse de JSON retornado por LLM, com reparo leve."""
    if not content or not str(content).strip():
        raise json.JSONDecodeError("Resposta vazia.", content or "", 0)

    candidates: list[str] = []
    cleaned = repair_llm_json_text(content)
    if cleaned:
        candidates.append(cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        sliced = cleaned[start : end + 1]
        if sliced not in candidates:
            candidates.append(sliced)

    decoder = json.JSONDecoder()
    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        for payload in (candidate, repair_llm_json_text(candidate)):
            stripped = payload.lstrip()
            if not stripped:
                continue
            try:
                parsed, _end = decoder.raw_decode(stripped)
            except json.JSONDecodeError as exc:
                last_error = exc
                try:
                    parsed = json.loads(payload)
                except json.JSONDecodeError as loads_exc:
                    last_error = loads_exc
                    continue
            if isinstance(parsed, dict):
                return parsed
            raise json.JSONDecodeError("JSON raiz deve ser um objeto.", payload, 0)

    if last_error is not None:
        raise last_error
    raise json.JSONDecodeError("Nenhum objeto JSON encontrado na resposta.", content, 0)
