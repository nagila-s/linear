# Linear Pipeline Backend

Backend de orquestracao para transformar PDF em artefatos acessiveis:

- pre-processamento de paginas e figuras
- linearizacao opcional via OpenAI
- contextualizacao por figura
- descricao de imagens via Dorina IA
- persistencia total no Supabase (banco + storage)
- exportacao para PB/Avalia

## Status atual

- Streamlit nao faz mais parte do fluxo principal.
- API de ingestao implementada com FastAPI.
- Worker de pipeline implementado com fila em tabela `jobs`.
- Estrutura pronta para front na Vercel consumir os endpoints.

## Estrutura

- `src/api/`: endpoints HTTP
- `src/worker/`: loop de processamento de jobs
- `src/pipeline/`: orquestracao e etapas
- `src/services/`: integracoes externas (OpenAI, Dorina, Supabase, export)
- `src/repositories/`: persistencia em banco relacional
- `api/index.py`: entrada para ambiente Vercel

## Variaveis de ambiente

Crie `.env` com:

```bash
APP_ENV=dev
APP_HOST=0.0.0.0
APP_PORT=8000
API_PREFIX=/api/v1
CORS_ORIGINS=*

SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_DB_DSN=
BUCKET_PDF=pdf
BUCKET_PAGES=pages
BUCKET_FIGURES=figures
BUCKET_JSON=json

OPENAI_API_KEY=
OPENAI_MODEL_LINEARIZATION=gpt-5.2-pro
OPENAI_MODEL_CONTEXT=gpt-5.2-pro
LINEARIZATION_PROMPT_FILE=prompt.txt

DORINA_API_URL=
DORINA_API_KEY=
DORINA_API_KEY_HEADER=Authorization
DORINA_DOCUMENT_TYPE=string
DORINA_BRAILLE=false
DORINA_SIGNED_URL_EXPIRES_SECONDS=3600
DORINA_TIMEOUT_SECONDS=60

PB_API_URL=
PB_API_KEY=
AVALIA_API_URL=
AVALIA_API_KEY=

WORKER_POLL_SECONDS=5
WORKER_MAX_ATTEMPTS=3

PDF_STORAGE_STRATEGY=auto
PDF_LOCAL_CACHE_DIR=data/pdf_cache
PDF_MAX_SIZE_MB=1024
```

### PDFs grandes (100 MB+)

O limite de **77 MB** que apareceu no upload nao vem da aplicacao: e o **Supabase Storage** (plano **Free** = teto global de **50 MB** por arquivo).

Com `PDF_STORAGE_STRATEGY=auto` (padrao), se o Supabase recusar o upload, o PDF fica em `data/pdf_cache/` e o worker le de la — desde que API e worker rodem na **mesma maquina** (ou volume compartilhado).

Para guardar o original na nuvem:

1. Plano **Pro** (ou superior) no Supabase.
2. Dashboard → **Storage** → **Settings** → aumentar **Global file size limit** (ex.: 500 MB ou mais).
3. Rodar a migration `20260601180000_storage_pdf_bucket_size.sql` (limite do bucket `pdf` = 500 MB).

## Executar localmente (desenvolvimento)

1. Instale dependencias:
   `pip install -r requirements.txt`
2. Suba a API:
   `python run_api.py`
3. Suba o worker (em outro terminal):
   `python run_worker.py`
4. Interface:
   `npm install && npm run dev`

Producao: nao use o PC para API/worker — veja `docs/deploy-completo.md`.

## Endpoints principais

- `GET /health`
- `POST /api/v1/jobs/upload` (multipart):
  - `isbn`
  - `job_type`: `linearizar` ou `contextualizar`
  - `prompt_version`
  - `pdf_file`
- `GET /api/v1/jobs/{job_id}`
- `POST /api/v1/jobs/{job_id}/retry`
- `GET /api/v1/jobs/{job_id}/result-url`

## Observacoes de deploy

- **Tudo online:** `docs/deploy-completo.md` — `deploy/aws/README.md` (API + worker ECS) + Vercel.
- O worker processa o PDF; a API so recebe o upload e enfileira o job.

## Documentacao adicional

- `docs/deploy-completo.md`
- `docs/vercel-deploy.md`
- `docs/schema_assumptions.md`
- `docs/deploy.md`
- `docs/local_test_runbook.md`
