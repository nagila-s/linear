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
```

## Executar localmente

1. Instale dependencias:
   `pip install -r requirements.txt`
2. Suba a API:
   `python run_api.py`
3. Suba o worker (em outro terminal):
   `python run_worker.py`

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

- Vercel funciona bem para a camada HTTP (FastAPI serverless).
- O worker e de longa execucao; normalmente deve rodar fora da Vercel (ex.: VM, container, Fly, Railway, ECS).
- O front pode ficar na Vercel consumindo a API.

## Documentacao adicional

- `docs/schema_assumptions.md`
- `docs/deploy.md`
- `docs/local_test_runbook.md`
