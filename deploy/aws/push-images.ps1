# Build e push das imagens linear-api e linear-worker para o ECR.
# Uso: .\deploy\aws\push-images.ps1 -Region us-west-2

param(
    [string]$Region = "us-west-2",
    [string]$Tag = "latest"
)

$ErrorActionPreference = "Stop"

function Invoke-AwsCli {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$AwsCliArgs)

    $previous = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        $text = (& aws @AwsCliArgs 2>&1 | Out-String).Trim()
        $code = $LASTEXITCODE
        return [pscustomobject]@{ ExitCode = $code; Output = $text }
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Ensure-EcrRepository {
    param([string]$Name, [string]$Region)

    $describe = Invoke-AwsCli ecr describe-repositories --repository-names $Name --region $Region
    if ($describe.ExitCode -eq 0) {
        Write-Host "Repositorio ECR ja existe: $Name"
        return
    }

    Write-Host "Criando repositorio ECR: $Name"
    $create = Invoke-AwsCli ecr create-repository --repository-name $Name --region $Region
    if ($create.ExitCode -ne 0) {
        throw "Falha ao criar $Name : $($create.Output)"
    }
}

$identity = Invoke-AwsCli sts get-caller-identity --query Account --output text
if ($identity.ExitCode -ne 0 -or -not $identity.Output) {
    throw "Falha ao obter Account ID: $($identity.Output)"
}
$AccountId = $identity.Output.Trim()
$Registry = "$AccountId.dkr.ecr.$Region.amazonaws.com"
Write-Host "Registry: $Registry"

$login = Invoke-AwsCli ecr get-login-password --region $Region
if ($login.ExitCode -ne 0) {
    throw "Falha ecr get-login-password: $($login.Output)"
}

$login.Output | docker login --username AWS --password-stdin $Registry
if ($LASTEXITCODE -ne 0) {
    throw "Falha docker login no ECR"
}
Write-Host "Docker login OK"

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Push-Location $root
try {
    foreach ($Repo in @("linear-api", "linear-worker")) {
        Ensure-EcrRepository -Name $Repo -Region $Region

        $Dockerfile = if ($Repo -eq "linear-api") { "Dockerfile.api" } else { "Dockerfile.worker" }
        Write-Host "Build: $Repo ($Dockerfile)"
        docker build -f $Dockerfile -t "${Repo}:${Tag}" .
        if ($LASTEXITCODE -ne 0) { throw "Falha docker build $Repo" }

        docker tag "${Repo}:${Tag}" "$Registry/${Repo}:${Tag}"
        Write-Host "Push: $Registry/${Repo}:${Tag}"
        docker push "$Registry/${Repo}:${Tag}"
        if ($LASTEXITCODE -ne 0) { throw "Falha docker push $Repo" }

        Write-Host "OK: $Registry/${Repo}:${Tag}"
    }
} finally {
    Pop-Location
}

Write-Host "`nImagens publicadas. Atualize as task definitions ECS com essas URIs."
