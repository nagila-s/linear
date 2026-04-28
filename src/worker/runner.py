import logging
import time

from src.core.config import get_settings
from src.core.logging import configure_logging
from src.pipeline.orchestrator import PipelineOrchestrator
from src.repositories.jobs import JobsRepository
from src.worker.v2_main import main as run_worker_v2


def run_worker_forever() -> None:
    settings = get_settings()
    if settings.supabase_db_dsn:
        # Worker v2 por RPC/Postgres queue.
        import asyncio

        asyncio.run(run_worker_v2())
        return

    configure_logging()
    logger = logging.getLogger("worker")
    jobs_repo = JobsRepository()
    orchestrator = PipelineOrchestrator()
    idle_sleep = settings.worker_poll_seconds
    error_sleep = max(2, settings.worker_poll_seconds)
    max_error_sleep = 60

    logger.info("Worker iniciado. Poll a cada %ss.", settings.worker_poll_seconds)
    while True:
        try:
            recovered = jobs_repo.requeue_stale_running_jobs(settings.worker_stale_job_minutes)
            if recovered:
                logger.warning(
                    "Recuperacao automatica reenfileirou %s job(s) running stale.",
                    recovered,
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falha ao executar recuperacao de jobs stale: %s", exc)

        try:
            job = jobs_repo.claim_next_job()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falha ao buscar proximo job: %s", exc)
            logger.warning("Worker continua ativo. Nova tentativa em %ss.", error_sleep)
            time.sleep(error_sleep)
            error_sleep = min(error_sleep * 2, max_error_sleep)
            continue

        error_sleep = max(2, settings.worker_poll_seconds)
        if not job:
            time.sleep(idle_sleep)
            continue

        job_id = job["id"]
        try:
            logger.info("Processando job %s...", job_id)
            orchestrator.process_job(job)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falha no job %s: %s", job_id, exc)
            attempts_after_failure = int(job.get("tentativas", 0)) + 1
            if attempts_after_failure < settings.worker_max_attempts:
                jobs_repo.requeue_with_error(job_id, str(exc))
                logger.warning(
                    "Job %s re-enfileirado (%s/%s tentativas).",
                    job_id,
                    attempts_after_failure,
                    settings.worker_max_attempts,
                )
            else:
                jobs_repo.mark_failed(job_id, str(exc))
