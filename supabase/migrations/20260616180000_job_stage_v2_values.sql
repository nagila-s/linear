-- Estende job_stage para etapas usadas pelo worker v2 (idempotente).

DO $$
BEGIN
  ALTER TYPE public.job_stage ADD VALUE 'pages';
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  ALTER TYPE public.job_stage ADD VALUE 'extract';
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  ALTER TYPE public.job_stage ADD VALUE 'describe';
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;
