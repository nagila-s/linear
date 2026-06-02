import codecs
import re
from typing import Any

_UNICODE_ESCAPE_RE = re.compile(r"\\u[0-9a-fA-F]{4}|\\U[0-9a-fA-F]{8}")


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
