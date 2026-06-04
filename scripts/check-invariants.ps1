# Pre-commit invariant check (Claude Code PreToolUse hook).
#
# Wired in .claude/settings.json under hooks.PreToolUse with matcher "Bash".
# Receives the tool invocation as JSON on stdin. If the command is a
# `git commit`, greps staged files for patterns that violate the 13
# cross-package invariants in CLAUDE.md. Exits 2 on violation (Claude
# Code interprets exit 2 as a block).
#
# Bypass for a specific commit (rare — invariants exist for a reason):
#     git commit --no-verify
# Note: --no-verify bypasses real git hooks, not Claude Code hooks. To
# bypass this PreToolUse hook from a Claude session, ask the user to
# stage the commit themselves outside Claude.

$ErrorActionPreference = "Stop"

# ── Parse hook input from stdin ───────────────────────────────────────
$stdin = [Console]::In.ReadToEnd()
if (-not $stdin) { exit 0 }

try {
    $payload = $stdin | ConvertFrom-Json
} catch {
    exit 0
}

$command = $payload.tool_input.command
if (-not $command) { exit 0 }

# Only run for `git commit`. Don't block other Bash usage.
if ($command -notmatch '\bgit\s+commit\b') { exit 0 }

# ── Collect violations ────────────────────────────────────────────────
$violations = @()

function Test-StagedPattern {
    param(
        [string]$Pattern,
        [string]$PathFilter,
        [string]$Message,
        [string[]]$ExcludePaths = @()
    )
    $files = git diff --cached --name-only --diff-filter=ACMR 2>$null | Where-Object { $_ -match $PathFilter }
    foreach ($exclude in $ExcludePaths) {
        $files = $files | Where-Object { $_ -notmatch $exclude }
    }
    if (-not $files) { return }

    foreach ($file in $files) {
        if (-not (Test-Path $file)) { continue }
        $hits = Select-String -Path $file -Pattern $Pattern -ErrorAction SilentlyContinue
        if ($hits) {
            $script:violations += "[$Message] $file"
            foreach ($h in $hits) {
                $script:violations += "    line $($h.LineNumber): $($h.Line.Trim())"
            }
        }
    }
}

# Rule 1: The extension must not access Intercom (Invariant #1 — the BACKEND is
# the only Intercom integration now, via api.intercom.io + INTERCOM_ACCESS_TOKEN).
# Flag any extension code that talks to Intercom directly.
Test-StagedPattern `
    -Pattern "app\.intercom\.com|api\.intercom\.io|ember/inbox" `
    -PathFilter "^extension/.*\.(js|json)$" `
    -Message "Invariant #1: extension must not access Intercom (backend owns ingestion)"

# Rule 2: No datetime.utcnow() in backend (Invariant #5).
Test-StagedPattern `
    -Pattern "datetime\.utcnow\(" `
    -PathFilter "^backend/app/.*\.py$" `
    -Message "Invariant #5: Use app.util.naive_utcnow(), not datetime.utcnow()"

# Rule 3: No Base.metadata.create_all outside init_db.
Test-StagedPattern `
    -Pattern "Base\.metadata\.create_all" `
    -PathFilter "^backend/" `
    -Message "Use Alembic migrations, not Base.metadata.create_all" `
    -ExcludePaths @("^backend/app/models\.py$")

# Rule 4: No importScripts in extension (service worker is type:module).
Test-StagedPattern `
    -Pattern "importScripts\(" `
    -PathFilter "^extension/.*\.js$" `
    -Message "Extension service worker is type:module - use import, not importScripts"

# Rule 5: host_permissions widening in manifest.json.
$manifestStaged = git diff --cached --name-only --diff-filter=ACMR 2>$null | Where-Object { $_ -eq "extension/manifest.json" }
if ($manifestStaged) {
    $manifestContent = git show ":extension/manifest.json" 2>$null
    $allowedHosts = @("127.0.0.1:4000", "localhost:4000")
    $hostMatches = [regex]::Matches($manifestContent, '"https?://[^"]+"')
    foreach ($match in $hostMatches) {
        $url = $match.Value.Trim('"')
        $hit = $false
        foreach ($h in $allowedHosts) {
            if ($url -like "*$h*") { $hit = $true; break }
        }
        if (-not $hit) {
            $violations += "[host_permissions widening] extension/manifest.json contains unrecognised URL: $url"
        }
    }
}

# Rule 6: defence-in-depth — never commit secrets / DB / local settings.
$forbidden = git diff --cached --name-only --diff-filter=ACMR 2>$null | Where-Object {
    $_ -match "(^|/)\.env(\.|$)" -or
    $_ -match "\.db(-journal|-wal|-shm)?$" -or
    $_ -match "^\.claude/settings\.local\.json$" -or
    $_ -match "^backend/data/"
}
foreach ($f in $forbidden) {
    $violations += "[forbidden file staged] $f -- must never be committed"
}

# ── Report ────────────────────────────────────────────────────────────
if ($violations.Count -gt 0) {
    [Console]::Error.WriteLine("")
    [Console]::Error.WriteLine("Pre-commit invariant check failed:")
    [Console]::Error.WriteLine("")
    foreach ($v in $violations) {
        [Console]::Error.WriteLine("  $v")
    }
    [Console]::Error.WriteLine("")
    [Console]::Error.WriteLine("Reference: CLAUDE.md (cross-package invariants section).")
    exit 2
}

exit 0
