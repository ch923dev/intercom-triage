# Tier 3 — Verification (audit funnel)

**Repo:** intercom-ticket-management (single-operator LOCAL tool — threat model applied throughout)
**Date:** 2026-05-27
**Tier:** 3 of 3 — independently stress-test every surviving Tier 2 finding against the actual code, spot-check dismissals, verify the remediation-merge claim, final sweep.

> **Read-only pass.** No code/config changed. The only write is this file.
> Every line number below was confirmed by opening the cited file myself, not trusting Tier 2's transcription.

---

## Method note — Tier 2 line-citation aliasing

Tier 2 wrote citations like `tickets.py:185-187`, `:169`, `:107` for the C1/C2/M3 fixes. There are **two** files named `tickets.py` (`app/routers/tickets.py` and `app/services/tickets.py`) plus `app/services/resolution.py`. Those line numbers resolve to **`services/tickets.py`** and `resolution.py`, NOT the router. The fixes are real and present; Tier 2's shorthand was just ambiguous. Recorded so FINAL.md cites the right file.

---

## Per-finding verdicts

### T1-005 — Stale review docs (PROMOTED MEDIUM-HIGH enablement) — **VERIFIED**
Evidence: `git ls-files` confirms both `backend/REVIEW-2026-05-27.md` and `webapp/REVIEW_FINDINGS.md` are tracked at package roots. The backend doc has **no resolved/fixed/historical banner** (grep for `resolved|fixed|landed|historical` returns only finding-body text, never a top banner); its `## CRITICAL` C1 section reads fully live ("the single most common auto-resolve path… the thing to fix now") with a "recommended order of action" that opens "1. Fix C1". The webapp doc, by contrast, *does* carry a `> Update — fixes landed on branch…` banner listing C1/C2/C3/F1/S1/S3/A1. So the asymmetry Tier 2 described is exactly real: the backend doc is a live-looking action list for already-fixed bugs. Severity is right — this is the single most consequential funnel item. Tier 2's "cross-check before pruning: L1 (no content-signature hash), C2-residual, H4" caveat is also sound (those items appear in the doc body and are genuinely not in the merge).
Proposed fix (delete or add a RESOLVED banner + move to `docs/`) is safe: these are markdown docs, no code depends on them.

### T2-NEW-01 — Dead `INTERCOM_ACCESS_TOKEN=` in `backend/.env` (LOW) — **VERIFIED, with an added observation**
Evidence: `backend/.env` line 4 is `INTERCOM_ACCESS_TOKEN=` (empty) — confirmed by reading the file. `git ls-files` returns only `backend/.env.example` (the `.env` itself is untracked); `git log --all -- backend/.env` is empty → **never committed, no history leak**. `AppConfig` has no such field and `extra="ignore"`, so zero runtime effect. Hook Rule 1 greps `INTERCOM_ACCESS_TOKEN` only under `^backend/app/` and Rule 6 forbids committing any `.env` at all, so the dead line is invisible to the hook — Tier 2's reasoning is correct. Fix (operator deletes line 4; agents can't — `.env` is on the Write/Edit deny-list, confirmed `settings.json:21`) is sound.
**Added observation (not a defect):** the same `.env` carries a **live `OPENROUTER_API_KEY=sk-or-v1-…`** in plaintext. Expected for a single-operator local tool and correctly gitignored/untracked, so no leak — but worth a one-line note in FINAL because the audit's own `.audit/` files and this verification do not echo the key, and the operator should be aware a real secret sits beside the dead token line they'll be editing. **Not** resurrected as a finding; in-threat-model.

