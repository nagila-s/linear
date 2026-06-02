"""Convencoes de caminho para PDF em cache local (compartilhado API + worker)."""

from pathlib import Path

from src.core.config import get_settings
from src.core.errors import IntegrationError

LOCAL_SCHEME = "local://"


def is_local_storage_path(storage_path: str) -> bool:
    return str(storage_path or "").strip().startswith(LOCAL_SCHEME)


def resolve_local_pdf_path(storage_path: str) -> Path:
    normalized = storage_path.strip()
    if not normalized.startswith(LOCAL_SCHEME):
        raise IntegrationError(f"Caminho nao e cache local: {storage_path}")
    rel = normalized[len(LOCAL_SCHEME) :].lstrip("/")
    return Path(get_settings().pdf_local_cache_dir) / rel
