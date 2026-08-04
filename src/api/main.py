import logging
import json
from uuid import UUID

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import get_settings
from src.core.errors import AppError, ValidationError
from src.core.logging import configure_logging
from src.models.enums import JobStatus, JobType
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.models.schemas import (
    BookListItem,
    BookListResponse,
    HealthResponse,
    JobResponse,
    QueueItem,
    QueueResponse,
    UploadCompleteRequest,
    UploadInitRequest,
    UploadInitResponse,
)
from src.pipeline.steps.preprocess import count_pdf_pages
from src.repositories.artifacts import ArtifactsRepository
from src.repositories.books import BooksRepository
from src.repositories.jobs import JobsRepository
from src.services.isbn import resolve_book_key, validate_book_key
from src.services.pdf_storage import PdfStorageService, is_payload_too_large
from src.services.prompt_router import sanitize_prompt_overrides
from src.services.storage import StorageService

load_dotenv()
configure_logging()
logger = logging.getLogger(__name__)

# Estimativa com base em testes anteriores.
SECONDS_PER_PAGE = 25
QUEUE_CALIBRATION_NOTE = "Estimativa com base em testes anteriores: 25 s por página."

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
    miolo_only: bool = False,
    test_run: bool = False,
    prompt_overrides: dict[str, str] | None = None,
    page_count: int | None = None,
) -> JobResponse:
    process_version = _process_version()
    overrides = sanitize_prompt_overrides(prompt_overrides)
    is_test = bool(test_run) or bool(overrides)
    books_repo.upsert(
        normalized_isbn,
        metadata={
            "filename": filename,
            "storage_path_pdf": storage_path_pdf,
        },
    )
    job_metadata: dict = {
        "filename": filename,
        "pipeline_mode": JobType.LINEARIZAR.value,
        "linearize_only": True,
        "miolo_only": bool(miolo_only),
        "process_version": process_version,
        "openai_model": settings.openai_model_linearization,
        "pdf_render_dpi": settings.pdf_render_dpi,
        "pdf_storage_path": storage_path_pdf,
    }
    if page_count and page_count > 0:
        job_metadata["page_count"] = int(page_count)
    if is_test:
        job_metadata["test_run"] = True
    if overrides:
        job_metadata["prompt_overrides"] = overrides
    created = jobs_repo.create(
        isbn=normalized_isbn,
        job_type=JobType.LINEARIZAR,
        prompt_version=prompt_version,
        metadata=job_metadata,
    )
    return JobResponse.model_validate(created)


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _queue_message(status: str, stage: str, error: str | None = None) -> str:
    normalized = (status or "").lower()
    if normalized == JobStatus.QUEUED.value:
        return "Na fila, aguardando a vez."
    if normalized == JobStatus.RETRYING.value:
        return "Reprocessando após falha temporária."
    if normalized == JobStatus.RUNNING.value:
        stage_map = {
            "preprocess": "Preparando páginas do PDF...",
            "pages": "Preparando páginas do PDF...",
            "extract": "Extraindo figuras...",
            "linearize": "Linearizando com IA...",
            "describe": "Descrevendo figuras (Dorina)...",
            "assemble": "Montando o JSON final...",
        }
        return stage_map.get((stage or "").lower(), "Processando...")
    if normalized == JobStatus.DONE.value:
        return "Concluído."
    if normalized == JobStatus.PARTIAL_SUCCESS.value:
        return "Concluído com avisos."
    if normalized == JobStatus.FAILED.value:
        detail = (error or "").strip()
        return f"Falhou: {detail[:180]}" if detail else "Falhou."
    return status or "—"


def _estimate_open_queue(rows: list[dict]) -> list[QueueItem]:
    now = datetime.now(timezone.utc)
    cursor = now
    items: list[QueueItem] = []
    eta_blocked = False

    for index, row in enumerate(rows, start=1):
        metadata = row.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        page_count_raw = metadata.get("page_count")
        try:
            page_count = int(page_count_raw) if page_count_raw is not None else None
        except (TypeError, ValueError):
            page_count = None
        if page_count is not None and page_count <= 0:
            page_count = None

        title = (
            str(row.get("titulo") or "").strip()
            or str(metadata.get("filename") or metadata.get("title") or "").strip()
            or str(row.get("isbn") or "Livro")
        )
        status = str(row.get("status") or "")
        stage = str(row.get("etapa_atual") or "")
        started_at = row.get("started_at")
        duration = page_count * SECONDS_PER_PAGE if page_count else None

        estimated_start: datetime | None = None
        estimated_end: datetime | None = None

        if duration is None:
            eta_blocked = True
        elif not eta_blocked:
            if status == JobStatus.RUNNING.value and isinstance(started_at, datetime):
                started = started_at if started_at.tzinfo else started_at.replace(tzinfo=timezone.utc)
                elapsed = max(0, int((now - started).total_seconds()))
                remaining = max(0, duration - elapsed)
                estimated_start = started
                estimated_end = now + timedelta(seconds=remaining)
                cursor = estimated_end
            elif status in (JobStatus.QUEUED.value, JobStatus.RETRYING.value):
                estimated_start = cursor
                estimated_end = cursor + timedelta(seconds=duration)
                cursor = estimated_end

        items.append(
            QueueItem(
                id=str(row["id"]),
                title=title,
                isbn=str(row.get("isbn") or ""),
                status=status,
                stage=stage,
                message=_queue_message(status, stage, row.get("erro")),
                pageCount=page_count,
                createdAt=_iso(row.get("created_at")) or "",
                startedAt=_iso(started_at if isinstance(started_at, datetime) else None),
                finishedAt=_iso(row.get("finished_at") if isinstance(row.get("finished_at"), datetime) else None),
                estimatedDurationSeconds=duration,
                estimatedStartAt=_iso(estimated_start),
                estimatedEndAt=_iso(estimated_end),
                queuePosition=index,
                canDownload=False,
                errorMessage=(str(row.get("erro") or "").strip() or None),
            )
        )
    return items


