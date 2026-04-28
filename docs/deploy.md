# Deploy recomendado

## Frontend

- Vercel (Next.js ou similar), consumindo a API backend.

## Backend HTTP (FastAPI)

- Pode rodar em Vercel Serverless usando `api/index.py`.
- Bom para endpoints de ingestao/status/download URL.

## Worker (fila/jobs)

- Nao deve rodar em serverless.
- Deploy recomendado em processo de longa execucao (container/VM).
- Opcoes comuns: Railway, Fly.io, Render, ECS, VM dedicada.
