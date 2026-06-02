-- Supabase: tabelas em public expostas ao PostgREST devem ter RLS ativado.
-- Estas tabelas sao apenas para worker/pipeline (fila e artefatos); nao ha
-- politicas para anon/authenticated, logo a API publica nao le nem escreve linhas.
-- Conexao direta ao Postgres (papel dono das tabelas / superuser) nao e afetada.

ALTER TABLE public.artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.job_items ENABLE ROW LEVEL SECURITY;
