from typing import Any, Dict

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
