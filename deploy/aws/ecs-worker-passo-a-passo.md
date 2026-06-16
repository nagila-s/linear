# ECS Fargate — worker (`linear-worker`) passo a passo

Use a região **us-east-2** (Ohio), a mesma do ECR e do SSM.

Valores já prontos no seu ambiente:

| Item | Valor |
|------|--------|
| Account ID | `089200327380` |
| Imagem ECR | `089200327380.dkr.ecr.us-east-2.amazonaws.com/linear-worker:latest` |
| Parâmetros SSM | `/linear/SUPABASE_URL`, etc. |

---

## Parte A — Pré-requisitos (uma vez)

### A.1 Log group no CloudWatch

1. Console AWS → canto superior direito: região **US East (Ohio) / us-east-2**.
2. Busque **CloudWatch** → menu **Logs** → **Log groups**.
3. **Create log group**.
4. Nome exato: `/ecs/linear-worker`
5. Retention: opcional (ex. 30 dias) ou **Never expire**.
6. **Create**.

Repita depois para a API: `/ecs/linear-api`.

Ou no PowerShell:

```powershell
aws logs create-log-group --log-group-name /ecs/linear-worker --region us-east-2
```

### A.2 Papel IAM `ecsTaskExecutionRole` (puxar imagem + logs + secrets SSM)

O ECS precisa de um **task execution role** para:

- Baixar imagem do ECR
- Enviar logs ao CloudWatch
- Ler parâmetros SSM e injetar no container

**Verificar se já existe:**

1. **IAM** → **Roles** → busque `ecsTaskExecutionRole`.
2. Se existir → abra e confira políticas anexadas:
   - `AmazonECSTaskExecutionRolePolicy` (geralmente já vem)
   - Para SSM: precisa permissão de leitura em `arn:aws:ssm:us-east-2:089200327380:parameter/linear/*`

**Se NÃO existir — criar:**

1. IAM → **Roles** → **Create role**.
2. Trusted entity: **AWS service** → use case **Elastic Container Service** → **Elastic Container Service Task**.
3. **Next**.
4. Adicione política: **AmazonECSTaskExecutionRolePolicy**.
5. **Next** → Role name: `ecsTaskExecutionRole` → **Create role**.

**Permissão SSM (importante):**

