"""Checklist automatizado de Supabase para producao (migrations, RPC worker v2, buckets)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

MIGRATION_FILES = [
    "20260428090000_foundation_processing_queue.sql",
    "20260428091000_fix_retry_and_worker_rpc.sql",
    "20260428092000_artifacts_and_versioning.sql",
    "20260511140000_worker_rpc_job_status_cast.sql",
    "20260511150000_enable_rls_artifacts_job_items.sql",
    "20260601180000_storage_pdf_bucket_size.sql",
]

REQUIRED_RPC = (
    "worker_claim_next_job",
    "worker_touch_heartbeat",
    "worker_complete_job",
    "worker_fail_job",
)


def main() -> int:
    import os
    from pathlib import Path

    print("=== Supabase producao ===\n")
    errors = 0

    if not os.getenv("SUPABASE_DB_DSN", "").strip():
        print("ERRO: SUPABASE_DB_DSN ausente (worker v2 exige Postgres).")
        errors += 1
    else:
        print("OK: SUPABASE_DB_DSN definido (worker v2)")

    migrations_dir = Path(__file__).resolve().parents[1] / "supabase" / "migrations"
    print("\n=== Arquivos de migration no repo ===")
    for name in MIGRATION_FILES:
        path = migrations_dir / name
        print(f"  {'OK' if path.is_file() else 'FALTA'}: {name}")
        if not path.is_file():
            errors += 1
    print("  Aplique no Supabase SQL Editor ou CLI na ordem acima.")

    print("\n=== Postgres ===")
    try:
        from src.repositories.db import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT proname FROM pg_proc p
                    JOIN pg_namespace n ON p.pronamespace = n.oid
                    WHERE n.nspname = 'public' AND proname = ANY(%s)
                    """,
                    (list(REQUIRED_RPC),),
                )
                found = {row[0] for row in cur.fetchall()}
                for rpc in REQUIRED_RPC:
                    ok = rpc in found
                    print(f"  RPC {rpc}: {'OK' if ok else 'AUSENTE — rode migrations'}")
                    if not ok:
                        errors += 1

                cur.execute(
                    """
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name IN ('books', 'jobs', 'artifacts', 'pages', 'job_items')
                    """
                )
                tables = {row[0] for row in cur.fetchall()}
                for t in ("books", "jobs", "artifacts", "pages"):
                    print(f"  tabela {t}: {'OK' if t in tables else 'AUSENTE'}")
                    if t not in tables:
                        errors += 1
    except Exception as exc:
        print(f"  ERRO conexao: {type(exc).__name__}: {exc}")
        errors += 1

    print("\n=== Storage buckets ===")
    try:
        from src.services.storage import StorageService

        storage = StorageService()
        for bucket in (
            storage.settings.bucket_pdf,
            storage.settings.bucket_pages,
            storage.settings.bucket_figures,
            storage.settings.bucket_json,
        ):
            try:
                storage.client.storage.from_(bucket).list("", {"limit": 1})
                print(f"  bucket '{bucket}': OK")
            except Exception as exc:
                print(f"  bucket '{bucket}': FALHOU — {str(exc)[:100]}")
                errors += 1
        print(
            "\n  PDFs grandes: plano Pro + limite global no dashboard + "
            "migration 20260601180000_storage_pdf_bucket_size.sql"
        )
        print("  Producao AWS: use PDF_STORAGE_STRATEGY=supabase na API e no worker.")
    except Exception as exc:
        print(f"  ERRO: {type(exc).__name__}: {exc}")
        errors += 1

    if errors:
        print(f"\n{errors} problema(s). Corrija antes do deploy AWS/Vercel.")
        return 1
    print("\nSupabase pronto para producao (checagem automatica).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
