from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Linear Pipeline Backend"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    api_prefix: str = "/api/v1"
    cors_origins: str = "*"

    supabase_url: str = Field(default="")
    supabase_service_role_key: str = Field(default="")
    supabase_db_dsn: str = Field(default="")
    bucket_pdf: str = "pdf"
    bucket_pages: str = "pages"
    bucket_figures: str = "figures"
    bucket_json: str = "json"

    openai_api_key: str = Field(default="")
    openai_model_linearization: str = "gpt-5.2-pro"
    openai_model_context: str = "gpt-5.2-pro"
    openai_combined_mode: bool = False
    openai_prefer_responses_api: bool = True
    linearization_prompt_file: str = "prompt.txt"
    linear_prompt_version: str = "v1"
    context_prompt_version: str = "v1"
    dorina_prompt_version: str = "v1"
    process_version_strategy: str = "lin-{linear_prompt_version}"

    dorina_api_url: str = Field(default="")
    dorina_api_key: str = Field(default="")
    dorina_api_key_header: str = "x-api-key"
    dorina_timeout_seconds: int = 60
    dorina_document_type: str = "string"
    dorina_braille: bool = False
    dorina_signed_url_expires_seconds: int = 3600

    pb_api_url: str = Field(default="")
    pb_api_key: str = Field(default="")
    avalia_api_url: str = Field(default="")
    avalia_api_key: str = Field(default="")

    worker_poll_seconds: int = 5
    worker_max_attempts: int = 3
    worker_stale_job_minutes: int = 120
    linear_pipeline_only: bool = True
    pdf_render_dpi: int = 150
    linearize_page_concurrency: int = 4
    # auto = Supabase; em 413 (limite do plano/bucket) grava em disco local compartilhado com o worker
    pdf_storage_strategy: str = "auto"
    pdf_local_cache_dir: str = "data/pdf_cache"
    pdf_max_size_mb: int = 1024

    @property
    def cors_origins_list(self) -> List[str]:
        raw = self.cors_origins.strip()
        if not raw:
            return []
        if raw == "*":
            return ["*"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
