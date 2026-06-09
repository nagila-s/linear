"""Verificação rápida de env, Postgres e Supabase Storage (sem imprimir segredos)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def main() -> int:
    import os

    keys = [
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_DB_DSN",
        "OPENAI_API_KEY",
        "ACCESS_PASSWORD",
    ]
    print("=== Variáveis de ambiente ===")
    missing = []
    for key in keys:
        ok = bool(os.getenv(key, "").strip())
        print(f"  {key}: {'OK' if ok else 'MISSING'}")
        if not ok:
            missing.append(key)

    print("\n=== Postgres (SUPABASE_DB_DSN) ===")
    try:
        from src.repositories.db import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                print("  Conexão: OK")

                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'jobs'
                    ORDER BY column_name
                    """
                )
                cols = {row[0] for row in cur.fetchall()}
                print(f"  Colunas em jobs ({len(cols)}):", ", ".join(sorted(cols)))

                for need in ("tentativas", "attempts", "erro", "book_id", "metadata", "status"):
                    print(f"    - {need}: {'sim' if need in cols else 'NÃO'}")

                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'worker_claim_next_job')"
                )
                print("  RPC worker_claim_next_job:", "sim" if cur.fetchone()[0] else "NÃO")

                for table in ("books", "jobs", "artifacts", "pages"):
                    try:
                        cur.execute(f"SELECT COUNT(*) FROM {table}")
                        print(f"  {table} count:", cur.fetchone()[0])
                    except Exception as exc:
                        print(f"  {table}: ERRO", str(exc)[:100])
    except Exception as exc:
        print("  Conexão: FALHOU —", type(exc).__name__, str(exc)[:300])
        return 1

    print("\n=== Supabase Storage ===")
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
                print(f"  bucket '{bucket}': FALHOU —", str(exc)[:120])
    except Exception as exc:
        print("  Storage: FALHOU —", type(exc).__name__, str(exc)[:300])
        return 1

    print("\n=== FastAPI local (opcional) ===")
    try:
        import urllib.request

        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2) as resp:
            print("  GET /health:", resp.status, resp.read()[:80])
    except Exception:
        print("  API não está rodando em :8000 (normal se só testou env/DB)")

    if missing:
        print("\n⚠ Variáveis ausentes:", ", ".join(missing))
        return 1
    print("\n✓ Verificação básica concluída.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
