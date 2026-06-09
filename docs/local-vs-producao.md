# Local vs producao

## Local (seu PC)

| Processo | Comando |
|----------|---------|
| API | `python run_api.py` |
| Worker | `python run_worker.py` |
| Site | `npm run dev` |

- `PDF_STORAGE_STRATEGY=auto` — cache em `data/pdf_cache/` se Supabase recusar tamanho.
- Upload via `/api/process` (sem `NEXT_PUBLIC_FASTAPI_URL`).

## Producao

| Processo | Onde |
|----------|------|
| API | ECS Fargate + ALB |
| Worker | ECS Fargate |
| Site | Vercel |

- `PDF_STORAGE_STRATEGY=supabase` na API e no worker.
- Vercel: `FASTAPI_URL` + `NEXT_PUBLIC_FASTAPI_URL` + `ACCESS_PASSWORD`.
- Nao rode `run_api.py` / `run_worker.py` no PC para usuarios reais.

## Validar antes do go-live

```powershell
python scripts/check_supabase_prod.py
python scripts/smoke_e2e.py --api-url https://SUA-API
```
