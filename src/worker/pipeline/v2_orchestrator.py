import asyncio
from typing import Any

from psycopg.rows import dict_row

from src.models.enums import JobType
from src.repositories.artifacts import ArtifactsRepository
from src.repositories.db import get_conn
from src.services.dorina_client import DorinaService
from src.services.export_clients import AvaliaExporter, PBExporter
from src.services.openai_client import OpenAIService
from src.services.storage import StorageService
from src.worker.pipeline.stages import describe, extract_images
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
    process_version = (job_data.get("metadata") or {}).get(
        "process_version",
        settings.process_version_strategy.format(
            linear_prompt_version=settings.linear_prompt_version,
            context_prompt_version=settings.context_prompt_version,
            dorina_prompt_version=settings.dorina_prompt_version,
        ),
    )
    prompt_version = str(job_data.get("prompt_version") or settings.linear_prompt_version)

    artifacts_repo = ArtifactsRepository()
    storage = StorageService()
    openai = OpenAIService()
    dorina = DorinaService()
    pb_exporter = PBExporter()
    avalia_exporter = AvaliaExporter()

    ctx = {
        "job_id": str(job_data["id"]),
        "book_id": str(job_data["book_id"]),
        "isbn": str(job_data["isbn"]),
        "job_type": str(job_data["job_type"]),
        "prompt_version": prompt_version,
        "process_version": process_version,
        "pdf_storage_path": str(job_data["storage_path_pdf"]),
        "artifacts_repo": artifacts_repo,
        "storage": storage,
        "openai": openai,
        "dorina": dorina,
    }

    ctx = await extract_images.run(ctx)
    ctx = await describe.run(ctx)

    linear_payload = {
        "isbn": ctx["isbn"],
        "job_id": ctx["job_id"],
        "prompt_version": prompt_version,
        "pages": ctx["linearized_pages"],
    }
    context_payload = {
        "isbn": ctx["isbn"],
        "job_id": ctx["job_id"],
        "prompt_version": prompt_version,
        "contexts": ctx["contexts"],
    }
    descriptions_payload = {
        "isbn": ctx["isbn"],
        "job_id": ctx["job_id"],
        "prompt_version": prompt_version,
        "descriptions": ctx["descriptions"],
    }
    final_payload = {
        "isbn": ctx["isbn"],
        "job_id": ctx["job_id"],
        "job_type": ctx["job_type"],
        "prompt_version": prompt_version,
        "process_version": process_version,
        "pages": ctx["linearized_pages"],
        "image_context": [{"figure_id": k, "context": v} for k, v in ctx["contexts"].items()],
        "descriptions": ctx["descriptions"],
    }

    await asyncio.to_thread(storage.upload_json, ctx["isbn"], process_version, ctx["job_id"], "linear.json", linear_payload)
    await asyncio.to_thread(storage.upload_json, ctx["isbn"], process_version, ctx["job_id"], "contexts.json", context_payload)
    await asyncio.to_thread(storage.upload_json, ctx["isbn"], process_version, ctx["job_id"], "descriptions.json", descriptions_payload)
    final_storage_path = await asyncio.to_thread(
        storage.upload_json,
        ctx["isbn"],
        process_version,
        ctx["job_id"],
        "final.json",
        final_payload,
    )
    await asyncio.to_thread(
        artifacts_repo.save_final_payload,
        ctx["job_id"],
        final_payload,
        final_storage_path,
    )

    if ctx["job_type"] == JobType.LINEARIZAR.value:
        await asyncio.to_thread(pb_exporter.export, final_payload)
    else:
        for description_item in ctx["descriptions"]:
            await asyncio.to_thread(
                avalia_exporter.export,
                {
                    "isbn": ctx["isbn"],
                    "job_id": ctx["job_id"],
                    "figure_id": description_item["figure_id"],
                    "description": description_item.get("description", ""),
                },
            )

    return {"described_count": ctx["described_count"], "failed_count": ctx["failed_count"]}
