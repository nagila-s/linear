-- Artefatos/versionamento obrigatorios + idempotencia.

CREATE TABLE IF NOT EXISTS public.artifacts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id UUID NOT NULL REFERENCES public.jobs(id) ON DELETE CASCADE,
  artifact_type TEXT NOT NULL DEFAULT 'final_json',
  storage_path TEXT,
  payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  version_tag TEXT,
  checksum TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.jobs
  ADD COLUMN IF NOT EXISTS prompt_version TEXT,
  ADD COLUMN IF NOT EXISTS openai_model TEXT,
  ADD COLUMN IF NOT EXISTS dorina_model TEXT,
  ADD COLUMN IF NOT EXISTS pipeline_mode TEXT,
  ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;

ALTER TABLE public.figures
  ADD COLUMN IF NOT EXISTS context_prompt_version TEXT;

ALTER TABLE public.descriptions
  ADD COLUMN IF NOT EXISTS dorina_prompt_version TEXT,
  ADD COLUMN IF NOT EXISTS dorina_model_version TEXT;

ALTER TABLE public.artifacts
  ADD COLUMN IF NOT EXISTS artifact_type TEXT DEFAULT 'final_json',
  ADD COLUMN IF NOT EXISTS storage_path TEXT,
  ADD COLUMN IF NOT EXISTS version_tag TEXT,
  ADD COLUMN IF NOT EXISTS checksum TEXT,
  ADD COLUMN IF NOT EXISTS payload_json JSONB DEFAULT '{}'::jsonb;

CREATE UNIQUE INDEX IF NOT EXISTS uq_pages_book_page ON public.pages(book_id, page_number);
CREATE UNIQUE INDEX IF NOT EXISTS uq_figures_page_index ON public.figures(page_id, figure_index);
CREATE UNIQUE INDEX IF NOT EXISTS uq_descriptions_figure_prompt ON public.descriptions(figure_id, prompt_version);
CREATE UNIQUE INDEX IF NOT EXISTS uq_artifacts_job_type ON public.artifacts(job_id, artifact_type);
