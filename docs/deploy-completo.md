# Deploy completo (Vercel + AWS)

## Arquitetura

```
Usuario → Vercel (Next.js)
            ├─ upload PDF → API AWS (NEXT_PUBLIC_FASTAPI_URL)  [PDFs grandes]
            └─ status/download → BFF /api/* → API AWS (FASTAPI_URL)

API AWS (ECS) → Supabase (job + PDF)
Worker AWS (ECS) → fila Postgres + pipeline
```

| Peça | Onde | Imagem / comando |
|------|------|------------------|
| Site | Vercel | `npm run build` |
| API | ECS Fargate + ALB | [`Dockerfile.api`](../Dockerfile.api) |
| Worker | ECS Fargate | [`Dockerfile.worker`](../Dockerfile.worker) |
| Dados | Supabase | migrations em [`supabase/migrations/`](../supabase/migrations/) |

## Ordem de deploy

1. **Supabase** — `python scripts/check_supabase_prod.py`
2. **Worker ECS** — subir antes da API ([`deploy/aws/README.md`](../deploy/aws/README.md))
3. **API ECS + ALB** — `GET /health` público
4. **Vercel** — [`deploy/aws/vercel.env.example`](../deploy/aws/vercel.env.example)
5. **Teste** — `python scripts/smoke_e2e.py --api-url https://...`

## Produção vs local

| | Local (dev) | Produção |
|---|-------------|----------|
| Site | `npm run dev` | Vercel |
| API | `python run_api.py` | ECS |
| Worker | `python run_worker.py` | ECS |
| PDF storage | `auto` (cache local OK) | `supabase` na API e worker |
| Upload | BFF `/api/process` | `NEXT_PUBLIC_FASTAPI_URL` na Vercel |

Não use o PC para processar jobs reais após o go-live.

## Documentação

- AWS passo a passo: [`deploy/aws/README.md`](../deploy/aws/README.md)
- Só Vercel: [`vercel-deploy.md`](vercel-deploy.md)
- Supabase: `python scripts/check_supabase_prod.py`
- Local vs producao: [`local-vs-producao.md`](local-vs-producao.md)
