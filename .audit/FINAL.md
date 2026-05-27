# Tiered Audit — FINAL Ranked Findings

**Repo:** intercom-ticket-management (single-operator local tool — FastAPI backend / Vue 3 webapp / Chrome MV3 extension)
**Date:** 2026-05-27 · **HEAD:** `1b64aef` (backend+webapp review remediation already merged)
**Method:** 3-tier funnel — Broad Scan → Deep Dive → Verify. Each tier in an isolated context; reports at `.audit/tier{1,2,3}-*.md`. All findings below independently re-confirmed against code in Tier 3.

---

## Summary

**Funnel narrowing:** 16 candidates in (Tier 1) → 11 confirmed out → 7 dismissed, 2 added (Tier 2) → 0 resurrected, 0 severity corrections, 1 INFO sweep item (Tier 3).

**Severity counts (surviving):**

| Severity | Count |
|----------|-------|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM-HIGH | 1 |
| LOW | 6 |
| INFO | 1 |

**Headline:** No critical or high code defect remains. The remediation batch in HEAD (`C1` crash, `C2`, `M1/M2/M3`, `S1` forced-download, `H3`) was confirmed present in actual code *and* covered by tests — Tier 3 verified each rather than trusting commit messages. The funnel's single real risk is an **enablement** item: a stale, un-bannered backend review doc that will mislead a future session. Everything else is doc-hygiene or sanctioned-by-design.

