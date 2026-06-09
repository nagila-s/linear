# Deploy recomendado

## Visao geral

[`docs/deploy-completo.md`](deploy-completo.md) — Vercel (site) + AWS ECS (API + worker) + Supabase.

## Passos

1. `python scripts/check_supabase_prod.py`
2. [`deploy/aws/README.md`](../deploy/aws/README.md) — worker ECS, depois API ECS + ALB
3. [`docs/vercel-deploy.md`](vercel-deploy.md) — variaveis Vercel
4. `python scripts/smoke_e2e.py --api-url https://...`

## Artefatos

| Servico | Dockerfile |
|---------|------------|
| API | `Dockerfile.api` |
| Worker | `Dockerfile.worker` |
| Site | Vercel (Next.js) |
