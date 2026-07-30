# Área de testes serverless (Supabase)

A área `/testes` **não usa** o worker AWS nem a FastAPI. Fluxo:

1. Navegador renderiza páginas e recorta figuras (`pdfjs-dist`).
2. BFF Next cria `test_jobs` + manifesto e sobe PNGs no bucket `test-runs`.
3. RPC `test_enqueue_job` coloca etapas em PGMQ `test_run_queue`.
4. Edge Function `test-run-dispatch` processa uma etapa por vez (classificar → linearizar → Dorina → finalize).
5. UI faz poll em `/api/test-jobs/:id/status` e baixa `final.json` (com `prompt_hash`).

## Pré-requisitos

1. Aplicar migration `supabase/migrations/20260730120000_test_jobs_serverless.sql`.
2. Deploy da function:
   ```bash
   supabase functions deploy test-run-dispatch
   ```
3. Secrets da function: `OPENAI_API_KEY`, `DORINA_API_URL`, `DORINA_API_KEY`, modelos OpenAI.
4. Vercel: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `ACCESS_PASSWORD`, `SESSION_SECRET`.
5. (Opcional) Vault + cron para `/functions/v1/test-run-dispatch` a cada minuto — o enqueue já dispara um POST best-effort.

## Isolamento

- Tabelas `test_jobs` / `test_pages` / `test_figures` — **nunca** `public.jobs`.
- Snapshot imutável em `prompt_snapshot`; sem fallback para `prompts/` do worker.
- JSON fora do contrato `{ tipo_pagina, pagina, conteudo }` falha após retry corretivo.
