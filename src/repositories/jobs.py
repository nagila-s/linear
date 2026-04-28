from typing import Any, Dict, Optional
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from src.models.enums import JobStatus, JobType
from src.repositories.db import get_conn


class JobsRepository:
    def create(self, isbn: str, job_type: JobType, prompt_version: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        query = """
            WITH ins AS (
                INSERT INTO jobs (
                    book_id,
                    job_type,
                    prompt_version,
                    openai_model,
                    dorina_model,
                    pipeline_mode,
                    metadata,
                    status,
                    etapa_atual,
                    tentativas
                )
                VALUES (
                    (SELECT id FROM books WHERE isbn = %s),
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s::jsonb,
                    %s,
                    %s,
                    0
                )
                RETURNING *
            )
            SELECT ins.*, b.isbn, b.storage_path_pdf
            FROM ins
            LEFT JOIN books b ON b.id = ins.book_id
        """
        with get_conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    query,
                    (
                        isbn,
                        job_type.value,
                        prompt_version,
                        (metadata or {}).get("openai_model"),
                        (metadata or {}).get("dorina_model"),
                        (metadata or {}).get("pipeline_mode", job_type.value),
                        Jsonb(metadata or {}),
                        JobStatus.QUEUED.value,
                        "preprocess",
                    ),
                )
                return cur.fetchone()

    def get(self, job_id: UUID) -> Optional[Dict[str, Any]]:
        query = """
            SELECT j.*, b.isbn, b.storage_path_pdf
            FROM jobs j
            LEFT JOIN books b ON b.id = j.book_id
            WHERE j.id = %s
        """
        with get_conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, (str(job_id),))
                return cur.fetchone()

    def claim_next_job(self) -> Optional[Dict[str, Any]]:
        try:
            return self.claim_next_job_via_rpc(worker_id="worker-legacy")
        except Exception:
            # Fallback para ambientes sem RPC worker_* aplicado.
            query = """
                WITH candidate AS (
                    SELECT j.id
                    FROM jobs j
                    WHERE status = %s
                    ORDER BY j.created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE jobs j
                SET
                    status = %s,
                    updated_at = NOW()
                FROM candidate
                WHERE j.id = candidate.id
                RETURNING
                    j.*,
                    (
                        SELECT b.isbn
                        FROM books b
                        WHERE b.id = j.book_id
                    ) AS isbn,
                    (
                        SELECT b.storage_path_pdf
                        FROM books b
                        WHERE b.id = j.book_id
                    ) AS storage_path_pdf
            """
            with get_conn() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (JobStatus.QUEUED.value, JobStatus.RUNNING.value))
                    return cur.fetchone()

    def claim_next_job_via_rpc(self, worker_id: str) -> Optional[Dict[str, Any]]:
        query = """
            SELECT *
            FROM worker_claim_next_job(%s)
        """
        with get_conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, (worker_id,))
                return cur.fetchone()

    def update_stage(self, job_id: UUID, stage: str) -> None:
        query = "UPDATE jobs SET etapa_atual = %s, updated_at = NOW() WHERE id = %s"
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (stage, str(job_id)))

    def mark_done(self, job_id: UUID) -> None:
        query = "UPDATE jobs SET status = %s, updated_at = NOW() WHERE id = %s"
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (JobStatus.DONE.value, str(job_id)))

    def mark_failed(self, job_id: UUID, error_message: str) -> None:
        query = """
            UPDATE jobs
            SET
                status = %s,
                tentativas = tentativas + 1,
                erro = %s,
                updated_at = NOW()
            WHERE id = %s
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (JobStatus.FAILED.value, error_message[:1500], str(job_id)))

    def requeue_with_error(self, job_id: UUID, error_message: str) -> None:
        query = """
            UPDATE jobs
            SET
                status = %s,
                tentativas = tentativas + 1,
                erro = %s,
                updated_at = NOW()
            WHERE id = %s
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (JobStatus.QUEUED.value, error_message[:1500], str(job_id)))

    def retry(self, job_id: UUID) -> None:
        query = """
            UPDATE jobs
            SET
                status = %s,
                updated_at = NOW()
            WHERE id = %s
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (JobStatus.QUEUED.value, str(job_id)))

    def requeue_stale_running_jobs(self, stale_minutes: int) -> int:
        query = """
            UPDATE jobs
            SET
                status = %s,
                tentativas = tentativas + 1,
                erro = CASE
                    WHEN erro IS NULL OR erro = '' THEN %s
                    ELSE erro || ' | ' || %s
                END,
                updated_at = NOW()
            WHERE status = %s
              AND updated_at < NOW() - make_interval(mins => %s)
            RETURNING id
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query,
                    (
                        JobStatus.QUEUED.value,
                        "Reenfileirado automaticamente: job running sem heartbeat.",
                        "Reenfileirado automaticamente: job running sem heartbeat.",
                        JobStatus.RUNNING.value,
                        stale_minutes,
                    ),
                )
                rows = cur.fetchall()
                return len(rows)
