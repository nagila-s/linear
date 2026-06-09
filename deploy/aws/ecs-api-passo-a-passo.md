# ECS Fargate + ALB — API (`linear-api`) passo a passo

Região: **us-east-2** (Ohio), mesmo cluster do worker.

| Item | Valor |
|------|--------|
| Account ID | `089200327380` |
| Cluster | `linear` |
| Imagem | `089200327380.dkr.ecr.us-east-2.amazonaws.com/linear-api:latest` |
| Porta do container | `8000` |
| Health check | `GET /health` |

---

## Parte A — Pré-requisitos

### A.1 Worker rodando

Confirme antes de subir a API:

```powershell
aws ecs describe-services --cluster linear --services linear-worker --region us-east-2 --query "services[0].{status:status,running:runningCount}"
```

Esperado: `ACTIVE`, `running: 1`.

### A.2 Imagem no ECR (us-east-2)

```powershell
cd c:\Users\nmesquita\Documents\linear-teste
.\deploy\aws\push-images.ps1 -Region us-east-2
```

Confirme `OK: .../linear-api:latest`.

### A.3 Log group

```powershell
aws logs create-log-group --log-group-name /ecs/linear-api --region us-east-2
```

(Se já existir, ignore o erro.)

### A.4 CORS no SSM

A API lê `CORS_ORIGINS` do SSM. Atualize com a URL da Vercel (ou `*` só para teste):

No `.env`:

```env
CORS_ORIGINS=https://seu-app.vercel.app
```

Depois:

```powershell
.\deploy\aws\setup-ssm-from-env.ps1 -Region us-east-2
```

Ou edite manualmente em **Systems Manager** → **Parameter Store** → `/linear/CORS_ORIGINS`.

### A.5 IAM

A role **`ecsTaskExecutionRole`** já deve ter policy `linear-ssm-read` em **us-east-2** (mesma do worker). A API usa os mesmos secrets.

---

## Parte B — Security groups (VPC)

Crie **dois** security groups na **mesma VPC** do cluster.

### B.1 `linear-alb-sg` (frente do load balancer)

1. **VPC** → **Security groups** → **Create**
2. Nome: `linear-alb-sg`
3. **Inbound:**

| Tipo | Porta | Origem |
|------|-------|--------|
| HTTP | 80 | `0.0.0.0/0` |
| HTTPS | 443 | `0.0.0.0/0` |

4. **Outbound:** All traffic → `0.0.0.0/0`
5. **Create**

### B.2 `linear-api-sg` (tasks da API)

1. **Create security group**
2. Nome: `linear-api-sg`
3. **Inbound:**

| Tipo | Porta | Origem |
|------|-------|--------|
| Custom TCP | **8000** | **Security group** → selecione `linear-alb-sg` |

(Não use `0.0.0.0/0` na porta 8000 — só o ALB fala com a API.)

4. **Outbound:** All traffic → `0.0.0.0/0`
5. **Create**

---

## Parte C — Application Load Balancer

1. Busque **EC2** → menu **Load Balancers** → **Create load balancer**
2. Tipo: **Application Load Balancer**
3. **Basic configuration:**
   - Name: `linear-api-alb`
   - Scheme: **Internet-facing**
   - IP address type: IPv4
4. **Network mapping:**
   - VPC: mesma do cluster `linear`
   - Subnets: marque **pelo menos 2** subnets **públicas** (mesmas que usa no ECS)
5. **Security groups:** marque **`linear-alb-sg`** (desmarque default se vier marcado)
6. **Listeners:**

### Opção 1 — HTTP primeiro (teste rápido)

| Listener | Ação |
|----------|------|
| HTTP :80 | Forward to target group (criar abaixo) |

Use a URL `http://linear-api-alb-xxxxx.us-east-2.elb.amazonaws.com` em `FASTAPI_URL` na Vercel (BFF).  
Upload direto no browser (`NEXT_PUBLIC_FASTAPI_URL`) exige **HTTPS** — veja Opção 2.

### Opção 2 — HTTPS (recomendado para produção)

1. **Certificate Manager (ACM)** → região **us-east-2** → peça certificado para seu domínio (ex. `api.seudominio.org`)
2. Valide por DNS (Route 53 ou CNAME no registrador)
3. No ALB, listener **HTTPS :443** → certificado ACM → forward ao target group
4. (Opcional) Listener HTTP :80 → redirect para HTTPS

7. **Target group** (criar na mesma tela ou antes):

| Campo | Valor |
|--------|--------|
| Target type | **IP addresses** (Fargate usa awsvpc) |
| Name | `linear-api-tg` |
| Protocol | HTTP |
| Port | **8000** |
| VPC | mesma do cluster |
| Health check protocol | HTTP |
| Health check path | **`/health`** |
| Healthy threshold | 2 |
| Interval | 30 s |
| Timeout | 5 s |

8. **Create load balancer**

9. Anote o **DNS name** do ALB (ex. `linear-api-alb-1234567890.us-east-2.elb.amazonaws.com`)

### Ajuste importante no ALB

Depois de criado: **Load balancer** → **Attributes** → **Idle timeout** → **300** segundos (upload de PDF).

