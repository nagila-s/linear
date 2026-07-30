-- Fila exclusiva da área de testes (isolada de public.jobs / worker AWS).

CREATE EXTENSION IF NOT EXISTS pgmq;
CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE EXTENSION IF NOT EXISTS pg_net;

-- ---------------------------------------------------------------------------
-- Tabelas
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.test_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  isbn TEXT NOT NULL,
  filename TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'uploading'
    CHECK (status IN (
      'uploading', 'queued', 'running', 'partial_success', 'done', 'failed', 'cancelled'
    )),
  miolo_only BOOLEAN NOT NULL DEFAULT false,
  dpi INTEGER NOT NULL DEFAULT 120,
  total_pages INTEGER NOT NULL DEFAULT 0,
  total_figures INTEGER NOT NULL DEFAULT 0,
  processed_pages INTEGER NOT NULL DEFAULT 0,
  failed_pages INTEGER NOT NULL DEFAULT 0,
  processed_figures INTEGER NOT NULL DEFAULT 0,
  failed_figures INTEGER NOT NULL DEFAULT 0,
  prompt_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  prompt_hash TEXT NOT NULL DEFAULT '',
  final_storage_path TEXT,
  error_message TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS public.test_pages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id UUID NOT NULL REFERENCES public.test_jobs(id) ON DELETE CASCADE,
  page_number INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'queued', 'running', 'ok', 'failed', 'skipped')),
  page_type TEXT,
  page_storage_path TEXT NOT NULL,
  width_px INTEGER,
  height_px INTEGER,
  prompt_file TEXT,
  prompt_hash TEXT,
  openai_model TEXT,
  openai_response_id TEXT,
  content JSONB,
  error_message TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (job_id, page_number)
);

CREATE TABLE IF NOT EXISTS public.test_figures (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id UUID NOT NULL REFERENCES public.test_jobs(id) ON DELETE CASCADE,
  page_id UUID NOT NULL REFERENCES public.test_pages(id) ON DELETE CASCADE,
  page_number INTEGER NOT NULL,
  figure_key TEXT NOT NULL,
  figure_index INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'queued', 'running', 'ok', 'failed', 'skipped')),
  storage_path TEXT NOT NULL,
  width_px INTEGER,
  height_px INTEGER,
  bbox JSONB,
  context TEXT,
  description TEXT,
  dorina_payload JSONB,
  error_message TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (job_id, figure_key)
);

CREATE INDEX IF NOT EXISTS idx_test_jobs_status ON public.test_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_test_pages_job ON public.test_pages(job_id, page_number);
CREATE INDEX IF NOT EXISTS idx_test_pages_status ON public.test_pages(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_test_figures_job ON public.test_figures(job_id, page_number, figure_index);
CREATE INDEX IF NOT EXISTS idx_test_figures_status ON public.test_figures(status, updated_at);

-- ---------------------------------------------------------------------------
-- Storage bucket privado
-- ---------------------------------------------------------------------------

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
  'test-runs',
  'test-runs',
  false,
  524288000,
  ARRAY['application/pdf', 'image/png', 'application/json']::text[]
)
ON CONFLICT (id) DO UPDATE
SET
  public = EXCLUDED.public,
  file_size_limit = EXCLUDED.file_size_limit,
  allowed_mime_types = EXCLUDED.allowed_mime_types;

-- ---------------------------------------------------------------------------
-- RLS: sem policies → PostgREST anon/authenticated bloqueados; service_role ok
-- ---------------------------------------------------------------------------

ALTER TABLE public.test_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.test_pages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.test_figures ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------
-- Fila PGMQ (uma mensagem = uma etapa atômica)
-- ---------------------------------------------------------------------------

SELECT pgmq.create('test_run_queue');

-- ---------------------------------------------------------------------------
-- updated_at trigger
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.test_touch_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_test_jobs_updated ON public.test_jobs;
CREATE TRIGGER trg_test_jobs_updated
  BEFORE UPDATE ON public.test_jobs
  FOR EACH ROW EXECUTE FUNCTION public.test_touch_updated_at();

DROP TRIGGER IF EXISTS trg_test_pages_updated ON public.test_pages;
CREATE TRIGGER trg_test_pages_updated
  BEFORE UPDATE ON public.test_pages
  FOR EACH ROW EXECUTE FUNCTION public.test_touch_updated_at();

DROP TRIGGER IF EXISTS trg_test_figures_updated ON public.test_figures;
CREATE TRIGGER trg_test_figures_updated
  BEFORE UPDATE ON public.test_figures
  FOR EACH ROW EXECUTE FUNCTION public.test_touch_updated_at();

-- ---------------------------------------------------------------------------
-- RPCs
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.test_enqueue_job(p_job_id UUID)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  page_rec RECORD;
BEGIN
  UPDATE public.test_jobs
  SET status = 'queued', started_at = COALESCE(started_at, now()), updated_at = now()
  WHERE id = p_job_id
    AND status IN ('uploading', 'queued', 'failed', 'partial_success');

  IF NOT FOUND THEN
    RAISE EXCEPTION 'test job % nao encontrado ou status invalido', p_job_id;
  END IF;

  FOR page_rec IN
    SELECT id, page_number
    FROM public.test_pages
    WHERE job_id = p_job_id
      AND status IN ('pending', 'failed')
    ORDER BY page_number
  LOOP
    UPDATE public.test_pages
    SET status = 'queued', error_message = NULL
    WHERE id = page_rec.id;

    PERFORM pgmq.send(
      'test_run_queue',
      jsonb_build_object(
        'kind', 'classify_page',
        'job_id', p_job_id,
        'page_id', page_rec.id,
        'page_number', page_rec.page_number
      )
    );
  END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.test_enqueue_stage(p_payload JSONB)
RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  msg_id BIGINT;
BEGIN
  SELECT * INTO msg_id FROM pgmq.send('test_run_queue', p_payload);
  RETURN msg_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.test_read_queue(p_vt INTEGER DEFAULT 120, p_qty INTEGER DEFAULT 5)
RETURNS TABLE (
  msg_id BIGINT,
  read_ct INTEGER,
  enqueued_at TIMESTAMPTZ,
  vt TIMESTAMPTZ,
  message JSONB
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  RETURN QUERY
  SELECT r.msg_id, r.read_ct, r.enqueued_at, r.vt, r.message
  FROM pgmq.read('test_run_queue', p_vt, p_qty) AS r;
END;
$$;

CREATE OR REPLACE FUNCTION public.test_archive_message(p_msg_id BIGINT)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  RETURN pgmq.archive('test_run_queue', p_msg_id);
END;
$$;

CREATE OR REPLACE FUNCTION public.test_refresh_job_counters(p_job_id UUID)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  ok_pages INTEGER;
  fail_pages INTEGER;
  ok_figs INTEGER;
  fail_figs INTEGER;
  pending_pages INTEGER;
  pending_figs INTEGER;
  new_status TEXT;
BEGIN
  SELECT
    COUNT(*) FILTER (WHERE status = 'ok'),
    COUNT(*) FILTER (WHERE status = 'failed'),
    COUNT(*) FILTER (WHERE status IN ('pending', 'queued', 'running'))
  INTO ok_pages, fail_pages, pending_pages
  FROM public.test_pages
  WHERE job_id = p_job_id;

  SELECT
    COUNT(*) FILTER (WHERE status = 'ok'),
    COUNT(*) FILTER (WHERE status = 'failed'),
    COUNT(*) FILTER (WHERE status IN ('pending', 'queued', 'running'))
  INTO ok_figs, fail_figs, pending_figs
  FROM public.test_figures
  WHERE job_id = p_job_id;

  IF pending_pages > 0 OR pending_figs > 0 THEN
    new_status := 'running';
  ELSIF fail_pages > 0 OR fail_figs > 0 THEN
    IF ok_pages > 0 THEN
      new_status := 'partial_success';
    ELSE
      new_status := 'failed';
    END IF;
  ELSE
    new_status := 'done';
  END IF;

  UPDATE public.test_jobs
  SET
    processed_pages = ok_pages,
    failed_pages = fail_pages,
    processed_figures = ok_figs,
    failed_figures = fail_figs,
    status = CASE
      WHEN status = 'cancelled' THEN status
      ELSE new_status
    END,
    finished_at = CASE
      WHEN new_status IN ('done', 'failed', 'partial_success') THEN COALESCE(finished_at, now())
      ELSE finished_at
    END,
    updated_at = now()
  WHERE id = p_job_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.test_cleanup_stale(p_hours INTEGER DEFAULT 48)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  deleted_count INTEGER;
BEGIN
  WITH doomed AS (
    DELETE FROM public.test_jobs
    WHERE status IN ('uploading', 'failed', 'cancelled', 'done', 'partial_success')
      AND created_at < now() - make_interval(hours => p_hours)
    RETURNING id
  )
  SELECT COUNT(*) INTO deleted_count FROM doomed;
  RETURN deleted_count;
END;
$$;

REVOKE ALL ON FUNCTION public.test_enqueue_job(UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.test_enqueue_stage(JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.test_read_queue(INTEGER, INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.test_archive_message(BIGINT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.test_refresh_job_counters(UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.test_cleanup_stale(INTEGER) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.test_enqueue_job(UUID) TO service_role;
GRANT EXECUTE ON FUNCTION public.test_enqueue_stage(JSONB) TO service_role;
GRANT EXECUTE ON FUNCTION public.test_read_queue(INTEGER, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.test_archive_message(BIGINT) TO service_role;
GRANT EXECUTE ON FUNCTION public.test_refresh_job_counters(UUID) TO service_role;
GRANT EXECUTE ON FUNCTION public.test_cleanup_stale(INTEGER) TO service_role;

-- ---------------------------------------------------------------------------
-- pg_cron: despacha Edge Function a cada minuto (requer Vault com secrets)
-- ---------------------------------------------------------------------------
-- Após deploy, configure:
--   select vault.create_secret('https://<ref>.supabase.co', 'project_url');
--   select vault.create_secret('<service_role_or_secret_key>', 'test_run_invoke_key');
-- e descomente o cron abaixo (ou rode via dashboard).

-- SELECT cron.schedule(
--   'dispatch-test-run-queue',
--   '* * * * *',
--   $$
--   SELECT net.http_post(
--     url := (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'project_url')
--            || '/functions/v1/test-run-dispatch',
--     headers := jsonb_build_object(
--       'Content-Type', 'application/json',
--       'Authorization', 'Bearer ' || (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'test_run_invoke_key')
--     ),
--     body := '{}'::jsonb
--   );
--   $$
-- );

SELECT cron.schedule(
  'cleanup-test-jobs',
  '15 3 * * *',
  $$SELECT public.test_cleanup_stale(48);$$
);
