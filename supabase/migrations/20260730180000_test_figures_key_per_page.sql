-- ---------------------------------------------------------------------------
-- test_figures.figure_key é sequencial POR PÁGINA (fig1, fig2...), conforme
-- prompts/base.txt e src/pipeline/test_run.py. A unicidade por job quebrava o
-- upsert do manifesto: um lote com N páginas manda "fig1" N vezes e o Postgres
-- responde "ON CONFLICT DO UPDATE command cannot affect row a second time".
-- ---------------------------------------------------------------------------

DO $$
DECLARE
  constraint_name TEXT;
BEGIN
  SELECT con.conname INTO constraint_name
  FROM pg_constraint con
  JOIN pg_class rel ON rel.oid = con.conrelid
  JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
  WHERE nsp.nspname = 'public'
    AND rel.relname = 'test_figures'
    AND con.contype = 'u'
    AND con.conkey = ARRAY[
      (SELECT attnum FROM pg_attribute WHERE attrelid = rel.oid AND attname = 'job_id'),
      (SELECT attnum FROM pg_attribute WHERE attrelid = rel.oid AND attname = 'figure_key')
    ]::smallint[];

  IF constraint_name IS NOT NULL THEN
    EXECUTE format('ALTER TABLE public.test_figures DROP CONSTRAINT %I', constraint_name);
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_test_figures_page_key
  ON public.test_figures (page_id, figure_key);

CREATE UNIQUE INDEX IF NOT EXISTS uq_test_figures_page_index
  ON public.test_figures (page_id, figure_index);
