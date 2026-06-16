# Deploy AWS (API + worker) + Vercel

Worker e API rodam em **dois serviços ECS Fargate**. O site fica na **Vercel**. Supabase é a fila e o storage.

## 0) Checklist Supabase

```powershell
pip install -r requirements.txt
python scripts/check_supabase_prod.py
```

Aplique as migrations em `supabase/migrations/` na ordem dos nomes, se alguma RPC/tabela faltar.

## 1) Secrets no SSM Parameter Store

Copie `setup-ssm-from-env.ps1.example` → `setup-ssm-from-env.ps1` (não commite o `.ps1` com dados) ou crie manualmente em `/linear/`:

- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_DB_DSN`
- `OPENAI_API_KEY`
- `CORS_ORIGINS` (URL da Vercel, ex. `https://linear-teste.vercel.app`)
- `DORINA_API_URL`, `DORINA_API_KEY` (worker)

Referência de variáveis: [`env.api.example`](env.api.example), [`env.worker.example`](env.worker.example).

## 2) Build e push (ECR)

```powershell
.\deploy\aws\push-images.ps1 -Region us-east-2
```

## 3) CloudWatch log groups

```bash
aws logs create-log-group --log-group-name /ecs/linear-api --region us-east-2
aws logs create-log-group --log-group-name /ecs/linear-worker --region us-east-2
```

## 4) Worker ECS (primeiro)

**Guia detalhado (console AWS, campo a campo):** [`ecs-worker-passo-a-passo.md`](ecs-worker-passo-a-passo.md)

Resumo: log group + IAM → cluster `linear` → task `linear-worker` → serviço Fargate sem ALB → validar CloudWatch.

## 5) API ECS + ALB

**Guia detalhado:** [`ecs-api-passo-a-passo.md`](ecs-api-passo-a-passo.md)

Resumo: SG `linear-alb-sg` + `linear-api-sg` → ALB → task `linear-api` → serviço com target group porta 8000 → `/health` → Vercel.

## 6) Vercel

Variáveis ([`vercel.env.example`](vercel.env.example)):

| Variável | Uso |
|----------|-----|
| `ACCESS_PASSWORD` | Login |
| `FASTAPI_URL` | BFF (status, download) |
| `NEXT_PUBLIC_FASTAPI_URL` | Upload direto no browser (PDFs grandes) |
| `NEXT_PUBLIC_API_PREFIX` | `/api/v1` |

Depois do deploy, atualize `CORS_ORIGINS` na API com a URL real da Vercel.

## 7) Smoke test

```powershell
python scripts/smoke_e2e.py --api-url https://SUA-URL
```

Com PDF de teste:

```powershell
python scripts/smoke_e2e.py --api-url https://SUA-URL --pdf caminho\teste.pdf
```

## Ordem resumida

```
Supabase OK → Worker ECS → API ECS+ALB → Vercel → smoke E2E
```

## Troubleshooting

| Sintoma | Ação |
|---------|------|
| Job `queued` forever | Logs `/ecs/linear-worker`; `SUPABASE_DB_DSN` |
| CORS no upload | `CORS_ORIGINS` = origem exata da Vercel |
| 413 upload | Limite Supabase Storage |
| 502 ALB | Health `/health`; task saudável |
| PDF não processa | `PDF_STORAGE_STRATEGY=supabase` em API **e** worker |

## CI (opcional)

Workflow [`.github/workflows/ecr-push.yml`](../../.github/workflows/ecr-push.yml) — push automático no ECR ao tag `v*`.
