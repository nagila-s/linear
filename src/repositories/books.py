from typing import Any, Dict, List

from psycopg.rows import dict_row

from src.repositories.db import get_conn


class BooksRepository:
    def upsert(self, isbn: str, metadata: Dict[str, Any]) -> str:
        titulo = str(metadata.get("titulo") or metadata.get("filename") or f"Livro {isbn}")
        origem = str(metadata.get("origem") or "upload")
        storage_path_pdf = str(metadata.get("storage_path_pdf") or "")
        query = """
            INSERT INTO books (isbn, titulo, origem, storage_path_pdf)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (isbn)
            DO UPDATE SET
                titulo = COALESCE(NULLIF(EXCLUDED.titulo, ''), books.titulo),
                origem = COALESCE(NULLIF(EXCLUDED.origem, ''), books.origem),
                storage_path_pdf = COALESCE(NULLIF(EXCLUDED.storage_path_pdf, ''), books.storage_path_pdf)
            RETURNING id
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (isbn, titulo, origem, storage_path_pdf))
                return str(cur.fetchone()[0])

    def list_with_latest_job(self, limit: int = 100) -> List[Dict[str, Any]]:
        query = """
            SELECT
                b.id AS book_id,
                b.titulo,
                b.isbn,
                b.created_at AS book_created_at,
                j.id AS job_id,
                j.status::text AS status,
                j.job_type::text AS job_type,
                j.created_at AS job_created_at,
                j.metadata AS metadata
            FROM books b
            INNER JOIN LATERAL (
                SELECT *
                FROM jobs
                WHERE book_id = b.id
                ORDER BY created_at DESC
                LIMIT 1
            ) j ON TRUE
            ORDER BY j.created_at DESC
            LIMIT %s
        """
        with get_conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, (limit,))
                return list(cur.fetchall())
