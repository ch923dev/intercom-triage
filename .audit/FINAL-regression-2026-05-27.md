# Regression Audit — Post-Remediation Check

**Repo:** intercom-ticket-management
**Date:** 2026-05-27 · **HEAD:** `f0fa441` · **Baseline:** `1b64aef` (the audit in [`FINAL.md`](./FINAL.md))
**Method:** same 3-tier funnel, re-run as a regression pass. Two isolated subagents (broad bug-hunt + per-finding verification); this doc is the Tier-3 synthesis. Original reports left untouched.

---

## Verdict: PASS ✅

All 4 merged fixes are present at HEAD, each correct, each closes its baseline finding. No regressions. No new CRITICAL/HIGH/MEDIUM/LOW defects. One net-new **INFO** observation (a threat-model-bounded concurrency window introduced by fix #5). All deferred / no-action / dismissed items hold.

**Delta since baseline** = exactly the 4 audit fixes (`git diff --stat 1b64aef..f0fa441` = 6 files, only one of them runtime code). Working tree clean.

---

## Fix verification (the 4 merged batches)

| Finding | Fix | Verified at HEAD | Tests |
|---------|-----|------------------|-------|
| #1 | banner on `backend/REVIEW-2026-05-27.md` | ✓ banner at `:3-4`, doc otherwise intact (125 lines) | doc-only |
| #3 | `check-invariants.ps1` docstring `12`→`13` | ✓ `:5` says 13; root CLAUDE.md genuinely lists 13 (1→13) | comment-only |
| #4 | qa docs → `npm --prefix webapp run …` | ✓ all 5 lines match allow glob `Bash(npm --prefix webapp run *)` @ `settings.json:38`; scripts exist in `package.json`; backend `cd backend` block untouched | doc-only |
| #5 | `attachments.py` unlink fresh file on commit failure | ✓ `wrote_file` guard + `except`/unlink/`raise` at `:80-85`; deduped-file-not-unlinked guarantee holds; docstring accurate | +2 regression tests, **proven not false-green** (removing the fix flips `test_upload_unlinks_fresh_file_when_commit_fails` to red) |

Full backend gate at HEAD: **249 passed**, ruff + format + mypy clean.

---

## New observation (net-new, introduced by fix #5)

### R1. [CODE] — INFO · Concurrent identical-byte upload could wrong-delete a committed sibling's file
- **Location:** `backend/app/services/attachments.py:64, 83-84`
- **Problem:** Fix #5 trades the old orphan-leak for a new race: if two requests upload *identical bytes* concurrently and both compute `wrote_file=True` (B's `exists()` check wins the race before A's `write_bytes`), then A commits successfully while B's commit fails, B's `unlink` removes the file A's now-committed row references. The pre-fix code never unlinked, so this path did not exist.
- **Why INFO, not higher:** single-operator local tool, sequential UI uploads. Concurrent identical-byte uploads with one commit failing is effectively impossible under the documented threat model. The old leak it replaced was also threat-model-bounded; net risk is a wash and arguably better (no silent disk growth).
- **Fix:** None recommended. If ever hardened: temp-file-then-atomic-rename, or skip the unlink when a committed sibling row for the sha already exists.
- **Confidence:** High (reasoned from code; concurrency not empirically reproducible against in-memory SQLite).

---

## Outstanding items (unchanged — still operator-only)

| # | State at HEAD | Action |
|---|---------------|--------|
| #2 | `backend/.env:4` `INTERCOM_ACCESS_TOKEN=` **still present** (dead at runtime — `config.py` has zero refs; never committed) | Operator hand-deletes (`.env` on agent deny-list) |
| #8 | `backend/.env:8` live `OPENROUTER_API_KEY=sk-or-v1-…` present (value never echoed) | Awareness only — not a defect |

## No-action (sanctioned) — confirmed unchanged
- **#6** broad `except` cluster — `main.py:54/84`, `ai/pipeline.py:358`, `extension/background.js:117`, `clients/openrouter.py:47-60`. As-described.
- **#7** `tickets.py` 7× `# type: ignore[arg-type]` (`:505-529`) + 25 MB in-mem upload read (`attachments.py` router `:64`). As-described.

## Dismissed candidates — re-confirmed safe
- **T1-002** (upload nosniff/forced-download/raster allowlist) — `_INLINE_SAFE_MIMES` + forced `Content-Disposition` + `X-Content-Type-Options: nosniff` all present in attachments router. Holds.
- **T1-004** (renderable_type decoded once in `extension/intercom.js:41-43`; backend+webapp consume `is_admin`) — holds.
- T1-001, T1-012, T1-013, T1-015, T1-016 — no contradicting evidence.

---

## Doc-accuracy nits in the original FINAL.md (not code defects, no action)
- #6 prose bundled `main.py:54/84/117`; the `117` is actually `extension/background.js:117` (also listed separately). In `main.py` the two broad-`except` loops are `:54` and `:84`; `:145/150` are `except asyncio.CancelledError` shutdown handlers, not the flagged pattern.
- #5 line refs (`:62-63` write / `:76-77` commit) shifted post-fix to `:66` write / `:80-85` commit — expected from the remediation edit.

---

## Tier trail (this regression pass)
- Broad bug-hunt agent: verdict CORRECT on all 4 fixes; PART-2 breadth pass found no new defects; surfaced R1 (INFO).
- Verification agent: per-finding + dismissed-candidate state table, all ✓, no correctness discrepancies.
- Synthesis (this doc): no resurrected findings, no severity corrections, 1 INFO added (R1).
