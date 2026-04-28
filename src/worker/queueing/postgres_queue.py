import asyncpg

from src.core.config import get_settings
from src.worker.utils.logger import get_logger

logger = get_logger(__name__)


class PostgresQueue:
    def __init__(self):
        self._pool: asyncpg.Pool | None = None
        self.settings = get_settings()
        self._book_lock_connections: dict[str, asyncpg.Connection] = {}

    async def connect(self):
        self._pool = await asyncpg.create_pool(
            dsn=self.settings.supabase_db_dsn,
            min_size=1,
            max_size=5,
            ssl="require",
        )
        logger.info("Pool de conexoes Postgres criado")

    async def disconnect(self):
        for book_id in list(self._book_lock_connections.keys()):
            await self.release_book_lock(book_id)
        if self._pool:
            await self._pool.close()

    async def claim_next_job(self, worker_id: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM public.worker_claim_next_job($1)", worker_id)
            return dict(row) if row else None

    async def touch_heartbeat(self, job_id: str, processed_items: int | None = None, failed_items: int | None = None):
        async with self._pool.acquire() as conn:
            await conn.execute(
                "SELECT public.worker_touch_heartbeat($1, $2, $3)",
                job_id,
                processed_items,
                failed_items,
            )

    async def complete_job(self, job_id: str, processed_items: int | None = None):
        async with self._pool.acquire() as conn:
            await conn.execute("SELECT public.worker_complete_job($1, $2)", job_id, processed_items)

    async def fail_job(self, job_id: str, error: str):
        async with self._pool.acquire() as conn:
            await conn.execute("SELECT public.worker_fail_job($1, $2)", job_id, error[:2000])

    async def requeue_stale(self) -> int:
        async with self._pool.acquire() as conn:
            value = await conn.fetchval("SELECT public.worker_requeue_stale_jobs()")
            return int(value or 0)

    async def acquire_book_lock(self, book_id: str):
        book_id_str = str(book_id)
        if book_id_str in self._book_lock_connections:
            return
        conn = await self._pool.acquire()
        try:
            await conn.execute("SELECT pg_advisory_lock(hashtextextended($1, 0))", book_id_str)
            self._book_lock_connections[book_id_str] = conn
        except Exception:
            await self._pool.release(conn)
            raise

    async def release_book_lock(self, book_id: str):
        book_id_str = str(book_id)
        conn = self._book_lock_connections.pop(book_id_str, None)
        if not conn:
            return
        try:
            await conn.execute("SELECT pg_advisory_unlock(hashtextextended($1, 0))", book_id_str)
        finally:
            await self._pool.release(conn)
