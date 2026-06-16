import asyncio
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from src.core.config import get_settings
from src.models.enums import JobType
from src.repositories.artifacts import ArtifactsRepository
from src.repositories.db import get_conn
from src.repositories.jobs import JobsRepository
from src.services.openai_client import OpenAIService
from src.services.storage import StorageService
from src.worker.pipeline.stages import describe, extract_images
from src.worker.services.dorina_client import DorinaClient
from src.worker.utils.logger import get_logger

logger = get_logger(__name__)


def _load_job_data(job_id: str) -> dict[str, Any]:
    query = """
        SELECT j.*, b.isbn, b.storage_path_pdf
        FROM jobs j
        JOIN books b ON b.id = j.book_id
        WHERE j.id = %s
    """
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, (str(job_id),))
            data = cur.fetchone()
            if not data:
                raise ValueError(f"Job nao encontrado: {job_id}")
            return data


async def run(job: dict, _queue) -> dict:
    job_data = await asyncio.to_thread(_load_job_data, str(job["id"]))
    settings = StorageService().settings
    app_settings = get_settings()
    process_version = (job_data.get("metadata") or {}).get(
        "process_version",
        settings.process_version_strategy.format(
            linear_prompt_version=settings.linear_prompt_version,
        ),
    )
    prompt_version = str(job_data.get("prompt_version") or settings.linear_prompt_version)

    if str(job_data.get("job_type")) != JobType.LINEARIZAR.value:
        raise ValueError(
            f"Job type '{job_data.get('job_type')}' desativado. Apenas '{JobType.LINEARIZAR.value}' esta habilitado."
        )

    artifacts_repo = ArtifactsRepository()
    storage = StorageService()
    openai = OpenAIService()
    dorina = DorinaClient()

    job_id = UUID(str(job_data["id"]))
    jobs_repo = JobsRepository()

    ctx = {
        "job_id": str(job_data["id"]),
        "book_id": str(job_data["book_id"]),
        "isbn": str(job_data["isbn"]),
        "job_type": JobType.LINEARIZAR.value,
        "prompt_version": prompt_version,
        "process_version": process_version,
        "pdf_storage_path": str(job_data["storage_path_pdf"]),
        "artifacts_repo": artifacts_repo,
        "storage": storage,
        "openai": openai,
        "dorina": dorina,
        "pdf_render_dpi": app_settings.pdf_render_dpi,
        "linearize_page_concurrency": app_settings.linearize_page_concurrency,
    }

    await asyncio.to_thread(jobs_repo.update_stage, job_id, "preprocess")
    ctx = await extract_images.run(ctx)
    await asyncio.to_thread(jobs_repo.update_stage, job_id, "linearize")
    ctx = await describe.run(ctx)
    await asyncio.to_thread(jobs_repo.update_stage, job_id, "assemble")

    final_payload = {
        "isbn": ctx["isbn"],
        "job_id": ctx["job_id"],
        "job_type": JobType.LINEARIZAR.value,
        "prompt_version": prompt_version,
        "process_version": process_version,
        "dpi": ctx["pdf_render_dpi"],
        "pages": ctx["linearized_pages"],
        "descriptions": ctx.get("descriptions", []),
    }

    await asyncio.to_thread(
        storage.upload_json,
        ctx["isbn"],
        process_version,
        ctx["job_id"],
        "linear.json",
        final_payload,
    )
    final_storage_path = await asyncio.to_thread(
        storage.upload_json,
        ctx["isbn"],
        process_version,
        ctx["job_id"],
        "final.json",
        final_payload,
        2,
    )
    await asyncio.to_thread(
        artifacts_repo.save_final_payload,
        ctx["job_id"],
        final_payload,
        final_storage_path,
    )

    return {"described_count": ctx["described_count"], "failed_count": ctx["failed_count"]}