def _map_finished_queue(rows: list[dict]) -> list[QueueItem]:
    items: list[QueueItem] = []
    for row in rows:
        metadata = row.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        page_count_raw = metadata.get("page_count")
        try:
            page_count = int(page_count_raw) if page_count_raw is not None else None
        except (TypeError, ValueError):
            page_count = None
        if page_count is not None and page_count <= 0:
            page_count = None
        title = (
            str(row.get("titulo") or "").strip()
            or str(metadata.get("filename") or metadata.get("title") or "").strip()
            or str(row.get("isbn") or "Livro")
        )
        status = str(row.get("status") or "")
        started_at = row.get("started_at")
        finished_at = row.get("finished_at")
        duration = None
        if isinstance(started_at, datetime) and isinstance(finished_at, datetime):
            s = started_at if started_at.tzinfo else started_at.replace(tzinfo=timezone.utc)
            f = finished_at if finished_at.tzinfo else finished_at.replace(tzinfo=timezone.utc)
            duration = max(0, int((f - s).total_seconds()))
        items.append(
            QueueItem(
                id=str(row["id"]),
                title=title,
                isbn=str(row.get("isbn") or ""),
                status=status,
                stage=str(row.get("etapa_atual") or ""),
                message=_queue_message(status, str(row.get("etapa_atual") or ""), row.get("erro")),
                pageCount=page_count,
                createdAt=_iso(row.get("created_at")) or "",
                startedAt=_iso(started_at if isinstance(started_at, datetime) else None),
                finishedAt=_iso(finished_at if isinstance(finished_at, datetime) else None),
                estimatedDurationSeconds=duration,
                canDownload=status in (JobStatus.DONE.value, JobStatus.PARTIAL_SUCCESS.value),
                errorMessage=(str(row.get("erro") or "").strip() or None),
            )
        )
    return items


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


def _map_job_ui_status(raw_status: str) -> str:
    normalized = (raw_status or "").lower()
    if normalized == JobStatus.DONE.value:
        return "done"
    if normalized == JobStatus.FAILED.value:
        return "error"
    return "processing"


@app.get(f"{settings.api_prefix}/books", response_model=BookListResponse)
def list_books(limit: int = 100) -> BookListResponse:
    try:
        rows = books_repo.list_with_latest_job(limit=min(max(limit, 1), 200))
        books: list[BookListItem] = []
        for row in rows:
            metadata = row.get("metadata") or {}
            if not isinstance(metadata, dict):
                metadata = {}
            title = (
                str(row.get("titulo") or "").strip()
                or str(metadata.get("filename") or metadata.get("title") or "").strip()
                or str(row.get("isbn") or "Livro")
            )
            job_type = str(row.get("job_type") or JobType.LINEARIZAR.value)
            actions = ["Linearizar"] if job_type == JobType.LINEARIZAR.value else [job_type]
            created_at = row.get("job_created_at")
            books.append(
                BookListItem(
                    id=str(row["job_id"]),
                    title=title,
                    createdAt=created_at.isoformat() if created_at else "",
                    actions=actions,
                    status=_map_job_ui_status(str(row.get("status") or "")),
                )
            )
        return BookListResponse(books=books)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Erro ao listar livros: %s", exc)
        raise HTTPException(status_code=500, detail="Falha ao listar livros processados.") from exc


