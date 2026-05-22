# Seed (or reset) the local SQLite DB.
# Usage:  .\scripts\seed-db.ps1
#         .\scripts\seed-db.ps1 -Reset      # nuke the file and re-seed
param([switch]$Reset)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $repoRoot "backend")

if (-not (Test-Path ".venv")) {
    Write-Error "No .venv — run scripts\dev-backend.ps1 once to create it."
}
& .\.venv\Scripts\Activate.ps1

if ($Reset) {
    Get-ChildItem -Path "data" -Filter "triage.db*" -ErrorAction SilentlyContinue | Remove-Item -Force
    Write-Host "Wiped data\triage.db*"
}

# init_db runs at app startup; trigger via the smoke-test entry point.
python -m app.models
