# Security

Single-operator local tool. No hosted surface, no auth, no deployment. The one
security property that matters for this repo: **no secret ever reaches GitHub.**

## Secrets model

- The only real secret is `OPENROUTER_API_KEY`, loaded from `backend/.env` at
  runtime. `backend/.env` is gitignored and must never be committed.
- `backend/.env.example` is the tracked template (empty values only).
- The extension uses **no Intercom token** — it reads Intercom through the
  operator's logged-in browser session (cookie). See CLAUDE.md invariant #1.
- No secret is logged, returned in errors, or baked into the webapp/extension
  client bundle.

If a key is ever committed (even then removed), treat it as compromised and
rotate it at <https://openrouter.ai/keys>.

## Pre-commit secret guard

`.githooks/pre-commit` blocks commits that contain credential files or
secret-shaped strings. It runs `gitleaks` if installed and always falls back to
a built-in regex sweep, so it guards even without gitleaks.

**Enable once per clone** (the hook path is local git config, not committed):

```sh
git config core.hooksPath .githooks
```

Optional, strengthens scanning — install gitleaks:

```sh
winget install gitleaks   # or: scoop install gitleaks / brew install gitleaks
```

Tuning lives in `.gitleaks.toml` (OpenRouter key rule + allowlist for test
fixtures, `.env.example`, and the public workspace id `j3dxf22l`).

Bypass for a verified false positive: `git commit --no-verify` (use sparingly).
