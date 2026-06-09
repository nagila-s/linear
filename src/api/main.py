import logging
from uuid import UUID

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import get_settings
from src.core.errors import AppError, ValidationError
from src.core.logging import configure_logging
from src.models.enums import JobStatus, JobType
from src.models.schemas import (
    HealthResponse,
    JobResponse,
    UploadCompleteRequest,
    UploadInitRequest,
    UploadInitResponse,
)
from src.repositories.artifacts import ArtifactsRepository
from src.repositories.books import BooksRepository
from src.repositories.jobs import JobsRepository
from src.services.isbn import normalize_isbn, resolve_book_key
from src.services.pdf_storage import PdfStorageService, is_payload_too_large
from src.services.storage import StorageService

load_dotenv()
configure_logging()
logger = logging.getLogger(__name__)

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

books_repo = BooksRepository()
jobs_repo = JobsRepository()
artifacts_repo = ArtifactsRepository()
storage = StorageService()
pdf_storage = PdfStorageService(storage)


def _process_version() -> str:
    return settings.process_version_strategy.format(
        linear_prompt_version=settings.linear_prompt_version,
    )


def _create_linearize_job(
    *,
    normalized_isbn: str,
    filename: str,
    storage_path_pdf: str,
    prompt_version: str,
) -> JobResponse:
    process_version = _process_version()
    books_repo.upsert(
        normalized_isbn,
        metadata={
            "filename": filename,
            "storage_path_pdf": storage_path_pdf,
        },
    )
    created = jobs_repo.create(
        isbn=normalized_isbn,
        job_type=JobType.LINEARIZAR,
        prompt_version=prompt_version,
        metadata={
            "filename": filename,
            "pipeline_mode": JobType.LINEARIZAR.value,
            "linearize_only": True,
            "process_version": process_version,
            "openai_model": settings.openai_model_linearization,
            "pdf_render_dpi": settings.pdf_render_dpi,
            "pdf_storage_path": storage_path_pdf,
        },
    )
    return JobResponse.model_validate(created)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.post(f"{settings.api_prefix}/jobs/upload-init", response_model=UploadInitResponse)
def init_presigned_upload(payload: UploadInitRequest) -> UploadInitResponse:
    try:
        if payload.job_type != JobType.LINEARIZAR:
            raise ValidationError("Apenas jobs do tipo 'linearizar' estao habilitados.")
        if not payload.filename.lower().endswith(".pdf"):
            raise ValidationError("Arquivo precisa ser PDF.")

        normalized_isbn = resolve_book_key(payload.isbn, payload.filename)
        process_version = _process_version()
        upload_info = storage.create_pdf_upload_url(normalized_isbn, process_version)
        return UploadInitResponse(
            signed_url=upload_info["signed_url"],
            token=upload_info["token"],
            storage_path=upload_info["storage_path"],
            isbn=normalized_isbn,
            process_version=process_version,
            bucket=upload_info["bucket"],
            object_path=upload_info["object_path"],
        )
    except AppError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Erro ao iniciar upload assinado: %s", exc)
        raise HTTPException(status_code=500, detail="Falha ao preparar upload do PDF.") from exc


@app.post(f"{settings.api_prefix}/jobs/upload-complete", response_model=JobResponse)
def complete_presigned_upload(payload: UploadCompleteRequest) -> JobResponse:
    try:
        if payload.job_type != JobType.LINEARIZAR:
            raise ValidationError("Apenas jobs do tipo 'linearizar' estao habilitados.")

        normalized_isbn = normalize_isbn(payload.isbn)
        if not payload.object_path.startswith(f"{normalized_isbn}/"):
            raise ValidationError("object_path nao corresponde ao ISBN informado.")

        expected_storage = f"{settings.bucket_pdf}/{payload.object_path}"
        if payload.storage_path != expected_storage:
            raise ValidationError("storage_path invalido para este upload.")

        if not storage.pdf_object_exists(payload.object_path):
            raise ValidationError("PDF ainda nao encontrado no storage. Conclua o upload antes de finalizar.")

        return _create_linearize_job(
            normalized_isbn=normalized_isbn,
            filename=payload.filename,
            storage_path_pdf=payload.storage_path,
            prompt_version=payload.prompt_version,
        )
    except AppError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Erro ao concluir upload assinado: %s", exc)
        raise HTTPException(status_code=500, detail="Falha ao enfileirar job apos upload.") from exc


@app.post(f"{settings.api_prefix}/jobs/upload", response_model=JobResponse)
async def create_job_from_upload(
    isbn: str | None = Form(None),
    job_type: JobType = Form(JobType.LINEARIZAR),
    prompt_version: str = Form("v1"),
    pdf_file: UploadFile = File(...),
) -> JobResponse:
    try:
        if job_type != JobType.LINEARIZAR:
            raise ValidationError("Apenas jobs do tipo 'linearizar' estao habilitados.")

        normalized_isbn = resolve_book_key(isbn, pdf_file.filename)
        if pdf_file.content_type not in ("application/pdf", "application/octet-stream"):
            raise ValidationError("Arquivo precisa ser PDF.")

        pdf_content = await pdf_file.read()
        if not pdf_content:
            raise ValidationError("Arquivo PDF vazio.")

        process_version = _process_version()
        storage_path_pdf = pdf_storage.store(normalized_isbn, pdf_content, process_version=process_version)
        return _create_linearize_job(
            normalized_isbn=normalized_isbn,
            filename=pdf_file.filename or "original.pdf",
            storage_path_pdf=storage_path_pdf,
            prompt_version=prompt_version,
        )
    except AppError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        if is_payload_too_large(exc) and settings.pdf_storage_strategy == "supabase":
            raise HTTPException(
                status_code=413,
                detail=(
                    "PDF excede o limite do Supabase Storage. No plano Free o teto global e 50 MB; "
                    "em Pro/Team aumente em Storage Settings (ate 500 GB) ou use PDF_STORAGE_STRATEGY=auto."
                ),
            ) from exc
        logger.exception("Erro ao criar job: %s", exc)
        raise HTTPException(status_code=500, detail="Falha interna ao criar job.") from exc


