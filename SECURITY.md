# Security

Single-operator local tool. No hosted surface, no auth, no deployment. The one
security property that matters for this repo: **no secret ever reaches GitHub.**

## Secrets model

- Two secrets, both loaded from `backend/.env` at runtime (gitignored, never
  committed):
  - `OPENROUTER_API_KEY` — the AI categorization key.
  - `INTERCOM_ACCESS_TOKEN` — the workspace Access Token the backend polls
    `api.intercom.io` with (cross-package invariant #1). `INTERCOM_WORKSPACE_APP_ID`
    sits alongside it but is **not** a secret (it's the public workspace slug used
    only for deep-link URLs).
- `backend/.env.example` is the tracked template (empty values only).
- Both tokens live server-side only — neither is baked into the webapp
  bundle, logged, or returned in errors.

If either key is ever committed (even then removed), treat it as compromised and
rotate it — OpenRouter at <https://openrouter.ai/keys>, the Intercom token in
Intercom → Settings → Integrations → Developer Hub → your app.

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

Tuning lives in `.gitleaks.toml` (OpenRouter key + Intercom Access Token rules +
allowlist for test fixtures, `.env.example`, and the public workspace id
`j3dxf22l`).

Bypass for a verified false positive: `git commit --no-verify` (use sparingly).