1. Abra a role `ecsTaskExecutionRole` → **Add permissions** → **Create inline policy** → JSON:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["ssm:GetParameters", "ssm:GetParameter"],
      "Resource": "arn:aws:ssm:us-east-2:089200327380:parameter/linear/*"
    },
    {
      "Effect": "Allow",
      "Action": ["kms:Decrypt"],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": "ssm.us-east-2.amazonaws.com"
        }
      }
    }
  ]
}
```

2. Nome da policy: `linear-ssm-read` → **Create policy**.

### A.3 Papel IAM da task (opcional no início)

No exemplo JSON usamos `linearWorkerTaskRole`. Para o worker **só falar com Supabase/OpenAI pela internet**, você pode **reutilizar a mesma** `ecsTaskExecutionRole` como **Task role** no passo da task definition (mais simples).

Se preferir role separada: crie `linearWorkerTaskRole` com trusted entity ECS Task, sem políticas extras (só execução via env injetado).

---

## Parte B — Cluster ECS

1. Busque **Elastic Container Service (ECS)**.
2. Menu esquerdo **Clusters** → **Create cluster**.
3. **Cluster name:** `linear` (ou `linear-prod`).
4. **Infrastructure:** AWS Fargate (serverless) — marcado.
5. Deixe o resto padrão → **Create**.
6. Aguarde status **Active**.

---

## Parte C — Task definition do worker

### Opção 1 — Console (recomendado na primeira vez)

1. ECS → menu **Task definitions** → **Create new task definition** → botão **Create new task definition** (novo formulário).
2. **Task definition family:** `linear-worker`
3. **Launch type:** AWS Fargate
4. **Operating system/Architecture:** Linux / X86_64
5. **Task size:**
   - CPU: **1 vCPU** (1024)
   - Memory: **2 GB** (2048)
6. **Task roles:**
   - **Task execution role:** `ecsTaskExecutionRole`
   - **Task role:** `ecsTaskExecutionRole` (ou `linearWorkerTaskRole` se criou)
7. **Network mode:** awsvpc (padrão Fargate)

### Container

8. Em **Container - 1** → **Add container** (ou preencha o container padrão):

| Campo | Valor |
|-------|--------|
| **Name** | `linear-worker` |
| **Image URI** | `089200327380.dkr.ecr.us-east-2.amazonaws.com/linear-worker:latest` |
| **Essential container** | Sim |

9. **Port mappings:** nenhuma (worker não expõe HTTP). Remova mapeamento 80 se existir.

10. **Environment variables** (tipo *Value*, não secret):

| Key | Value |
|-----|--------|
| `APP_ENV` | `production` |
| `PDF_STORAGE_STRATEGY` | `supabase` |
| `WORKER_POLL_SECONDS` | `5` |
| `WORKER_MAX_ATTEMPTS` | `3` |
| `BUCKET_PDF` | `pdf` |
| `BUCKET_PAGES` | `pages` |
| `BUCKET_FIGURES` | `figures` |
| `BUCKET_JSON` | `json` |
| `LINEAR_PIPELINE_ONLY` | `true` |
| `LINEARIZATION_PROMPT_FILE` | `prompt.txt` |
| `PDF_RENDER_DPI` | `150` |
| `LINEARIZE_PAGE_CONCURRENCY` | `4` |

11. **Environment variables — secrets** (tipo *ValueFrom* → SSM):

Para cada linha, **Add environment variable** → marque **Value type: ValueFrom** → **ValueFrom**:

| Key | ValueFrom (ARN do parâmetro SSM) |
|-----|----------------------------------|
| `SUPABASE_URL` | `arn:aws:ssm:us-east-2:089200327380:parameter/linear/SUPABASE_URL` |
| `SUPABASE_SERVICE_ROLE_KEY` | `arn:aws:ssm:us-east-2:089200327380:parameter/linear/SUPABASE_SERVICE_ROLE_KEY` |
| `SUPABASE_DB_DSN` | `arn:aws:ssm:us-east-2:089200327380:parameter/linear/SUPABASE_DB_DSN` |
| `OPENAI_API_KEY` | `arn:aws:ssm:us-east-2:089200327380:parameter/linear/OPENAI_API_KEY` |
| `DORINA_API_URL` | `arn:aws:ssm:us-east-2:089200327380:parameter/linear/DORINA_API_URL` |
| `DORINA_API_KEY` | `arn:aws:ssm:us-east-2:089200327380:parameter/linear/DORINA_API_KEY` |

**Dica:** em Systems Manager → Parameter Store → clique no parâmetro → copie o **ARN**.

12. **Log configuration** — marque **Use log collection**:

| Campo | Valor |
|-------|--------|
| Log driver | `awslogs` |
| awslogs-group | `/ecs/linear-worker` |
| awslogs-region | `us-east-2` |
| awslogs-stream-prefix | `worker` |

13. **Create** (final da task definition).

### Opção 2 — JSON

1. Edite [`task-definition.worker.example.json`](task-definition.worker.example.json): troque `ACCOUNT_ID` → `089200327380`, `REGION` → `us-east-2`.
2. ECS → Task definitions → **Create** → **Create new task definition with JSON**.
3. Cole o JSON → **Create**.

---

## Parte D — Serviço ECS (rodar o worker)

1. ECS → **Clusters** → abra `linear`.
2. Aba **Services** → **Create**.
3. **Compute configuration:** Launch type **Fargate**.
4. **Deployment configuration:**
   - Application type: **Service**
   - **Task definition:** family `linear-worker`, revisão mais recente (ex. `linear-worker:1`)
   - **Service name:** `linear-worker`
   - **Desired tasks:** `1`
5. **Networking:**
   - **VPC:** default (ou a VPC da sua org)
   - **Subnets:** marque **pelo menos 2** subnets (preferência: subnets **públicas** com **Auto-assign public IP = ENABLED** — mais simples para saída à internet sem NAT)
   - **Security group:** crie novo ou use existente:
     - Nome sugerido: `linear-worker-sg`
     - **Outbound:** All traffic → `0.0.0.0/0` (para Supabase, OpenAI, Dorina)
     - **Inbound:** nenhuma regra necessária (worker não recebe tráfego externo)
6. **Load balancing:** **None** (sem ALB).
7. **Service auto scaling:** desligado por enquanto (opcional depois).
8. **Create service**.

Aguarde **Running** e **1/1 tasks running**.

---

## Parte E — Validar

### E.1 Status no ECS

- Cluster `linear` → service `linear-worker` → aba **Tasks** → task **RUNNING**.

Se **Stopped**, clique na task → **Stopped reason** e **Logs**.

### E.2 Logs (CloudWatch)

1. CloudWatch → Log groups → `/ecs/linear-worker`.
2. Abra o stream mais recente (`worker/linear-worker/...`).
3. Procure mensagens de início do worker (worker v2 / loop de fila). Erros comuns:
   - `AccessDenied` SSM → política A.2
   - `CannotPullContainerError` → execution role / imagem ECR errada
   - Erro Postgres → `SUPABASE_DB_DSN` errado no SSM

### E.3 Teste indireto (fila)

Com a API ainda local ou depois na AWS: crie um job de teste. Nos logs do worker deve aparecer processamento do `job_id`.

---

## Problemas frequentes

| Sintoma | O que fazer |
|---------|-------------|
| Task para logo ao iniciar | Veja **Stopped reason** + log CloudWatch |
| `ResourceInitializationError: unable to pull secrets` | IAM `ecsTaskExecutionRole` sem SSM/KMS |
| `CannotPullContainerError` | URI da imagem; região ECR = us-east-2 |
| Task para logo, log `set: Illegal option -` | Scripts `.sh` com CRLF (Windows) — ver nota abaixo |

### Windows: scripts `.sh` em LF

Se o CloudWatch mostrar `scripts/start-worker.sh: set: Illegal option -`, reconstrua as imagens após garantir LF nos scripts (`*.sh` no repo usa `.gitattributes`). Rode de novo `.\deploy\aws\push-images.ps1`.
| Worker não pega jobs | Confirme `SUPABASE_DB_DSN` no SSM; worker v2 exige Postgres |

---

## Depois do worker

Siga [`README.md`](README.md) seção **API + ALB** (item 3), depois Vercel.
