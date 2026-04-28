import logging
from uuid import UUID

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import get_settings
from src.core.errors import AppError, ValidationError
from src.core.logging import configure_logging
from src.models.enums import JobType
from src.models.schemas import HealthResponse, JobResponse
from src.repositories.books import BooksRepository
from src.repositories.jobs import JobsRepository
from src.services.isbn import normalize_isbn
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
storage = StorageService()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.post(f"{settings.api_prefix}/jobs/upload", response_model=JobResponse)
async def create_job_from_upload(
    isbn: str = Form(...),
    job_type: JobType = Form(...),
    prompt_version: str = Form("v1"),
    pdf_file: UploadFile = File(...),
) -> JobResponse:
    try:
        normalized_isbn = normalize_isbn(isbn)
        if pdf_file.content_type not in ("application/pdf", "application/octet-stream"):
            raise ValidationError("Arquivo precisa ser PDF.")

        pdf_content = await pdf_file.read()
        if not pdf_content:
            raise ValidationError("Arquivo PDF vazio.")

        process_version = settings.process_version_strategy.format(
            linear_prompt_version=settings.linear_prompt_version,
            context_prompt_version=settings.context_prompt_version,
            dorina_prompt_version=settings.dorina_prompt_version,
        )
        storage_path_pdf = storage.upload_pdf(normalized_isbn, pdf_content, process_version=process_version)
        books_repo.upsert(
            normalized_isbn,
            metadata={
                "filename": pdf_file.filename or "original.pdf",
                "storage_path_pdf": storage_path_pdf,
            },
        )
        created = jobs_repo.create(
            isbn=normalized_isbn,
            job_type=job_type,
            prompt_version=prompt_version,
            metadata={
                "filename": pdf_file.filename or "original.pdf",
                "pipeline_mode": job_type.value,
                "process_version": process_version,
                "openai_model": settings.openai_model_linearization,
                "dorina_model": "dorina-default",
            },
        )
        return JobResponse.model_validate(created)
    except AppError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
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
    job_type: JobType = Form(...),
    prompt_version: str = Form("v1"),
    files: list[UploadFile] = File(...),
    isbn: str | None = Form(None),
) -> dict:
    try:
        if not files:
            raise ValidationError("Nenhum arquivo enviado.")
        if len(files) > 1 and isbn:
            raise ValidationError("Para upload multiplo, ISBN deve vir no nome de cada arquivo.")

        process_version = settings.process_version_strategy.format(
            linear_prompt_version=settings.linear_prompt_version,
            context_prompt_version=settings.context_prompt_version,
            dorina_prompt_version=settings.dorina_prompt_version,
        )
        created_jobs = []
        for file in files:
            if file.content_type not in ("application/pdf", "application/octet-stream"):
                raise ValidationError(f"Arquivo invalido: {file.filename}")

            pdf_content = await file.read()
            if not pdf_content:
                raise ValidationError(f"Arquivo PDF vazio: {file.filename}")

            if len(files) == 1 and isbn:
                normalized_isbn = normalize_isbn(isbn)
            else:
                normalized_isbn = normalize_isbn((file.filename or "").rsplit(".", 1)[0])

            storage_path_pdf = storage.upload_pdf(normalized_isbn, pdf_content, process_version=process_version)
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
                    "pipeline_mode": job_type.value,
                    "process_version": process_version,
                    "openai_model": settings.openai_model_linearization,
                    "dorina_model": "dorina-default",
                },
            )
            created_jobs.append({"job_id": str(created["id"]), "isbn": normalized_isbn})

        return {"count": len(created_jobs), "jobs": created_jobs}
    except AppError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Erro ao criar jobs em lote: %s", exc)
        raise HTTPException(status_code=500, detail="Falha interna ao criar jobs em lote.") from exc


@app.get(f"{settings.api_prefix}/jobs/{{job_id}}/result-url")
def get_result_url(job_id: UUID) -> dict:
    data = jobs_repo.get(job_id)
    if not data:
        raise HTTPException(status_code=404, detail="Job nao encontrado.")
    if data.get("status") != "done":
        raise HTTPException(status_code=409, detail="Job ainda nao finalizado.")

    isbn = data["isbn"]
    metadata = data.get("metadata") or {}
    process_version = metadata.get("process_version", "v1")
    url = storage.signed_json_url(isbn, process_version, str(job_id), "final.json")
    return {"job_id": str(job_id), "download_url": url}
