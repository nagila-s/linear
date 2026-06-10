from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from src.models.enums import JobStatus, JobType


class CreateJobPayload(BaseModel):
    isbn: str = Field(min_length=1, max_length=128)
    job_type: JobType
    prompt_version: str = Field(default="v1")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class JobResponse(BaseModel):
    id: UUID
    isbn: str
    job_type: JobType
    status: JobStatus
    etapa_atual: str
    tentativas: int
    created_at: datetime
    updated_at: datetime
    error_message: Optional[str] = None
    prompt_version: Optional[str] = None
    openai_model: Optional[str] = None
    dorina_model: Optional[str] = None
    pipeline_mode: Optional[str] = None
    final_json_storage_path: Optional[str] = None


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "linear-backend"


class BookListItem(BaseModel):
    id: str
    title: str
    createdAt: str
    actions: List[str] = Field(default_factory=list)
    status: str


class BookListResponse(BaseModel):
    books: List[BookListItem] = Field(default_factory=list)


class UploadInitRequest(BaseModel):
    isbn: Optional[str] = None
    filename: str = Field(min_length=1, max_length=512)
    job_type: JobType = JobType.LINEARIZAR
    prompt_version: str = Field(default="v1")


class UploadInitResponse(BaseModel):
    signed_url: str
    token: str
    storage_path: str
    isbn: str
    process_version: str
    bucket: str
    object_path: str


class UploadCompleteRequest(BaseModel):
    isbn: str = Field(min_length=1, max_length=128)
    storage_path: str = Field(min_length=3)
    object_path: str = Field(min_length=3)
    token: str = Field(min_length=1)
    filename: str = Field(min_length=1, max_length=512)
    job_type: JobType = JobType.LINEARIZAR
    prompt_version: str = Field(default="v1")


class FigureContext(BaseModel):
    figure_id: str
    context: str


class LinearizedPage(BaseModel):
    page_number: int
    content: Dict[str, Any]
    figure_refs: List[str] = Field(default_factory=list)


class FinalPayload(BaseModel):
    isbn: str
    job_id: UUID
    job_type: JobType
    prompt_version: str
    pages: List[LinearizedPage] = Field(default_factory=list)
    image_context: List[FigureContext] = Field(default_factory=list)
    descriptions: List[Dict[str, Any]] = Field(default_factory=list)
