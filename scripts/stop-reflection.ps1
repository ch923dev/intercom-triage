# Stop hook reflection.
#
# Runs when Claude Code is about to stop (end of turn). Reads the
# transcript and, if the session made code edits but never ran a
# quality gate (pytest / vitest / mypy / ruff / npm lint|typecheck /
# `node --test` for the extension), emits a one-time reminder to
# consider /qa-all.
#
# Triggered via .claude/settings.json hooks.Stop.
#
# Behavior:
# - `stop_hook_active = true` (we already nudged this session) -> exit 0.
# - No edits this session -> exit 0.
# - Edits without QA gate -> exit 2 with stderr reminder. Claude
#   surfaces the message; user can ignore, ask Claude to run gates,
#   or just continue.
# - Edits + QA gate already run -> exit 0 (silent).
#
# The reminder is best-effort; failures in this script never block
# Claude from finishing (exit 0 on any parse error).

$ErrorActionPreference = "Continue"

try {
    $stdin = [Console]::In.ReadToEnd()
    if (-not $stdin) { exit 0 }

    $payload = $stdin | ConvertFrom-Json
    if ($payload.stop_hook_active -eq $true) { exit 0 }

    $transcriptPath = $payload.transcript_path
    if (-not $transcriptPath -or -not (Test-Path $transcriptPath)) { exit 0 }

    $editCount = 0
    $qaCount = 0

    Get-Content $transcriptPath -ErrorAction SilentlyContinue | ForEach-Object {
        if (-not $_) { return }
        try {
            $entry = $_ | ConvertFrom-Json -ErrorAction Stop
        } catch {
            return
        }

        # Tool-use entries land under message.content[].type == "tool_use".
        $content = $entry.message.content
        if (-not $content) { return }

        foreach ($block in $content) {
            if ($block.type -ne "tool_use") { continue }

            $name = $block.name
            $cmd = $block.input.command

            if ($name -eq "Edit" -or $name -eq "Write" -or $name -eq "NotebookEdit") {
                $script:editCount++
            }
            elseif ($name -eq "Bash" -or $name -eq "PowerShell") {
                # `node --test` is the extension's only automated gate (plain
                # ES modules, no bundler) — count it like the backend/webapp gates.
                if ($cmd -match '\b(pytest|vitest|mypy|ruff|node\s+--test|npm\s+(run\s+)?(lint|test|typecheck|build|format))\b') {
                    $script:qaCount++
                }
            }
        }
    }

    if ($editCount -gt 0 -and $qaCount -eq 0) {
        [Console]::Error.WriteLine("")
        [Console]::Error.WriteLine("Stop-hook reminder: this session made $editCount code edit(s) but no quality gate ran.")
        [Console]::Error.WriteLine("Consider /qa-all (or /qa-backend / /qa-webapp) before committing.")
        [Console]::Error.WriteLine("")
        exit 2
    }

    exit 0
} catch {
    # Reflection is best-effort; never block stop on script errors.
    exit 0
}
