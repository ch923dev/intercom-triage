# Boot backend in --reload mode against .env in backend/.
# Usage: .\scripts\dev-backend.ps1
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $repoRoot "backend")

if (-not (Test-Path ".venv")) {
    Write-Host "Creating venv..."
    python -m venv .venv
    & .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt
} else {
    & .\.venv\Scripts\Activate.ps1
}

if (-not (Test-Path ".env")) {
    Write-Warning "No backend\.env — copy .env.example and fill in tokens."
}

uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