@app.get(f"{settings.api_prefix}/jobs/{{job_id}}", response_model=JobResponse)
def get_job(job_id: UUID) -> JobResponse:
    data = jobs_repo.get(job_id)
    if not data:
        raise HTTPException(status_code=404, detail="Job nao encontrado.")
    return JobResponse.model_validate(data)


@app.post(f"{settings.api_prefix}/jobs/{{job_id}}/retry")
def retry_job(job_id: UUID) -> dict:
    data = jobs_repo.get(job_id)
    if not data:
        raise HTTPException(status_code=404, detail="Job nao encontrado.")
    jobs_repo.retry(job_id)
    return {"status": "queued", "job_id": str(job_id)}


@app.post(f"{settings.api_prefix}/jobs/upload-multi")
async def create_jobs_from_multi_upload(
    job_type: JobType = Form(JobType.LINEARIZAR),
    prompt_version: str = Form("v1"),
    files: list[UploadFile] = File(...),
    isbn: str | None = Form(None),
) -> dict:
    try:
        if job_type != JobType.LINEARIZAR:
            raise ValidationError("Apenas jobs do tipo 'linearizar' estao habilitados.")

        if not files:
            raise ValidationError("Nenhum arquivo enviado.")
        if len(files) > 1 and isbn:
            raise ValidationError("Para upload multiplo, ISBN deve vir no nome de cada arquivo.")

        process_version = settings.process_version_strategy.format(
            linear_prompt_version=settings.linear_prompt_version,
        )
        created_jobs = []
        for file in files:
            if file.content_type not in ("application/pdf", "application/octet-stream"):
                raise ValidationError(f"Arquivo invalido: {file.filename}")

            pdf_content = await file.read()
            if not pdf_content:
                raise ValidationError(f"Arquivo PDF vazio: {file.filename}")

            file_isbn = isbn if len(files) == 1 else None
            normalized_isbn = resolve_book_key(file_isbn, file.filename)

            storage_path_pdf = pdf_storage.store(normalized_isbn, pdf_content, process_version=process_version)
            books_repo.upsert(
                normalized_isbn,
                metadata={
                    "filename": file.filename or "original.pdf",
                    "storage_path_pdf": storage_path_pdf,
                },
            )
            created = jobs_repo.create(
                isbn=normalized_isbn,
                job_type=job_type,
                prompt_version=prompt_version,
                metadata={
                    "filename": file.filename or "original.pdf",
                    "pipeline_mode": JobType.LINEARIZAR.value,
                    "linearize_only": True,
                    "process_version": process_version,
                    "openai_model": settings.openai_model_linearization,
                    "pdf_render_dpi": settings.pdf_render_dpi,
                    "pdf_storage_path": storage_path_pdf,
                },
            )
            created_jobs.append({"job_id": str(created["id"]), "isbn": normalized_isbn})

        return {"count": len(created_jobs), "jobs": created_jobs}
    except AppError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Erro ao criar jobs em lote: %s", exc)
        raise HTTPException(status_code=500, detail="Falha interna ao criar jobs em lote.") from exc


def _job_status_str(data: dict) -> str:
    raw = data.get("status")
    if raw is None:
        return ""
    if hasattr(raw, "value"):
        return str(raw.value)
    return str(raw)


@app.get(f"{settings.api_prefix}/jobs/{{job_id}}/result-url")
def get_result_url(job_id: UUID) -> dict:
    data = jobs_repo.get(job_id)
    if not data:
        raise HTTPException(status_code=404, detail="Job nao encontrado.")
    status_val = _job_status_str(data)
    artifact_storage_path = artifacts_repo.get_final_json_storage_path(job_id)
    has_final = artifact_storage_path is not None
    if status_val != JobStatus.DONE.value and not has_final:
        raise HTTPException(status_code=409, detail="Job ainda nao finalizado.")

    isbn = data["isbn"]
    metadata = data.get("metadata") or {}
    process_version = metadata.get("process_version", "v1")
    if artifact_storage_path:
        url = storage.signed_url_for_storage_path(artifact_storage_path)
    else:
        url = storage.signed_json_url(isbn, process_version, str(job_id), "final.json")
    out: dict = {"job_id": str(job_id), "download_url": url}
    if status_val != JobStatus.DONE.value and has_final:
        out["note"] = (
            "JSON disponivel (artefato gravado), mas o status do job na BD nao e 'done' "
            "(ex.: falha apos gravar o final ou encerramento manual). Considere corrigir o status."
        )
    return out
