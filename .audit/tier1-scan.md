# Tier 1 — Broad Scan (audit funnel)

**Repo:** intercom-ticket-management (240 tracked files; single-operator local tool)
**Date:** 2026-05-27
**Tier:** 1 of 3 — breadth over depth. Candidates only; NOT confirmed. Each line = pointer + one-line reason + severity guess for downstream tiers to chase.

## Scope covered
- **CODE:** backend/app (main, config, models, schemas, clients/openrouter, ai/pipeline, services/{tickets,attachments,cache,categories,resolution}, routers/{tickets,attachments}), extension (manifest, background, intercom, popup), webapp/src (api/client, CLAUDE patterns, store doctrine). Risk-pattern greps: bare/broad except, raw SQL, v-html/innerHTML/eval, CORS, secrets, TODO/FIXME/ts-ignore/as-any across all 3 packages.
- **ENABLEMENT:** root + 3 package CLAUDE.md, .claude/settings.json (permissions + hooks), .claude/commands (4 qa-*), .claude/skills (3), scripts/{check-invariants,stop-reflection}.ps1, .gitignore, manifest permissions. Cross-checked vs the 13 stated cross-package invariants.

## Scope skipped / lighter pass (budget)
- backend/tests/* (53 test files) — only counted + name-skimmed, not read. Tier 2 should spot-check coverage gaps (esp. attachments path-handling, ingest limits).
- Most webapp/src components (.vue) read only via store/CLAUDE doctrine, not line-by-line. `TicketConversation.vue` (renderable_type) NOT opened — flagged below for Tier 2.
- design_bundle/ (reference assets, gitignored bundle) — intentionally ignored.
- backend/.venv/ — not tracked (correctly gitignored); not scanned.
- docs/** prose, alembic migration bodies (only filenames reviewed), webapp eslint/vite/tsconfig configs.
- Pre-existing review docs **NOT re-flagged** (assume known): `backend/REVIEW-2026-05-27.md`, `webapp/REVIEW_FINDINGS.md`. Tier 2 should reconcile against these to avoid dupes.

## Method
Glob full tree → git ls-files to drop .venv/design_bundle noise → parallel Grep for risk patterns → targeted Read of highest-traffic / highest-risk files (ingest, attachments, openrouter, pipeline, CORS, hooks). Flag-don't-confirm.

---

## Candidates

### MEDIUM
| ID | Tag | Pointer | Reason | Sev |
|----|-----|---------|--------|-----|
| T1-001 | CODE | backend/app/services/attachments.py:30-42 `_extension_for`/`_stored_path_for` | On-disk path uses client-supplied filename suffix (≤16 chars) concatenated after `sha256[:2]/sha256`; `Path.suffix` *should* strip separators but extension is attacker-influenced — confirm no path-traversal / odd-suffix write. | MEDIUM |
| T1-002 | CODE | backend/app/routers/attachments.py:77 | Upload trusts client `content_type` (`mime`) verbatim; no extension/MIME allowlist. Mitigated by nosniff + forced-download for non-image mimes, but stored `mime` drives inline-disposition decision — verify spoofed image/* can't bypass. | MEDIUM |
| T1-003 | CODE | backend/app/services/tickets.py:485-530 (`get_tickets` build loop) | `# type: ignore[arg-type]` clustered on ORM→schema field copies (state/author/parts/internal_notes/resolved_source/verdict/chip); suppressions hide real type drift if a column nullability changes. Low risk, verify each still holds. | MEDIUM |
| T1-004 | ENABLEMENT | webapp/src/components/ticket/TicketConversation.vue (not read) | renderable_type 1/12/2/24/3 mapping is reverse-engineered (invariant #3) and spans 3 packages; Tier 1 did not open the webapp half — Tier 2 confirm it matches extension/intercom.js + backend schema. | MEDIUM |
| T1-005 | ENABLEMENT | backend/REVIEW-2026-05-27.md + webapp/REVIEW_FINDINGS.md | Two committed review-findings docs in package roots — stale/unresolved findings may linger and contradict current code; reconcile + decide whether they belong in docs/ or should be removed. | MEDIUM |

### LOW
| ID | Tag | Pointer | Reason | Sev |
|----|-----|---------|--------|-----|
| T1-006 | CODE | backend/app/routers/attachments.py:64 `await file.read(max_bytes+1)` | Reads whole file into memory (cap 25 MB). Fine for single-operator, but unbounded concurrent uploads × 25 MB is a memory ceiling worth noting; no streaming. | LOW |
| T1-007 | CODE | backend/app/clients/openrouter.py:47-60 `_parse_retry_after` | HTTP-date form of `Retry-After` silently ignored (returns None → computed backoff). Documented, but OpenRouter could send a date; minor over-aggressive retry. | LOW |
| T1-008 | CODE | backend/app/main.py:117-121 `poll()` empty `except` / background loops 54,84 | Broad `except Exception` swallow in sweep loops + bare `except` in extension poll — *intentional per backend CLAUDE.md §3 and extension doctrine* (must keep ticking). Listed only so Tier 2 confirms no NEW silent-failure crept in beyond the sanctioned spots. | LOW |
| T1-009 | CODE | backend/app/ai/pipeline.py:358 `except Exception` | Per-ticket fallback catch-all (batch never aborts) — sanctioned, but it also swallows programming errors (e.g. a bad `resolve`) as "ai_calls_total.error". Verify no logic bug masquerades as AI failure. | LOW |
| T1-010 | CODE | extension/background.js:117 empty `catch {}` in `poll()` | Badge-refresh failure fully silent (by design); confirm `ingestFromIntercom` auth-error rethrow path (45,71,88) still surfaces to the popup and isn't eaten here. | LOW |
| T1-011 | CODE | backend/app/services/attachments.py:55-77 | Comment says file is written *before* row insert intentionally (stray-file-on-failed-insert is "desired"); confirm sweep actually GCs such orphan files (sweep keys off DB rows — a file with no row ever is never swept). Possible disk leak. | LOW |
| T1-012 | ENABLEMENT | extension/CLAUDE.md "Architecture" vs manifest.json:10 | Docs reference `app.intercom.com/ember/...`; manifest host_permission is `https://app.intercom.com/*` (matches). But MEMORY.md "intercom-session-pivot" cites workspace-specific `ember/` + id `j3dxf22l` — verify docs/code/memory still agree on the live endpoint base. | LOW |
| T1-013 | ENABLEMENT | backend/CLAUDE.md "Configuration" mentions `.env.example` | Referenced `.env.example` not found in tracked file list (only .gitignore rules for .env). Confirm `.env.example` exists/committed or fix the doc pointer. | LOW |
| T1-014 | ENABLEMENT | .claude/settings.json:38 allow `Bash(npm --prefix webapp run *)` vs others | qa allow-list mixes `npm run lint*` (cwd-relative) and `npm --prefix webapp` forms; webapp commands must run from webapp/ — verify the qa-* command docs and allow-list don't assume mismatched cwd (agent cwd resets between bash calls per env note). | LOW |
| T1-015 | CODE | backend/app/config.py:27 `MAX_INGEST_TICKETS = 500` | Not covered by the `bump-max-bulk-ids` skill (which only guards MAX_BULK_IDS=200). A second un-skilled magic cap; confirm webapp/extension don't need to know it (extension fetches count=60/state — likely fine). | LOW |
| T1-016 | ENABLEMENT | docs/tasks/phase-02-intercom-superseded.md | A whole "superseded" phase doc retained; ensure it's clearly marked dead so a future Claude doesn't implement the abandoned Access-Token path (contradicts invariant #1). | LOW |

### INFO / NEGATIVE FINDINGS (scanned, looked clean — recorded so Tier 2 can deprioritize)
- CORS (main.py:166-173): origins pinned to 5173 + `chrome-extension://[a-z]{32}` regex, `allow_credentials=False`. No wildcard origin. Doc/code agree. CLEAN.
- No `v-html` / `innerHTML` / `eval` / `new Function` anywhere in webapp or extension. popup.js builds DOM via `createElement`+`textContent`. CLEAN (no obvious XSS sink).
- No raw/string-built SQL. All `text()` uses are static (server defaults, partial-index WHERE). SQLAlchemy 2.0 typed selects throughout. CLEAN.
- No hardcoded secrets. OPENROUTER_API_KEY via pydantic-settings; missing-secret → degraded boot per FR-014. CLEAN.
- Resolution XOR (models.py CheckConstraints) + Settings singleton (`id=1`) enforced at DB layer. Invariants #10/#12 backed by constraints. CLEAN.
- Ingest batch capped (500 → 413), bulk capped (200 via schema max_length), upload size capped (25 MB → 413). DoS surface bounded. CLEAN.
- Harness: deny-list blocks destructive git + secret/db writes; PreToolUse invariant hook (greps staged for 6 rules) + Stop QA-reminder hook both robust (exit-0 on parse error, never hard-block wrongly). Skills cover the 3 cross-package edit traps. STRONG.

---
**Return to orchestrator:** full candidate list above (T1-001..T1-016 + negative findings). Forward to Tier 2 for confirmation/depth.
