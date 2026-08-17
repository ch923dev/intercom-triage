# Security

Hosted, authenticated, shared-team tool (the MHU charter pivot): multiple
operators sign in with OnlySales credentials against one shared board. We ship no
infra config — hosting is the operator's concern. The one security property that
matters for this repo: **no secret ever reaches GitHub.**

Identity is delegated. Login proxies to OnlySales and **no password is ever
stored or logged** (cross-package invariant #19); the only credential material
persisted is the Fernet-encrypted upstream OnlySales refresh token and a `sha256`
hash of our own rotating refresh token (invariant #16).

## Secrets model

All of these load from `backend/.env` at runtime (gitignored, never committed):

- `OPENROUTER_API_KEY` — the AI categorization key.
- `INTERCOM_ACCESS_TOKEN` — the workspace Access Token the backend polls
  `api.intercom.io` with (invariant #1). `INTERCOM_WORKSPACE_APP_ID` sits
  alongside it but is **not** a secret (it's the public workspace slug used only
  for deep-link URLs).
- `SESSION_JWT_SECRET` — HS256 signing key for the access JWT. Boot hard-fails
  when empty: an unsigned session is worse than no service.
- `SESSION_REFRESH_ENCRYPTION_KEY` — Fernet key encrypting the stored OnlySales
  refresh token at rest. Optional; empty means the upstream token is not stored.
- `SLACK_BOT_TOKEN` — bot token for bug-alert delivery (`xoxb-…`). Optional, and
  deliberately absent from `/health.missing_secrets`: unconfigured Slack is a
  disabled optional feature, not a degraded service.

`backend/.env.example` is the tracked template (empty values only). Every one of
these lives server-side only — none is baked into the webapp bundle, logged, or
returned in errors.

If any of them is ever committed (even if removed afterwards), treat it as
compromised and rotate: OpenRouter at <https://openrouter.ai/keys>, the Intercom
token in Intercom → Settings → Integrations → Developer Hub → your app, the Slack
token in the Slack app's OAuth page, and the session secret / Fernet key by
generating new values (rotating either invalidates live sessions, which is the
point).

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

Tuning lives in `.gitleaks.toml` (OpenRouter key + Intercom Access Token + Slack
bot token rules + allowlist for test fixtures, `.env.example`, and the public
workspace id `j3dxf22l`).

Bypass for a verified false positive: `git commit --no-verify` (use sparingly).