**Top 3 actions overall:**
1. Banner or delete `backend/REVIEW-2026-05-27.md` — it reads as a live "fix now" list for bugs already fixed (#1).
2. Operator deletes the dead `INTERCOM_ACCESS_TOKEN=` line at `backend/.env:4` — cognitive contradiction of invariant #1 (#2). *(agent-blocked: `.env` is on the Write/Edit deny-list)*
3. Bump `check-invariants.ps1` docstring "12" → "13" to match CLAUDE.md (#3).

**🔧 Highest-leverage ENABLEMENT change (compounds across every future session):** Fix the stale `backend/REVIEW-2026-05-27.md` (#1). A committed review doc with no "resolved" banner is the worst kind of harness rot — every future Claude session that reads it will burn budget chasing already-fixed ghosts (C1/C2/M*/H3). One banner line prevents that on every run.

---

## Findings (ranked: severity, then impact)

### 1. [ENABLEMENT] — MEDIUM-HIGH · Stale backend review doc presents fixed bugs as live
- **Location:** `backend/REVIEW-2026-05-27.md`
- **Problem:** The doc lists C1 (crash), C2, M1/M2/M3, H3 as urgent open issues with no "resolved/superseded" banner — but all are fixed at HEAD (Tier 3 confirmed the fixed code + regression tests are present). The sibling `webapp/REVIEW_FINDINGS.md` *does* carry a self-correcting banner; the backend one's asymmetry is the trap.
- **Fix:** Add a top banner — `> ⚠️ RESOLVED in 1b64aef — historical record only` — or delete the file. Prefer a banner if it's kept for traceability.
- **Severity:** MEDIUM-HIGH · **Confidence:** Confirmed (Tier 3 grep confirmed no banner; fixed code located).

### 2. [CODE] — LOW · Dead `INTERCOM_ACCESS_TOKEN=` line in backend `.env`
- **Location:** `backend/.env:4`
- **Problem:** Empty `INTERCOM_ACCESS_TOKEN=` line (review H4, never actioned). Harmless at runtime — no `AppConfig` field reads it, `git log --all` confirms it was never committed — but it cognitively contradicts invariant #1 ("No Intercom Access Token anywhere").
- **Fix:** Operator deletes line 4. **Agent-blocked:** `.env` is on the Write/Edit deny-list, so this must be done by hand.
- **Severity:** LOW · **Confidence:** Confirmed.

### 3. [ENABLEMENT] — LOW · Invariant-count drift in hook docstring
- **Location:** `scripts/check-invariants.ps1:5`
- **Problem:** Docstring says "12 invariants"; root CLAUDE.md now lists 13. Enforcement logic (6 rules) is unaffected — purely a stale comment.
- **Fix:** Change `12` → `13` in the docstring.
- **Severity:** LOW · **Confidence:** Confirmed.

### 4. [ENABLEMENT] — LOW · qa command cwd friction + dead allow-list entry
- **Location:** qa-* command docs; `.claude/settings.json:38`
- **Problem:** qa-* docs use `cd backend` / `cd webapp` which must be pasted as one Bash call (agent cwd resets between calls), and the `cd` isn't allow-listed so may prompt. The `npm --prefix webapp run *` allow entry is dead — docs use `cd` instead, so the entry never matches. Cosmetic harness friction, not a correctness bug.
- **Fix:** Either switch qa docs to `npm --prefix webapp run …` (so the existing allow entry fires) or drop the dead entry and allow-list the `cd` form. Pick one and align docs + settings.
- **Severity:** LOW · **Confidence:** Confirmed (Severity-adjusted: Tier 1 MEDIUM → Tier 2/3 LOW).

### 5. [CODE] — LOW · Orphan attachment file on failed commit
- **Location:** `backend/app/services/attachments.py:62-63` (write) vs `:76-77` (commit)
- **Problem:** File is written to disk before the DB row commits. If the commit fails, a row-less file is orphaned; the GC sweep keys off DB rows so it's never collected. Self-heals on an identical re-upload (same sha256 path). Micro-leak, single-operator disk.
- **Fix:** Optional — wrap in try/except that unlinks the file on commit failure, or accept as-is given the threat model. Low priority.
- **Severity:** LOW · **Confidence:** Confirmed.

### 6. [CODE] — LOW · Sanctioned silent-failure / suppression cluster
- **Location:** `main.py:54/84/117` (poll+sweep loops), `ai/pipeline.py:358`, `extension/background.js:117`, `clients/openrouter.py:47-60`
- **Problem:** Broad/bare `except` in background loops, per-ticket `except Exception` labeling logic bugs as "ai error", empty `catch {}` in extension poll, and HTTP-date `Retry-After` ignored (numeric-only). Tier 3 verified auth errors still bubble to the popup and these are sanctioned by CLAUDE.md for loop resilience.
- **Fix:** None required. Optionally narrow the `ai/pipeline.py:358` catch so genuine logic bugs aren't masked as AI errors. Confirmed-as-is.
- **Severity:** LOW · **Confidence:** Confirmed.

### 7. [CODE] — LOW · ORM→schema `type: ignore` cluster & in-memory upload read
- **Location:** `backend/app/services/tickets.py:485-530` (`# type: ignore[arg-type]`); `attachments.py:64` (25 MB read into memory)
- **Problem:** Type-ignores on ORM→Literal copies hide nullability drift if a column's nullability changes; whole-file read sets a per-upload memory ceiling. Both standard/sized for a single operator.
- **Fix:** None required. If touched later, prefer explicit narrowing over `type: ignore`. Confirmed-as-is.
- **Severity:** LOW · **Confidence:** Confirmed.

### 8. [CODE] — INFO · Live `OPENROUTER_API_KEY` in plaintext `.env`
- **Location:** `backend/.env`
- **Problem:** A live `sk-or-v1-…` key sits in plaintext beside the dead token line. **Not a defect** — in threat model (single-operator, own key, own machine), correctly gitignored, never committed. Flagged only because the operator will be editing that file for finding #2.
- **Fix:** None. Awareness only: don't paste `.env` contents anywhere shared. (Key value was deliberately never echoed into any `.audit/` file.)
- **Severity:** INFO · **Confidence:** Verifier-noted (Tier 3 sweep).

---

## Dismissed candidates

Nothing silently vanished — each dismissal was spot-checked by Tier 3; the two most consequential (T1-002, T1-004) were independently re-confirmed safe.

| ID | What it claimed | Why dismissed |
|----|-----------------|---------------|
| T1-001 | Attachment path traversal via filename suffix | `Path.suffix` can never contain a path separator — no traversal possible. |
| T1-002 | Spoofed `content_type` bypasses nosniff (upload) | Forced `Content-Disposition: attachment` + `X-Content-Type-Options: nosniff` + raster allowlist; S1 fixed at HEAD. Re-confirmed by Tier 3. |
| T1-004 | renderable_type mapping (invariant #3) mismatched across packages | Decoded only once in `extension/intercom.js:41-43`; backend + webapp consume `is_admin`, not the raw code — consistent. Re-confirmed by Tier 3. |
| T1-012 | ember/ endpoint + workspace id disagree across docs/code/memory | Endpoints agree; `app_id` is per-operator config, not a constant to reconcile. |
| T1-013 | `backend/CLAUDE.md` references missing `.env.example` | `.env.example` exists and is tracked — false alarm. |
| T1-015 | `MAX_INGEST_TICKETS=500` needs a bump-skill like MAX_BULK_IDS | No cross-package coupling — correctly un-skilled. |
| T1-016 | Superseded Intercom-token phase doc could revive Access-Token path | Doc is loudly fenced as superseded + PreToolUse invariant hook backstops it. |

---

## Tier-by-tier audit trail
- `.audit/tier1-scan.md` — 16 candidates, full breadth, scope + skips recorded.
- `.audit/tier2-deepdive.md` — per-candidate root cause / blast radius / fix; 7 dismissed, 2 added.
- `.audit/tier3-verification.md` — independent re-confirmation of every surviving finding + remediation-merge proof + dismissal spot-checks.