### T2-NEW-02 — Hook docstring "12 invariants" vs CLAUDE.md's 13 (LOW) — **VERIFIED**
Evidence: `scripts/check-invariants.ps1:5` reads "the 12 / cross-package invariants in CLAUDE.md"; root CLAUDE.md enumerates 13 (playbooks = #13). The hook enforces 6 grep rules regardless, so enforcement is unaffected — pure doc drift. Fix (s/12/13/ or make count-agnostic) is trivially safe.

### T1-014 — qa-* cwd + allow-list friction (DOWNGRADED to LOW) — **VERIFIED**
Evidence: `qa-backend.md` and `qa-webapp.md` both present a multi-line PowerShell block starting `cd backend` / `cd webapp` on its own line, then package-relative gate commands (`ruff check app tests`, `npm run lint`). Env note confirms cwd resets between Bash calls, so the block must be one invocation — real but minor. `settings.json:26-46` allows `Bash(npm run lint*)` etc. (cwd-relative, used by qa-webapp via `cd webapp`) **and** `Bash(npm --prefix webapp run *)` (line 38) which the qa docs never use → dead allow surface, exactly as Tier 2 said. `cd` is not itself allow-listed → a compound `cd backend; ruff …` may prompt once. No gate is wrong; outputs trustworthy. LOW is correct; the two polish suggestions are safe.

### T1-011 — Orphan attachment file never GC'd (LOW, confirmed-as-is) — **VERIFIED**
Evidence: `services/attachments.py:62-63` writes the file (`anyio.to_thread.run_sync(abs_path.write_bytes, data)`) **before** `session.add` + `commit` at `:76-77`. `sweep_attachments` (`:151-188`) iterates only `NoteAttachment` rows with a past `deleted_at`; a file with no row is invisible to it forever. Content-addressed naming (`if not abs_path.exists()` at `:62`) means an identical re-upload reuses the orphan → self-heals, never multiplies. Real micro-leak on a rare commit failure; negligible for one operator on local disk. By-design per the docstring. No fix needed; the optional orphan-file sweep is gold-plating. Correct.

### T1-006 — Whole-file read into memory (LOW, confirmed-as-is) — **VERIFIED**
Evidence: `routers/attachments.py:64` `await file.read(config.attachment_max_bytes + 1)`; `:65-69` rejects `> max_bytes` with 413. The `+1` correctly bounds memory at the cap+1 without streaming. One operator, one upload at a time. Sized for the threat model. Correct.

### T1-007 — HTTP-date Retry-After ignored (LOW, confirmed-as-is) — **VERIFIED**
Evidence: `clients/openrouter.py:47-60` `_parse_retry_after` parses numeric seconds only; the HTTP-date form returns `None` → falls back to computed exponential+jitter backoff (`:42-44`, jitter `[0.8,1.2]`). Worst case: slightly over-aggressive retry on a hypothetical date header against one external API. No correctness impact. Correct.

### T1-003 / T1-008 / T1-009 / T1-010 — suppressions / sanctioned catch-alls (LOW, pass-through) — **VERIFIED**
Evidence: `ai/pipeline.py:358` `except Exception` is the documented per-ticket fallback (`out[ticket.id] = _fallback(...)`, `ai_calls_total.error`) so the batch never aborts — sanctioned by backend CLAUDE.md §3. The `type: ignore[arg-type]` pattern (e.g. `routers/attachments.py:39`, and the cluster in `services/tickets.py`) is the standard ORM→Literal narrowing where DB-side CheckConstraints (`models.py:519-527`) constrain the values mypy can't prove — no nullability drift. Extension badge `catch {}` and the auth-error bubble (`IntercomSessionError`) are per extension doctrine. No NEW silent failure crept in. Correct.

---

## Remediation-merge verification (Tier 2's central claim) — **CONFIRMED, with tests**

I verified the *actual fixed code is present*, not just commit messages. HEAD = `1b64aef`.

| Item | Verified in code | Verdict |
|---|---|---|
| **C1** verdict→source map | `services/tickets.py:184-187` — `resolved_source = "ai_resolved" if verdict=="resolved" else "non_actionable"`. NOT the raw verdict. | FIXED |
| C1 3-package contract | `models.py:525` CheckConstraint includes `'ai_resolved'`; `schemas.py:56` `ResolvedSource` Literal includes it; `webapp/src/types/api.ts:20` includes it. XOR constraint `models.py:519-522` intact. | FIXED (all 3 packages) |
| **C1 regression test** | `tests/test_resolution_ingest.py:234` `test_ingest_auto_resolves_when_verdict_resolved_uses_ai_resolved_source` asserts `resolved_source == "ai_resolved"`. The exact gap the doc flagged is now closed. | TEST PRESENT |
| **C2** reopen durability | `services/tickets.py:169` guard `if row.resolution_cleared_at is not None and content_signature <= row.resolution_cleared_at: return`; `resolution.py:59` sets `resolution_cleared_at` on reopen; `services/tickets.py:111` sets it on drag-out reopen. | FIXED |
| C2 regression test | `tests/test_resolution_ingest.py:295+` asserts `resolved_at is None` after reopen ("auto-resolve must not re-stamp after manual reopen"). | TEST PRESENT |
| **M1** ingest cap | `routers/tickets.py:68-72` → 413 when `len(body) > MAX_INGEST_TICKETS`; `config.py:27` `MAX_INGEST_TICKETS = 500`; test in `tests/test_ingest_api.py`. | FIXED |
| **M2** blocking I/O | `services/attachments.py:63` write + `:141` PIL render both `anyio.to_thread.run_sync`. | FIXED |
| **M3** set_override orphan | `services/tickets.py:106-107` → 404 when ticket is None (before commit, atomic with override). | FIXED |
| **S1** inline-mime XSS | `routers/attachments.py:32` raster allowlist, `:107` forced `attachment` disposition for non-allowlisted, `:113` `X-Content-Type-Options: nosniff`. | FIXED |
| **F1** CRLF format gate | `.gitattributes` `* text=auto eol=lf`; `webapp/.prettierrc.json:8` `endOfLine: auto`. | FIXED |
| **H3** CVE deps | (commit `54a3022` bumps fastapi/starlette/pillow/python-multipart/pytest; not re-run pip-audit here but the version-bump commit is in history.) | FIXED (commit present) |

Tier 2's headline claim holds: the batch is genuinely merged AND test-backed. No ghost-fixing risk on the code itself — only the stale *doc* (T1-005) misrepresents the state.

---

## Dismissals checked (independent ruling)

- **T1-002 spoofed mime / inline render (the one I was told to scrutinize)** — **DISMISSAL UPHELD.** `routers/attachments.py:107` `disposition = "inline" if row.mime in _INLINE_SAFE_MIMES else "attachment"`; `_INLINE_SAFE_MIMES` (`:32`) is raster-only (png/jpeg/gif/webp/bmp). A spoofed `text/html` or `image/svg+xml` falls to `attachment` (force-download, no in-origin render); a spoofed `image/png` carrying markup won't execute under `nosniff` + image media-type. Self-XSS surface for the lone operator is closed. Safe.
- **T1-004 renderable_type invariant #3 (the other one I was told to scrutinize)** — **DISMISSAL UPHELD.** Numeric decoding lives ONLY in `extension/intercom.js:41-43` (`INBOUND={1,12}`, `ADMIN_REPLY={2,24}`, `INTERNAL_NOTE=3`). `webapp/.../TicketConversation.vue:35` consumes the resolved `is_admin` boolean (`p.is_admin ? 'admin':'customer'`); line 9 only *mentions* `renderable_type` in a comment. Backend `schemas.py` carries `is_admin`, never re-decodes the numerics. Invariant #3 is single-sourced and consistent end-to-end. No drift.
- **T1-001 path traversal via filename suffix** — **DISMISSAL UPHELD.** `services/attachments.py:33` `Path(filename).suffix`; `Path.suffix` is the segment after the last dot of the final component and cannot contain `/` or `\`. Appended after a server-derived `{sha[:2]}/{sha}` prefix (`:42`), ≤16-char cap (`:34`). Write stays inside `attachments_dir`. Safe.
- **T1-012 / T1-013 / T1-015 / T1-016** — spot-confirmed cheaply: `.env.example` is tracked (`git ls-files`); `MAX_INGEST_TICKETS` has no client-contract coupling (extension fetches per-state, webapp never bulk-ingests); `check-invariants.ps1` Rule 1 backstops any re-introduction of `api.intercom.io`/token under `backend/app/`; CORS pinned (`main.py:166-173`, `allow_credentials=False`, no wildcard). All dismissals hold.

No dismissal was wrongly made; nothing resurrected.

---

## Final sweep — independent pass for missed issues

Quick targeted look beyond the funnel's candidates. **No new CRITICAL/HIGH found.** Candidates noted:

- **T3-NEW-01 — [INFO, not a defect] Live `OPENROUTER_API_KEY` in plaintext `backend/.env`.** Pointer: `backend/.env` (untracked, never committed). In threat model (single-operator local tool, operator's own key on own machine) this is expected and correctly gitignored. Flagged only so FINAL notes a real secret sits beside the dead `INTERCOM_ACCESS_TOKEN=` line the operator will edit (T2-NEW-01). **No action required beyond awareness.** Severity: INFO.
- Pipeline fallback (`ai/pipeline.py:351-360`): re-read with the "does a logic bug masquerade as AI failure?" lens (T1-009). The `except Exception` wraps `parse_response` + `resolve`; both are pure/DB helpers whose failures are legitimately per-ticket. `_fallback` is correctly never cached (CLAUDE.md §3 / invariant #7) — the cache-skip lives in the ingest service, not here. No masked logic bug. Clean.
- CORS / secrets / raw-SQL / v-html: re-confirmed clean (CORS `main.py:166-173`; no new sinks). Consistent with Tier 1 negatives.

No rabbit-holing beyond this; budget respected.

---

## Summary for orchestrator (→ FINAL.md)

**Per-finding verdicts:**
- T1-005 (stale docs, MED-HIGH) — **VERIFIED** (backend doc has no banner; reads live; correct top item).
- T2-NEW-01 (.env dead token, LOW) — **VERIFIED** (present, never committed, harmless; +observation: live OpenRouter key beside it).
- T2-NEW-02 (hook "12"→"13", LOW) — **VERIFIED**.
- T1-014 (qa cwd/allow-list, LOW) — **VERIFIED** (incl. dead `npm --prefix webapp run *` entry at `settings.json:38`).
- T1-011 (orphan file, LOW) — **VERIFIED** (self-heals, by design).
- T1-006 / T1-007 / T1-003 / T1-008 / T1-009 / T1-010 (LOW cluster) — **VERIFIED** (all sanctioned/sized for threat model).

**Severity corrections:** none. Every Tier 2 severity is right.
**Fixes flagged unsafe:** none. All proposed fixes (delete/banner docs, delete `.env` line, s/12/13/, qa polish) are doc/config-only with no code, test, or invariant side effects.
**Resurrected findings:** none.
**Newly found:** T3-NEW-01 (INFO only — live API key in gitignored `.env`; in-threat-model, awareness note).

**Remediation-merge claim:** **CONFIRMED in code AND tests** — C1 (incl. 3-package `ai_resolved` contract + regression test), C2 (`resolution_cleared_at` guard + reopen-durability test), M1/M2/M3, S1, F1 all present at HEAD `1b64aef`. Not trusting commit messages — opened each.

**Confidence in the funnel's overall conclusion: HIGH.** No CRITICAL or genuine HIGH code defect remains. The one real risk is enablement (T1-005 stale backend review doc with no resolved banner), correctly promoted. Dismissals (esp. the two I was asked to scrutinize — T1-002 mime, T1-004 renderable_type) are genuinely safe. The only thing the funnel under-emphasized is cosmetic: a live secret sits in the untracked `.env` next to the dead token line — worth one awareness sentence, not a finding.
