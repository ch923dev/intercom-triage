# Single-command dev launcher.
#
# 1. Ensures backend Python venv + pip deps (handles new/outdated packages).
# 2. Ensures webapp npm deps (handles new/outdated packages).
# 3. Opens a Windows Terminal window with backend (:4000) and webapp (:5173)
#    in a vertical split-pane.
#
# Backend:   127.0.0.1:4000  (uvicorn --reload)
# Webapp:    127.0.0.1:5173  (Vite, proxies /api -> :4000)
#
# Requires Windows Terminal (wt.exe). Default on Windows 11.

$ErrorActionPreference = 'Stop'

$repoRoot   = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repoRoot 'backend'
$webappDir  = Join-Path $repoRoot 'webapp'

# ── Backend deps ─────────────────────────────────────────────────
Write-Host '[dev] backend: ensuring venv + pip deps' -ForegroundColor Cyan
Push-Location $backendDir
try {
    if (-not (Test-Path '.venv')) {
        Write-Host '[dev]   creating .venv...' -ForegroundColor DarkGray
        python -m venv .venv
    }
    & .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -r requirements.txt
    if (Test-Path 'requirements-dev.txt') {
        & .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -r requirements-dev.txt
    }
    if (-not (Test-Path '.env')) {
        Write-Warning 'No backend/.env — copy backend/.env.example and fill in OPENROUTER_API_KEY.'
    }
} finally {
    Pop-Location
}

# ── Webapp deps ──────────────────────────────────────────────────
Write-Host '[dev] webapp: ensuring npm deps' -ForegroundColor Cyan
Push-Location $webappDir
try {
    npm install --silent
} finally {
    Pop-Location
}

# ── Launch split-pane Windows Terminal ───────────────────────────
$wt = Get-Command wt.exe -ErrorAction SilentlyContinue
if (-not $wt) {
    throw 'wt.exe (Windows Terminal) not found. Install from Microsoft Store, or run backend + webapp in two terminals manually.'
}

$shell = if (Get-Command pwsh.exe -ErrorAction SilentlyContinue) { 'pwsh.exe' } else { 'powershell.exe' }

$backendUvicorn = Join-Path $backendDir '.venv\Scripts\uvicorn.exe'
$backendCmd = "& '$backendUvicorn' app.main:app --reload --host 127.0.0.1 --port 4000"
$webappCmd  = 'npm run dev'

Write-Host '[dev] launching split-pane Windows Terminal...' -ForegroundColor Cyan
wt.exe new-tab --title 'backend :4000' --startingDirectory "$backendDir" $shell -NoExit -Command $backendCmd `; split-pane --vertical --title 'webapp :5173' --startingDirectory "$webappDir" $shell -NoExit -Command $webappCmd
