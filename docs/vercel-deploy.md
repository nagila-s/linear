# Deploy na Vercel (site)

Guia completo: [`deploy-completo.md`](deploy-completo.md). AWS (API + worker): [`deploy/aws/README.md`](../deploy/aws/README.md).

## Variáveis (Production)

Copie de [`deploy/aws/vercel.env.example`](../deploy/aws/vercel.env.example):

| Variável | Obrigatória | Uso |
|----------|-------------|-----|
| `ACCESS_PASSWORD` | Sim | Login `/login` |
| `FASTAPI_URL` | Sim | BFF: status, download, ISBN |
| `NEXT_PUBLIC_FASTAPI_URL` | Sim (prod) | Upload PDF direto na API (evita limite ~4,5 MB da Vercel) |
| `NEXT_PUBLIC_API_PREFIX` | Não | Padrão `/api/v1` |

`NEXT_PUBLIC_FASTAPI_URL` e `FASTAPI_URL` são a **mesma URL** do ALB da API na AWS.

## Deploy

1. [vercel.com/new](https://vercel.com/new) → repositório → preset Next.js.
2. Cole as variáveis acima.
3. `npm run build` deve passar no CI da Vercel.
4. Após o deploy, configure `CORS_ORIGINS` na API AWS com a URL `.vercel.app`.

## Dev local

Sem `FASTAPI_URL` / `NEXT_PUBLIC_*`: upload usa `/api/process` → `http://127.0.0.1:8000`. Rode `python run_api.py` e `python run_worker.py`.

## Problemas

| Sintoma | Causa |
|---------|--------|
| CORS no upload | `CORS_ORIGINS` na API sem URL da Vercel |
| Upload pequeno OK, grande falha | Falta `NEXT_PUBLIC_FASTAPI_URL` |
| Jobs `queued` | Worker ECS parado |
