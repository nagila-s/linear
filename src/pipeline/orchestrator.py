import logging
from typing import Any, Dict, List
from uuid import UUID

from src.core.config import get_settings
from src.models.enums import JobType
from src.pipeline.steps.preprocess import preprocess_pdf
from src.repositories.artifacts import ArtifactsRepository
from src.repositories.jobs import JobsRepository
from src.services.openai_client import OpenAIService
from src.services.storage import StorageService

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    def __init__(self) -> None:
        self.jobs_repo = JobsRepository()
        self.artifacts_repo = ArtifactsRepository()
        self.storage = StorageService()
        self.openai = OpenAIService()

    def process_job(self, job: Dict[str, Any]) -> None:
        job_id = UUID(str(job["id"]))
        book_id = str(job["book_id"])
        isbn = str(job["isbn"])
        job_type = JobType(str(job["job_type"]))
        if job_type != JobType.LINEARIZAR:
            raise ValueError(f"Job type '{job_type.value}' desativado. Apenas linearizar esta habilitado.")

        prompt_version = str(job.get("prompt_version") or self.storage.settings.linear_prompt_version)
        process_version = self.storage.settings.process_version_strategy.format(
            linear_prompt_version=self.storage.settings.linear_prompt_version,
        )
        pdf_storage_path = str(job.get("storage_path_pdf") or "")

        self.jobs_repo.update_stage(job_id, "preprocess")
        pages = self._run_preprocess(book_id, isbn, pdf_storage_path)

        self.jobs_repo.update_stage(job_id, "linearize")
        linearized_pages: List[Dict[str, Any]] = []
        for page in pages:
            page_content = self.openai.linearize_page(page.page_png, prompt_version)
            linearized_pages.append(
                {
                    "page_number": page.page_number,
                    "content": page_content,
                }
            )

        self.jobs_repo.update_stage(job_id, "assemble")
        final_payload = {
            "isbn": isbn,
            "job_id": str(job_id),
            "job_type": job_type.value,
            "prompt_version": prompt_version,
            "process_version": process_version,
            "dpi": get_settings().pdf_render_dpi,
            "pages": linearized_pages,
        }
        final_storage_path = self.storage.upload_json(
            isbn, process_version, str(job_id), "final.json", final_payload, 2
        )
        self.artifacts_repo.save_final_payload(job_id, final_payload, final_storage_path)
        self.jobs_repo.mark_done(job_id)
        logger.info("Job %s finalizado com sucesso.", job_id)

    def _run_preprocess(self, book_id: str, isbn: str, pdf_storage_path: str):
        pdf_bytes = self.storage.download_by_storage_path(pdf_storage_path or f"pdf/{isbn}/original.pdf")
        pages = preprocess_pdf(pdf_bytes, dpi=get_settings().pdf_render_dpi)
        process_version = self.storage.settings.process_version_strategy.format(
            linear_prompt_version=self.storage.settings.linear_prompt_version,
        )

        for page in pages:
            page_storage_path = self.storage.upload_page(
                isbn, page.page_name, page.page_png, process_version=process_version
            )
            width_px, height_px = page.source_rgb_image.size
            self.artifacts_repo.add_page(book_id, page.page_number, page_storage_path, width_px, height_px)

        return pages
