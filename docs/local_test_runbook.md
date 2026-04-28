# Runbook local de validacao (backend)

Objetivo: validar com seguranca a estrutura atual antes do frontend.

## 1) Pre-requisitos

- Python 3.11+
- Poppler instalado (necessario para `pdf2image`)
- Supabase configurado
- Chaves OpenAI e Dorina validas

## 2) Preparar ambiente

1. Crie/ajuste o `.env` a partir de `.env.example`.
2. Instale dependencias:

```powershell
pip install -r requirements.txt
```

3. Confirme variaveis minimas no `.env`:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `SUPABASE_DB_DSN`
   - `OPENAI_API_KEY`
   - `DORINA_API_URL`
   - `DORINA_API_KEY`

## 3) Subir backend local (2 terminais)

Terminal A (API):

```powershell
python run_api.py
```

Terminal B (Worker):

```powershell
python run_worker.py
```

Sinais esperados:
- API responde em `http://localhost:8000/health`
- Worker mostra log `Worker iniciado`

## 4) Teste feliz - `linearizar`

Use um PDF pequeno (2 a 3 paginas) e um ISBN valido.

Exemplo de ISBN valido para teste: `9780306406157`

Upload:

```powershell
$form = @{
  isbn = "9780306406157"
  job_type = "linearizar"
  prompt_version = "v1"
  pdf_file = Get-Item ".\seu_teste.pdf"
}

$resp = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/jobs/upload" -Form $form
$resp | ConvertTo-Json -Depth 10
```

Guarde o `id` retornado:

```powershell
$jobId = $resp.id
```

Polling de status:

```powershell
do {
  Start-Sleep -Seconds 3
  $job = Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/v1/jobs/$jobId"
  "status=$($job.status) etapa=$($job.etapa_atual) tentativas=$($job.tentativas)"
} while ($job.status -eq "queued" -or $job.status -eq "running")

$job | ConvertTo-Json -Depth 10
```

Resultado final:

```powershell
$result = Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/v1/jobs/$jobId/result-url"
$result | ConvertTo-Json -Depth 10
```

Abra `download_url` no navegador e valide o JSON.

## 5) Teste feliz - `contextualizar`

Repita o upload alterando:

```powershell
job_type = "contextualizar"
```

Esperado:
- pipeline executa sem linearizacao completa de pagina
- export direcionado para fluxo Avalia

## 6) Testes de erro obrigatorios

### 6.1 ISBN invalido

Use `isbn = "123"` no upload.

Esperado: HTTP 400.

### 6.2 PDF vazio/corrompido

Envie arquivo vazio ou nao-PDF.

Esperado: HTTP 400.

### 6.3 Falha de integracao (Dorina/OpenAI)

Temporariamente coloque URL invalida no `.env` (ex.: `DORINA_API_URL=http://localhost:9999`), reinicie API/worker e rode um job.

Esperado:
- job vai para `failed` ou requeue ate atingir `WORKER_MAX_ATTEMPTS`
- `error_message` preenchido

## 7) Teste de retry manual

Depois de um `failed`:

```powershell
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/jobs/$jobId/retry"
```

Esperado:
- status volta para `queued`
- worker processa novamente

## 8) Criterio para liberar inicio do frontend

Iniciar front so quando estes 6 pontos estiverem verdes:

1. Upload `linearizar` finaliza em `done`
2. Upload `contextualizar` finaliza em `done`
3. `result-url` retorna link valido
4. Erro de ISBN invalido retorna 400
5. Falha externa gera `failed` com mensagem
6. Retry reprocessa job com sucesso

## 9) Escopo inicial do frontend (depois da validacao)

1. Tela de upload (PDF + ISBN + modo)
2. Tela de status de job
3. Tela de resultado (download JSON)

Sem novas features ate estabilizar este fluxo.
