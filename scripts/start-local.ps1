param(
    [switch]$CreateVenv,
    [switch]$InstallDependencies,
    [switch]$StartRedisDocker,
    [switch]$SkipWorker,
    [switch]$SkipQaApi,
    [switch]$NoNewWindows
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $repoRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$envFile = Join-Path $repoRoot ".env"
$envExampleFile = Join-Path $repoRoot ".env.example"

function Get-PythonLauncher {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return "py"
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        return "python"
    }

    throw "Python nao encontrado no PATH. Instale Python 3 e tente novamente."
}

function Ensure-Venv {
    if (Test-Path $venvPython) {
        return
    }

    if (-not $CreateVenv) {
        throw "Ambiente virtual nao encontrado em .venv. Rode o script com -CreateVenv ou crie o ambiente manualmente."
    }

    $pythonLauncher = Get-PythonLauncher
    Push-Location $repoRoot
    try {
        if ($pythonLauncher -eq "py") {
            & py -3 -m venv $venvPath
        }
        else {
            & python -m venv $venvPath
        }
    }
    finally {
        Pop-Location
    }

    if (-not (Test-Path $venvPython)) {
        throw "Falha ao criar o ambiente virtual em .venv."
    }
}

function Ensure-EnvFile {
    if (Test-Path $envFile) {
        return
    }

    if (-not (Test-Path $envExampleFile)) {
        throw "Nem .env nem .env.example foram encontrados."
    }

    Copy-Item $envExampleFile $envFile
    Write-Host ".env criado a partir de .env.example. Revise as configuracoes antes de continuar." -ForegroundColor Yellow
}

function Install-ProjectDependencies {
    Push-Location $repoRoot
    try {
        & $venvPython -m pip install --upgrade pip
        & $venvPython -m pip install -r requirements.txt
    }
    finally {
        Pop-Location
    }
}

function Start-RedisContainer {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker nao encontrado no PATH. Inicie o Redis manualmente ou instale o Docker."
    }

    $containerName = "redis-local"
    $existingContainerId = (& docker ps -a --filter "name=^/${containerName}$" --format "{{.ID}}") | Select-Object -First 1

    if ($existingContainerId) {
        $isRunning = (& docker ps --filter "name=^/${containerName}$" --format "{{.ID}}") | Select-Object -First 1
        if (-not $isRunning) {
            & docker start $containerName | Out-Null
            Write-Host "Redis Docker iniciado: $containerName" -ForegroundColor Green
        }
        else {
            Write-Host "Redis Docker ja esta em execucao: $containerName" -ForegroundColor Green
        }
        return
    }

    & docker run -d --name $containerName -p 6379:6379 redis | Out-Null
    Write-Host "Redis Docker criado e iniciado: $containerName" -ForegroundColor Green
}

function Start-ProcessWindow {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Title,
        [Parameter(Mandatory = $true)]
        [string]$Command
    )

    $escapedRepoRoot = $repoRoot.Replace("'", "''")
    $escapedTitle = $Title.Replace("'", "''")
    $escapedCommand = $Command.Replace("'", "''")
    $fullCommand = "Set-Location '$escapedRepoRoot'; & '$venvPython' $escapedCommand"
    $windowCommand = "`$Host.UI.RawUI.WindowTitle = '$escapedTitle'; $fullCommand"

    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy", "Bypass",
        "-Command", $windowCommand
    ) | Out-Null
}

Ensure-Venv
Ensure-EnvFile

if ($InstallDependencies) {
    Install-ProjectDependencies
}

if ($StartRedisDocker) {
    Start-RedisContainer
}

Write-Host "Repositorio: $repoRoot" -ForegroundColor Cyan
Write-Host "Python do projeto: $venvPython" -ForegroundColor Cyan
Write-Host "Backend Java deve estar rodando antes do processamento completo." -ForegroundColor Yellow

if ($NoNewWindows) {
    if (-not $SkipWorker) {
        Write-Host "Execute em outro terminal: $venvPython main.py" -ForegroundColor Green
    }

    if (-not $SkipQaApi) {
        Write-Host "Execute em outro terminal: $venvPython -m uvicorn qa_api:app --host 0.0.0.0 --port 8001" -ForegroundColor Green
    }

    exit 0
}

if (-not $SkipWorker) {
    Start-ProcessWindow -Title "BackIa Worker" -Command "main.py"
}

if (-not $SkipQaApi) {
    Start-ProcessWindow -Title "BackIa QA API" -Command "-m uvicorn qa_api:app --host 0.0.0.0 --port 8001"
}

Write-Host "Processos iniciados." -ForegroundColor Green
Write-Host "Worker: main.py" -ForegroundColor Green
Write-Host "QA API: http://localhost:8001" -ForegroundColor Green
Write-Host "Se quiser ver apenas os comandos sem abrir novas janelas, rode com -NoNewWindows." -ForegroundColor Yellow