@app.get(f"{settings.api_prefix}/queue", response_model=QueueResponse)
def list_processing_queue(tab: str = "open", limit: int = 100) -> QueueResponse:
    normalized_tab = (tab or "open").strip().lower()
    if normalized_tab not in ("open", "finished"):
        raise HTTPException(status_code=400, detail="tab deve ser 'open' ou 'finished'.")
    try:
        rows = jobs_repo.list_queue(tab=normalized_tab, limit=limit)
        items = _estimate_open_queue(rows) if normalized_tab == "open" else _map_finished_queue(rows)
        return QueueResponse(
            tab=normalized_tab,
            items=items,
            secondsPerPage=SECONDS_PER_PAGE,
            calibrationNote=QUEUE_CALIBRATION_NOTE,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Erro ao listar fila: %s", exc)
        raise HTTPException(status_code=500, detail="Falha ao listar fila de processamento.") from exc


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

        book_key = validate_book_key(payload.isbn)
        if not payload.object_path.startswith(f"{book_key}/"):
            raise ValidationError("object_path nao corresponde ao identificador do livro.")

        expected_storage = f"{settings.bucket_pdf}/{payload.object_path}"
        if payload.storage_path != expected_storage:
            raise ValidationError("storage_path invalido para este upload.")

        if not storage.pdf_object_exists(payload.object_path):
            raise ValidationError("PDF ainda nao encontrado no storage. Conclua o upload antes de finalizar.")

        page_count = payload.page_count
        if not page_count:
            try:
                pdf_bytes = storage.download_by_storage_path(payload.storage_path)
                page_count = count_pdf_pages(pdf_bytes)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Nao foi possivel contar paginas no upload-complete de %s",
                    payload.filename,
                    exc_info=True,
                )
                page_count = None

        return _create_linearize_job(
            normalized_isbn=book_key,
            filename=payload.filename,
            storage_path_pdf=payload.storage_path,
            prompt_version=payload.prompt_version,
            miolo_only=payload.miolo_only,
            test_run=payload.test_run,
            prompt_overrides=payload.prompt_overrides,
            page_count=page_count,
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
    miolo_only: bool = Form(False),
    test_run: bool = Form(False),
    prompt_overrides: str | None = Form(None),
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

        overrides_payload: dict[str, str] | None = None
        if prompt_overrides:
            try:
                parsed = json.loads(prompt_overrides)
            except json.JSONDecodeError as exc:
                raise ValidationError("prompt_overrides deve ser JSON valido.") from exc
            overrides_payload = sanitize_prompt_overrides(parsed) or None

        process_version = _process_version()
        storage_path_pdf = pdf_storage.store(normalized_isbn, pdf_content, process_version=process_version)
        page_count: int | None = None
        try:
            page_count = count_pdf_pages(pdf_content)
        except Exception:  # noqa: BLE001
            logger.warning("Nao foi possivel contar paginas no upload de %s", pdf_file.filename, exc_info=True)
        return _create_linearize_job(
            normalized_isbn=normalized_isbn,
            filename=pdf_file.filename or "original.pdf",
            storage_path_pdf=storage_path_pdf,
            prompt_version=prompt_version,
            miolo_only=miolo_only,
            test_run=test_run,
            prompt_overrides=overrides_payload,
            page_count=page_count,
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


@app.post(f"{settings.api_prefix}/jobs/test-run")
async def test_run(
    isbn: str | None = Form(None),
    miolo_only: bool = Form(False),
    prompt_overrides: str | None = Form(None),
    pdf_file: UploadFile = File(...),
) -> dict:
    """Processa um PDF pequeno na hora (OpenAI + Dorina) e devolve o JSON.

    Nao cria job, nao usa fila/worker e nao grava nos prompts do sistema.
    """
    from starlette.concurrency import run_in_threadpool

    from src.pipeline.test_run import run_test_linearization

    try:
        if pdf_file.content_type not in ("application/pdf", "application/octet-stream"):
            raise ValidationError("Arquivo precisa ser PDF.")
        pdf_content = await pdf_file.read()
        if not pdf_content:
            raise ValidationError("Arquivo PDF vazio.")

        overrides_payload: dict[str, str] = {}
        if prompt_overrides:
            try:
                parsed = json.loads(prompt_overrides)
            except json.JSONDecodeError as exc:
                raise ValidationError("prompt_overrides deve ser JSON valido.") from exc
            overrides_payload = sanitize_prompt_overrides(parsed)

        normalized_isbn = resolve_book_key(isbn, pdf_file.filename)
        result = await run_in_threadpool(
            run_test_linearization,
            pdf_content,
            prompt_overrides=overrides_payload,
            miolo_only=miolo_only,
            isbn=normalized_isbn,
        )
        return result
    except AppError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Erro no test-run: %s", exc)
        raise HTTPException(status_code=500, detail=f"Falha no teste: {exc}") from exc


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
            page_count: int | None = None
            try:
                page_count = count_pdf_pages(pdf_content)
            except Exception:  # noqa: BLE001
                logger.warning("Nao foi possivel contar paginas no upload de %s", file.filename, exc_info=True)
            books_repo.upsert(
                normalized_isbn,
                metadata={
                    "filename": file.filename or "original.pdf",
                    "storage_path_pdf": storage_path_pdf,
                },
            )
            meta = {
                "filename": file.filename or "original.pdf",
                "pipeline_mode": JobType.LINEARIZAR.value,
                "linearize_only": True,
                "process_version": process_version,
                "openai_model": settings.openai_model_linearization,
                "pdf_render_dpi": settings.pdf_render_dpi,
                "pdf_storage_path": storage_path_pdf,
            }
            if page_count:
                meta["page_count"] = page_count
            created = jobs_repo.create(
                isbn=normalized_isbn,
                job_type=job_type,
                prompt_version=prompt_version,
                metadata=meta,
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
