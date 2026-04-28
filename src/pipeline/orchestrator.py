import logging
from typing import Any, Dict, List
from uuid import UUID

from src.models.enums import JobType
from src.pipeline.steps.preprocess import (
    FigureArtifact,
    extract_figures_from_page,
    map_figures_by_page,
    preprocess_pdf,
)
from src.repositories.artifacts import ArtifactsRepository
from src.repositories.jobs import JobsRepository
from src.services.dorina_client import DorinaService
from src.services.export_clients import AvaliaExporter, PBExporter
from src.services.openai_client import OpenAIService
from src.services.storage import StorageService

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    def __init__(self) -> None:
        self.jobs_repo = JobsRepository()
        self.artifacts_repo = ArtifactsRepository()
        self.storage = StorageService()
        self.openai = OpenAIService()
        self.dorina = DorinaService()
        self.pb_exporter = PBExporter()
        self.avalia_exporter = AvaliaExporter()

    def process_job(self, job: Dict[str, Any]) -> None:
        job_id = UUID(str(job["id"]))
        book_id = str(job["book_id"])
        isbn = str(job["isbn"])
        job_type = JobType(str(job["job_type"]))
        prompt_version = "v1"
        process_version = self.storage.settings.process_version_strategy.format(
            linear_prompt_version=self.storage.settings.linear_prompt_version,
            context_prompt_version=self.storage.settings.context_prompt_version,
            dorina_prompt_version=self.storage.settings.dorina_prompt_version,
        )
        pdf_storage_path = str(job.get("storage_path_pdf") or "")

        self.jobs_repo.update_stage(job_id, "preprocess")
        pages, figures, figure_id_map, figure_storage_map = self._run_preprocess(book_id, isbn, pdf_storage_path)
        figure_map = map_figures_by_page(figures)

        if job_type == JobType.LINEARIZAR:
            self.jobs_repo.update_stage(job_id, "linearize")
        else:
            self.jobs_repo.update_stage(job_id, "context")
        linearized_pages: List[Dict[str, Any]] = []
        contexts: Dict[str, str] = {}

        for page in pages:
            page_figures = figure_map.get(page.page_number, [])
            figure_keys = [f.figure_key for f in page_figures]

            page_content: Dict[str, Any]
            if self.storage.settings.openai_combined_mode:
                combined = self.openai.linearize_and_extract_context(page.page_png, figure_keys, prompt_version)
                page_content = combined["page_structure"]
                contexts.update(combined["figure_contexts"])
            elif job_type == JobType.LINEARIZAR:
                page_content = self.openai.linearize_page(page.page_png, prompt_version)
            else:
                page_content = {"mode": "contextualizar", "page_number": page.page_number}

            linearized_pages.append(
                {
                    "page_number": page.page_number,
                    "content": page_content,
                    "figure_refs": figure_keys,
                }
            )

            if figure_keys:
                page_contexts = self.openai.extract_context(page.page_png, figure_keys, prompt_version)
                contexts.update(page_contexts)
                for key, context in page_contexts.items():
                    figure_id = figure_id_map.get(key)
                    if figure_id:
                        self.artifacts_repo.save_context(figure_id, context, prompt_version)

        self.jobs_repo.update_stage(job_id, "dorina")
        descriptions: List[Dict[str, Any]] = []
        for figure in figures:
            figure_id = figure_id_map.get(figure.figure_key)
            if not figure_id:
                logger.warning("Figura %s sem ID persistido. Pulando descricao.", figure.figure_key)
                continue
            storage_path = figure_storage_map.get(figure.figure_key, "")
            if not storage_path:
                logger.warning("Figura %s sem storage_path. Pulando descricao.", figure.figure_key)
                continue
            context = contexts.get(figure.figure_key, "")
            signed_url = self.storage.signed_url_for_storage_path(
                storage_path,
                expires_in=self.storage.settings.dorina_signed_url_expires_seconds,
            )
            description_payload = self.dorina.describe_figure(
                image_url=signed_url,
                isbn=isbn,
                context=context,
                prompt_version=prompt_version,
            )
            descriptions.append({"figure_key": figure.figure_key, "figure_id": figure_id, **description_payload})
            self.artifacts_repo.save_description(figure_id, prompt_version, description_payload)

        self.jobs_repo.update_stage(job_id, "assemble")
        final_payload = {
            "isbn": isbn,
            "job_id": str(job_id),
            "job_type": job_type.value,
            "prompt_version": prompt_version,
            "pages": linearized_pages,
            "image_context": [{"figure_id": key, "context": ctx} for key, ctx in contexts.items()],
            "descriptions": descriptions,
        }
        final_payload["process_version"] = process_version
        final_storage_path = self.storage.upload_json(isbn, process_version, str(job_id), "final.json", final_payload)
        self.artifacts_repo.save_final_payload(job_id, final_payload, final_storage_path)

        self.jobs_repo.update_stage(job_id, "export")
        if job_type == JobType.LINEARIZAR:
            pb_result = self.pb_exporter.export(final_payload)
            self.artifacts_repo.add_export_pb(book_id, pb_result, pb_result.get("status", "unknown"))
        else:
            for description in descriptions:
                avalia_payload = {
                    "isbn": isbn,
                    "job_id": str(job_id),
                    "figure_id": description["figure_id"],
                    "description": description.get("description", ""),
                }
                avalia_result = self.avalia_exporter.export(avalia_payload)
                self.artifacts_repo.add_export_avalia(
                    description["figure_id"],
                    avalia_result,
                    avalia_result.get("status", "unknown"),
                )

        self.jobs_repo.mark_done(job_id)
        logger.info("Job %s finalizado com sucesso.", job_id)

    def _run_preprocess(self, book_id: str, isbn: str, pdf_storage_path: str):
        pdf_bytes = self.storage.download_by_storage_path(pdf_storage_path or f"pdf/{isbn}/original.pdf")
        pages = preprocess_pdf(pdf_bytes)
        figures: List[FigureArtifact] = []
        figure_id_map: Dict[str, str] = {}
        figure_storage_map: Dict[str, str] = {}

        for page in pages:
            process_version = self.storage.settings.process_version_strategy.format(
                linear_prompt_version=self.storage.settings.linear_prompt_version,
                context_prompt_version=self.storage.settings.context_prompt_version,
                dorina_prompt_version=self.storage.settings.dorina_prompt_version,
            )
            page_storage_path = self.storage.upload_page(isbn, page.page_name, page.page_png, process_version=process_version)
            width_px, height_px = page.source_rgb_image.size
            page_id = self.artifacts_repo.add_page(book_id, page.page_number, page_storage_path, width_px, height_px)

            page_figures = extract_figures_from_page(page)
            for fig in page_figures:
                figure_storage_path = self.storage.upload_figure(
                    isbn=isbn,
                    page_folder=fig.page_folder,
                    figure_name=fig.figure_name,
                    content=fig.figure_png,
                    process_version=process_version,
                )
                figure_id = self.artifacts_repo.add_figure(book_id, page_id, fig.figure_index, figure_storage_path)
                figure_id_map[fig.figure_key] = figure_id
                figure_storage_map[fig.figure_key] = figure_storage_path
            figures.extend(page_figures)
        return pages, figures, figure_id_map, figure_storage_map
