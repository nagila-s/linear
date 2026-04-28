from typing import Any, Dict
from uuid import UUID

from psycopg.types.json import Jsonb

from src.repositories.db import get_conn


class ArtifactsRepository:
    @staticmethod
    def _normalize_export_status(status: str) -> str:
        value = (status or "").strip().lower()
        if value in {"queued", "sent", "failed"}:
            return value
        # Quando integracao retorna "skipped" (ex.: URL nao configurada),
        # persistimos como failed para manter compatibilidade com enum atual.
        return "failed"

    def add_page(self, book_id: str, page_number: int, storage_path: str, width_px: int, height_px: int) -> str:
        query = """
            INSERT INTO pages (book_id, page_number, storage_path_page_png, width_px, height_px)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (book_id, page_number)
            DO UPDATE SET
                storage_path_page_png = EXCLUDED.storage_path_page_png,
                width_px = EXCLUDED.width_px,
                height_px = EXCLUDED.height_px
            RETURNING id
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (book_id, page_number, storage_path, width_px, height_px))
                return str(cur.fetchone()[0])

    def add_figure(self, book_id: str, page_id: str, figure_index: int, storage_path: str) -> str:
        query = """
            INSERT INTO figures (book_id, page_id, figure_index, storage_path_figure_png)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (page_id, figure_index)
            DO UPDATE SET storage_path_figure_png = EXCLUDED.storage_path_figure_png
            RETURNING id
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (book_id, page_id, figure_index, storage_path))
                return str(cur.fetchone()[0])

    def save_context(self, figure_id: str, context: str, prompt_version: str) -> None:
        query = """
            UPDATE figures
            SET
                context_local = %s,
                context_structural = %s,
                context_prompt_version = %s
            WHERE id = %s
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                context_local = {"text": context}
                context_structural = {
                    "prompt_version": prompt_version,
                    "text": context,
                }
                cur.execute(
                    query,
                    (
                        Jsonb(context_local),
                        Jsonb(context_structural),
                        prompt_version,
                        figure_id,
                    ),
                )

    def save_description(
        self,
        figure_id: str,
        prompt_version: str,
        payload: Dict[str, Any],
    ) -> None:
        query = """
            INSERT INTO descriptions (
                figure_id,
                dorina_model_version,
                prompt_version,
                description_text,
                quality_flags
            )
            VALUES (%s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (figure_id, prompt_version)
            DO UPDATE SET
                dorina_model_version = EXCLUDED.dorina_model_version,
                description_text = EXCLUDED.description_text,
                quality_flags = EXCLUDED.quality_flags
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                description_text = str(payload.get("description") or payload.get("texto") or "")
                model_version = str(payload.get("model") or payload.get("model_version") or "unknown")
                quality_flags = payload.get("quality_flags", {})
                cur.execute(
                    query,
                    (figure_id, model_version, prompt_version, description_text, Jsonb(quality_flags)),
                )

    def save_final_payload(self, job_id: UUID, payload: Dict[str, Any], storage_path: str) -> None:
        query = """
            INSERT INTO artifacts (
                job_id,
                artifact_type,
                storage_path,
                payload_json,
                version_tag,
                checksum
            )
            VALUES (%s, %s, %s, %s::jsonb, %s, md5(%s))
            ON CONFLICT (job_id, artifact_type)
            DO UPDATE SET
                storage_path = EXCLUDED.storage_path,
                payload_json = EXCLUDED.payload_json,
                version_tag = EXCLUDED.version_tag,
                checksum = EXCLUDED.checksum,
                updated_at = NOW()
        """
        version_tag = str(payload.get("process_version") or payload.get("prompt_version") or "v1")
        raw_payload = Jsonb(payload)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query,
                    (
                        str(job_id),
                        "final_json",
                        storage_path,
                        raw_payload,
                        version_tag,
                        str(payload),
                    ),
                )

    def add_export_pb(self, book_id: str, payload: Dict[str, Any], status: str) -> None:
        normalized_status = self._normalize_export_status(status)
        query = """
            INSERT INTO exports_pb (book_id, payload_json, status)
            VALUES (%s, %s::jsonb, %s)
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (book_id, Jsonb(payload), normalized_status))

    def add_export_avalia(self, figure_id: str, payload: Dict[str, Any], status: str) -> None:
        normalized_status = self._normalize_export_status(status)
        query = """
            INSERT INTO exports_avalia (figure_id, payload_json, status)
            VALUES (%s, %s::jsonb, %s)
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (figure_id, Jsonb(payload), normalized_status))
