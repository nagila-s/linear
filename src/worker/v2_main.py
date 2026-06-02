import asyncio
import signal
import uuid

from src.core.config import get_settings
from src.worker.pipeline import v2_orchestrator
from src.worker.queueing.postgres_queue import PostgresQueue
from src.worker.utils.logger import get_logger

settings = get_settings()
logger = get_logger(__name__)
WORKER_ID = f"worker-{uuid.uuid4().hex[:8]}"
shutdown_event = asyncio.Event()


def _handle_signal(sig, _frame):
    logger.info("Sinal recebido, encerrando (cancela job em andamento)", signal=sig)
    shutdown_event.set()


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


async def heartbeat_loop(queue: PostgresQueue, job_id: str):
    while True:
        await asyncio.sleep(max(5, settings.worker_poll_seconds))
        try:
            await queue.touch_heartbeat(job_id)
        except Exception as error:
            logger.warning("Falha ao enviar heartbeat", job_id=job_id, error=str(error))


async def process_job(queue: PostgresQueue, job: dict):
    job_id = job["id"]
    book_id = job.get("book_id")
    lock_acquired = False
    heartbeat_task = asyncio.create_task(heartbeat_loop(queue, job_id))
    try:
        if book_id:
            await queue.acquire_book_lock(book_id)
            lock_acquired = True
        ctx = await v2_orchestrator.run(job, queue)
        await queue.touch_heartbeat(job_id, processed_items=ctx.get("described_count", 0), failed_items=ctx.get("failed_count", 0))
        await queue.complete_job(job_id, processed_items=ctx.get("described_count", 0))
    except Exception as error:
        await queue.fail_job(job_id, str(error))
        logger.error("Job falhou", job_id=job_id, error=str(error), exc_info=True)
    finally:
        if lock_acquired and book_id:
            await queue.release_book_lock(book_id)
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass


async def main():
    queue = PostgresQueue()
    await queue.connect()
    cycle = 0
    try:
        while not shutdown_event.is_set():
            cycle += 1
            if cycle % 12 == 0:
                await queue.requeue_stale()
            job = await queue.claim_next_job(WORKER_ID)
            if not job:
                await asyncio.sleep(settings.worker_poll_seconds)
                continue

            job_id = str(job["id"])
            work_task = asyncio.create_task(process_job(queue, job))
            shutdown_task = asyncio.create_task(shutdown_event.wait())
            done, _pending = await asyncio.wait(
                {work_task, shutdown_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if shutdown_task in done and not work_task.done():
                work_task.cancel()
                try:
                    await work_task
                except asyncio.CancelledError:
                    pass
                try:
                    await queue.fail_job(
                        job_id,
                        "Worker encerrado pelo operador (SIGINT/SIGTERM) durante o processamento.",
                    )
                except Exception as error:
                    logger.warning("fail_job apos cancelamento", job_id=job_id, error=str(error))
                shutdown_task.cancel()
                try:
                    await shutdown_task
                except asyncio.CancelledError:
                    pass
                break

            shutdown_task.cancel()
            try:
                await shutdown_task
            except asyncio.CancelledError:
                pass

            try:
                await work_task
            except asyncio.CancelledError:
                pass

            if shutdown_event.is_set():
                break
    finally:
        await queue.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