---

## Parte D — Task definition `linear-api`

1. **ECS** → **us-east-2** → **Task definitions** → **Create new task definition**
2. Family: `linear-api`
3. Launch: **Fargate**, Linux X86_64
4. CPU **512**, Memory **1024**
5. **Task execution role:** `ecsTaskExecutionRole`
6. **Task role:** `ecsTaskExecutionRole` (simples)

### Container `linear-api`

| Campo | Valor |
|--------|--------|
| Name | `linear-api` |
| Image | `089200327380.dkr.ecr.us-east-2.amazonaws.com/linear-api:latest` |
| Port mapping | **8000** TCP (container + app) |

### Environment (tipo Valor)

| Key | Value |
|-----|--------|
| `APP_ENV` | `production` |
| `APP_PORT` | `8000` |
| `API_PREFIX` | `/api/v1` |
| `PDF_STORAGE_STRATEGY` | `supabase` |
| `BUCKET_PDF` | `pdf` |
| `BUCKET_PAGES` | `pages` |
| `BUCKET_FIGURES` | `figures` |
| `BUCKET_JSON` | `json` |

### Secrets (ValueFrom — SSM us-east-2)

| Key | ARN |
|-----|-----|
| `SUPABASE_URL` | `arn:aws:ssm:us-east-2:089200327380:parameter/linear/SUPABASE_URL` |
| `SUPABASE_SERVICE_ROLE_KEY` | `arn:aws:ssm:us-east-2:089200327380:parameter/linear/SUPABASE_SERVICE_ROLE_KEY` |
| `SUPABASE_DB_DSN` | `arn:aws:ssm:us-east-2:089200327380:parameter/linear/SUPABASE_DB_DSN` |
| `OPENAI_API_KEY` | `arn:aws:ssm:us-east-2:089200327380:parameter/linear/OPENAI_API_KEY` |
| `CORS_ORIGINS` | `arn:aws:ssm:us-east-2:089200327380:parameter/linear/CORS_ORIGINS` |

### Coleção de logs

| Chave | Valor |
|--------|--------|
| `awslogs-group` | `/ecs/linear-api` |
| `awslogs-region` | `us-east-2` |
| `awslogs-stream-prefix` | `api` |
| `awslogs-create-group` | `true` |

7. **Create**

---

## Parte E — Serviço ECS com load balancer

1. **ECS** → cluster **`linear`** → **Create service**
2. **Task definition:** `linear-api` (última revisão)
3. **Service name:** `linear-api`
4. **Desired tasks:** `1`
5. **Deployment:** Rolling update (padrão)

### Networking

| Campo | Valor |
|--------|--------|
| VPC / Subnets | Mesmas do worker (2+ subnets) |
| **IP público** | **Ativado** |
| Security group | **`linear-api-sg`** (não o do ALB) |

### Load balancing

| Campo | Valor |
|--------|--------|
| Load balancer type | Application Load Balancer |
| Load balancer | **Existing** → `linear-api-alb` |
| Listener | 80 (ou 443 se HTTPS) |
| Target group | **`linear-api-tg`** |
| Container | `linear-api:8000` |

6. **Create service**

Aguarde **Running** e target group **healthy**.

---

## Parte F — Testar

### Health

```powershell
curl http://SEU-ALB-DNS/health
```

Ou no navegador: `http://linear-api-alb-xxxxx.us-east-2.elb.amazonaws.com/health`

Resposta esperada: JSON OK da API.

### Smoke (opcional)

```powershell
python scripts/smoke_e2e.py --api-url http://SEU-ALB-DNS
```

Com PDF pequeno:

```powershell
python scripts/smoke_e2e.py --api-url http://SEU-ALB-DNS --pdf caminho\teste.pdf
```

Confira logs do **worker** processando o job.

---

## Parte G — Vercel

Arquivo [`vercel.env.example`](vercel.env.example):

| Variável | Valor |
|----------|--------|
| `ACCESS_PASSWORD` | senha do login |
| `FASTAPI_URL` | `http://SEU-ALB-DNS` (sem `/` no final) |
| `NEXT_PUBLIC_FASTAPI_URL` | mesma URL **com HTTPS** quando tiver certificado |
| `NEXT_PUBLIC_API_PREFIX` | `/api/v1` |

Atualize `CORS_ORIGINS` no SSM com a URL real `.vercel.app` e force novo deploy da API (nova task).

---

## Problemas frequentes

| Sintoma | Causa |
|---------|--------|
| Target **unhealthy** | SG: ALB não alcança API na 8000; ou `/health` falha |
| 502 Bad Gateway | Task parada; veja logs `/ecs/linear-api` |
| CORS no upload | `CORS_ORIGINS` sem URL da Vercel |
| Circuit breaker | Secrets `us-west-2` na task (use **east**); imagem errada |
| Upload lento / timeout | Idle timeout do ALB (aumente para 300s) |

---

## Ordem resumida

```
Imagem ECR → SG alb + api → ALB + target group → Task definition linear-api → Service com LB → /health → Vercel
```

Worker já deve estar **ACTIVE** antes do primeiro upload de teste.
