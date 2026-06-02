"""Armazenamento de PDF original (Supabase Storage ou cache local compartilhado)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from storage3.exceptions import StorageApiError

from src.core.config import get_settings
from src.core.errors import IntegrationError
from src.services.pdf_paths import LOCAL_SCHEME, is_local_storage_path, resolve_local_pdf_path
from src.services.storage import StorageService

logger = logging.getLogger(__name__)

PdfStorageStrategy = Literal["auto", "supabase", "local"]


def is_payload_too_large(exc: BaseException) -> bool:
    text = str(exc).lower()
    if "413" in text or "payload too large" in text or "maximum allowed size" in text:
        return True
    if isinstance(exc, StorageApiError):
        raw = getattr(exc, "message", None) or getattr(exc, "args", ())
        if isinstance(raw, dict):
            code = raw.get("statusCode") or raw.get("status")
            if code == 413:
                return True
    return False


class PdfStorageService:
    def __init__(self, storage: StorageService | None = None) -> None:
        self._storage = storage or StorageService()
        self._settings = self._storage.settings

    def store(self, isbn: str, content: bytes, process_version: str) -> str:
        size_mb = len(content) / (1024 * 1024)
        max_mb = self._settings.pdf_max_size_mb
        if max_mb > 0 and size_mb > max_mb:
            raise IntegrationError(
                f"PDF com {size_mb:.1f} MB excede o limite configurado (PDF_MAX_SIZE_MB={max_mb})."
            )

        strategy: PdfStorageStrategy = self._settings.pdf_storage_strategy  # type: ignore[assignment]
        if strategy == "local":
            return self._store_local(isbn, content, process_version)
        if strategy == "supabase":
            return self._store_supabase(isbn, content, process_version)

        try:
            return self._store_supabase(isbn, content, process_version)
        except Exception as exc:
            if not is_payload_too_large(exc):
                raise
            logger.warning(
                "Upload Supabase rejeitado por tamanho (%.1f MB). Usando cache local em %s.",
                size_mb,
                self._settings.pdf_local_cache_dir,
            )
            return self._store_local(isbn, content, process_version)

    def _store_supabase(self, isbn: str, content: bytes, process_version: str) -> str:
        return self._storage.upload_pdf(isbn, content, process_version=process_version)

    def _store_local(self, isbn: str, content: bytes, process_version: str) -> str:
        rel = f"{isbn}/{process_version}/original.pdf"
        path = Path(self._settings.pdf_local_cache_dir) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return f"{LOCAL_SCHEME}{rel}"

    def download(self, storage_path: str) -> bytes:
        if is_local_storage_path(storage_path):
            path = resolve_local_pdf_path(storage_path)
            if not path.is_file():
                raise IntegrationError(f"PDF local nao encontrado: {path}")
            return path.read_bytes()
        return self._storage.download_by_storage_path(storage_path)
