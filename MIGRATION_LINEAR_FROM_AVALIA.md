# Migration Linear from Avalia

## Objetivo
Migrar o `linear-teste` para um backend de producao com worker v2 (fila Postgres + heartbeat + retry), preservando os endpoints atuais do Linear.

## Mapa de arquivos copiados/adaptados

### Copiados/adaptados do Avalia
- `src/worker/v2_main.py`
- `src/worker/queueing/postgres_queue.py`
- `src/worker/pipeline/v2_orchestrator.py`
- `src/worker/pipeline/stages/extract_images.py`
- `src/worker/pipeline/stages/describe.py`
- `src/worker/services/dorina_client.py`
- `src/worker/utils/retry.py`
- `src/worker/utils/logger.py`

### Adaptacoes no Linear
- `src/core/config.py`: flags/versionamento (`openai_combined_mode`, prompt versions, strategy).
- `src/models/enums.py` e `src/models/schemas.py`: status extras e campos de versionamento/modelo.
- `src/repositories/jobs.py`: `create()` persiste prompt/model/pipeline/metadata; claim via RPC.
- `src/repositories/artifacts.py`: persistencia real de `final_json` em `artifacts`.
- `src/services/openai_client.py`: modo `combined` com fallback para chamadas separadas.
- `src/services/dorina_client.py`: classificacao de erro transitivo/permanente.
- `src/services/storage.py`: paths com `process_version`.
- `src/api/main.py`: endpoint `POST /api/v1/jobs/upload-multi` e `result-url` versionado.
- `src/worker/runner.py`: preferencia por worker v2.

## SQL aplicado (ordem)
1. `supabase/migrations/20260428090000_foundation_processing_queue.sql`
2. `supabase/migrations/20260428091000_fix_retry_and_worker_rpc.sql`
3. `supabase/migrations/20260428092000_artifacts_and_versioning.sql`

## Buckets e convencao de paths
Buckets esperados:
- `pdf`
- `pages`
- `figures`
- `json`

Padrao:
- `pdf/{isbn}/{process_version}/original.pdf`
- `pages/{isbn}/{process_version}/p0001.png`
- `figures/{isbn}/{process_version}/p0001/fig0001.png`
- `json/{isbn}/{process_version}/{job_id}/final.json`

## Novas variaveis de ambiente
- `OPENAI_COMBINED_MODE=true|false`
- `LINEAR_PROMPT_VERSION=v1`
- `CONTEXT_PROMPT_VERSION=v1`
- `DORINA_PROMPT_VERSION=v1`
- `PROCESS_VERSION_STRATEGY=lin-{linear_prompt_version}_ctx-{context_prompt_version}_dor-{dorina_prompt_version}`

## Runbook de rollback
1. Desabilitar worker v2 (parar processo que executa `src/worker/v2_main.py`).
2. Voltar para o runner legado (`src/worker/runner.py`) sem `SUPABASE_DB_DSN`.
3. Reverter app para `OPENAI_COMBINED_MODE=false`.
4. Se necessario, reverter migrations em ordem inversa (remover RPCs/indices/colunas adicionadas para v2).
5. Reprocessar jobs `retrying`/`running` para limpar estado inconsistente.

## Itens fora de escopo desta rodada
- Port de codigo legado/depreciado do Avalia (`supabase/functions/process-book-jobs`, `api/process-jobs.js`, `generate-description`).
