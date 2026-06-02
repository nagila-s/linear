-- Corrige atribuicao a jobs.status (enum job_status): CASE sem cast vira text e quebra no UPDATE.

CREATE OR REPLACE FUNCTION public.worker_claim_next_job(p_worker_id text)
RETURNS TABLE (
  id UUID,
  book_id UUID,
  status TEXT,
  pipeline_mode TEXT,
  attempts INTEGER,
  max_attempts INTEGER
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  WITH candidate AS (
    SELECT j.id
    FROM public.jobs j
    WHERE j.status IN ('queued'::public.job_status, 'retrying'::public.job_status)
      AND COALESCE(j.run_after, now()) <= now()
      AND j.attempts < j.max_attempts
    ORDER BY j.created_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT 1
  )
  UPDATE public.jobs j
  SET
    status = 'running'::public.job_status,
    attempts = j.attempts + 1,
    worker_id = p_worker_id,
    heartbeat_at = now(),
    started_at = now(),
    updated_at = now()
  FROM candidate
  WHERE j.id = candidate.id
  RETURNING j.id, j.book_id, j.status::text, COALESCE(j.pipeline_mode, j.job_type::text), j.attempts, j.max_attempts;
END;
$$;

CREATE OR REPLACE FUNCTION public.worker_touch_heartbeat(p_job_id uuid, p_processed int, p_failed int)
RETURNS VOID
LANGUAGE sql
AS $$
  UPDATE public.jobs
  SET
    heartbeat_at = now(),
    processed_items = COALESCE(p_processed, processed_items),
    failed_items = COALESCE(p_failed, failed_items),
    updated_at = now()
  WHERE id = p_job_id AND status = 'running'::public.job_status;
$$;

CREATE OR REPLACE FUNCTION public.worker_complete_job(p_job_id uuid, p_processed int)
RETURNS VOID
LANGUAGE sql
AS $$
  UPDATE public.jobs
  SET
    status = 'done'::public.job_status,
    processed_items = COALESCE(p_processed, processed_items),
    finished_at = now(),
    updated_at = now()
  WHERE id = p_job_id AND status = 'running'::public.job_status;
$$;

CREATE OR REPLACE FUNCTION public.worker_fail_job(p_job_id uuid, p_error text)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
  v_attempts integer;
  v_max integer;
BEGIN
  SELECT attempts, max_attempts INTO v_attempts, v_max FROM public.jobs WHERE id = p_job_id;
  UPDATE public.jobs
  SET
    status = (
      CASE
        WHEN v_attempts < v_max THEN 'retrying'::public.job_status
        ELSE 'failed'::public.job_status
      END
    ),
    run_after = CASE WHEN v_attempts < v_max THEN now() + interval '2 minutes' ELSE now() END,
    erro = left(COALESCE(p_error, 'erro desconhecido'), 1500),
    finished_at = CASE WHEN v_attempts < v_max THEN NULL ELSE now() END,
    updated_at = now()
  WHERE id = p_job_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.worker_requeue_stale_jobs()
RETURNS INTEGER
LANGUAGE sql
AS $$
  WITH stale AS (
    SELECT id
    FROM public.jobs
    WHERE status = 'running'::public.job_status
      AND COALESCE(heartbeat_at, updated_at) < now() - interval '20 minutes'
  ),
  upd AS (
    UPDATE public.jobs j
    SET
      status = 'retrying'::public.job_status,
      run_after = now() + interval '1 minute',
      updated_at = now()
    FROM stale
    WHERE j.id = stale.id
    RETURNING j.id
  )
  SELECT COUNT(*)::int FROM upd;
$$;
