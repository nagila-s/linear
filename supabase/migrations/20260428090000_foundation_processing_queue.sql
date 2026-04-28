-- Foundation fila/jobs para Linear.

CREATE TABLE IF NOT EXISTS public.job_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id UUID NOT NULL REFERENCES public.jobs(id) ON DELETE CASCADE,
  stage TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  idempotency_key TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  next_retry_at TIMESTAMPTZ,
  last_error TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (idempotency_key)
);

ALTER TABLE public.jobs
  ADD COLUMN IF NOT EXISTS run_after TIMESTAMPTZ DEFAULT now(),
  ADD COLUMN IF NOT EXISTS worker_id TEXT,
  ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 3,
  ADD COLUMN IF NOT EXISTS processed_items INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS failed_items INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_jobs_queue ON public.jobs(status, run_after, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_running_heartbeat ON public.jobs(status, heartbeat_at);
CREATE INDEX IF NOT EXISTS idx_job_items_job_id ON public.job_items(job_id, created_at);
