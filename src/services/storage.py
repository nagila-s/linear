import io
import json
from typing import Any, Dict

from supabase import create_client

from src.core.config import get_settings
from src.core.errors import IntegrationError


class StorageService:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise IntegrationError("SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY sao obrigatorios.")
        self.settings = settings
        self.client = create_client(settings.supabase_url, settings.supabase_service_role_key)

    def upload_pdf(self, isbn: str, content: bytes, process_version: str = "v1") -> str:
        path = f"{isbn}/{process_version}/original.pdf"
        self.client.storage.from_(self.settings.bucket_pdf).upload(
            path=path,
            file=content,
            file_options={"content-type": "application/pdf", "upsert": "true"},
        )
        return f"{self.settings.bucket_pdf}/{path}"

    def upload_page(self, isbn: str, page_name: str, content: bytes, process_version: str = "v1") -> str:
        path = f"{isbn}/{process_version}/{page_name}"
        self.client.storage.from_(self.settings.bucket_pages).upload(
            path=path,
            file=content,
            file_options={"content-type": "image/png", "upsert": "true"},
        )
        return f"{self.settings.bucket_pages}/{path}"

    def upload_figure(self, isbn: str, page_folder: str, figure_name: str, content: bytes, process_version: str = "v1") -> str:
        path = f"{isbn}/{process_version}/{page_folder}/{figure_name}"
        self.client.storage.from_(self.settings.bucket_figures).upload(
            path=path,
            file=content,
            file_options={"content-type": "image/png", "upsert": "true"},
        )
        return f"{self.settings.bucket_figures}/{path}"

    def upload_json(self, isbn: str, process_version: str, job_id: str, file_name: str, payload: Dict[str, Any]) -> str:
        path = f"{isbn}/{process_version}/{job_id}/{file_name}"
        self.client.storage.from_(self.settings.bucket_json).upload(
            path=path,
            file=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            file_options={"content-type": "application/json", "upsert": "true"},
        )
        return f"{self.settings.bucket_json}/{path}"

    def download_pdf(self, isbn: str) -> bytes:
        path = f"{isbn}/original.pdf"
        data = self.client.storage.from_(self.settings.bucket_pdf).download(path)
        if not data:
            raise IntegrationError(f"PDF nao encontrado em {self.settings.bucket_pdf}/{path}.")
        if isinstance(data, bytes):
            return data
        return io.BytesIO(data).read()

    def download_by_storage_path(self, storage_path: str) -> bytes:
        normalized = storage_path.strip().lstrip("/")
        if not normalized or "/" not in normalized:
            raise IntegrationError("storage_path_pdf invalido.")
        bucket, path = normalized.split("/", 1)
        data = self.client.storage.from_(bucket).download(path)
        if not data:
            raise IntegrationError(f"Arquivo nao encontrado em {bucket}/{path}.")
        if isinstance(data, bytes):
            return data
        return io.BytesIO(data).read()

    def signed_json_url(self, isbn: str, process_version: str, job_id: str, file_name: str, expires_in: int = 3600) -> str:
        path = f"{isbn}/{process_version}/{job_id}/{file_name}"
        result = self.client.storage.from_(self.settings.bucket_json).create_signed_url(path, expires_in)
        return result.get("signedURL", "")

    def signed_url_for_storage_path(self, storage_path: str, expires_in: int = 3600) -> str:
        normalized = storage_path.strip().lstrip("/")
        if not normalized or "/" not in normalized:
            raise IntegrationError("storage_path invalido para URL assinada.")
        bucket, path = normalized.split("/", 1)
        result = self.client.storage.from_(bucket).create_signed_url(path, expires_in)
        return result.get("signedURL", "")
