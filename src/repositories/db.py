from contextlib import contextmanager
from typing import Generator

import psycopg

from src.core.config import get_settings
from src.core.errors import PersistenceError


def _dsn() -> str:
    dsn = get_settings().supabase_db_dsn
    if not dsn:
        raise PersistenceError("SUPABASE_DB_DSN nao configurado.")
    return dsn


@contextmanager
def get_conn() -> Generator[psycopg.Connection, None, None]:
    conn = psycopg.connect(_dsn(), autocommit=False)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
