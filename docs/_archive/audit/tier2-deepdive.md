# Tier 2 — Deep Dive (audit funnel)

**Repo:** intercom-ticket-management (single-operator LOCAL tool — judge severity in that threat model)
**Date:** 2026-05-27
**Tier:** 2 of 3 — confirm/dismiss Tier 1 candidates, establish root cause + blast radius, write concrete (un-applied) fixes.
**Input:** `.audit/tier1-scan.md` (T1-001..T1-016 + negatives).

> **Read-only pass.** No code/config changed. The only write is this file.

## Headline context (changes everything below)

Git HEAD `1b64aef` already merged a *backend review remediation* batch (C1/C2/M1/M2/M3/L2/L3/L4/H3) and the webapp `fix/webapp-review-batch` (C1/C2/C3/F1/S1/S3/A1). **The two committed REVIEW docs are now substantially STALE** — most of the issues they describe are already fixed in `main`. Verified in code (not trusting the docs):

| Review finding | Status in `main` (verified) |
|---|---|
| C1 illegal `resolved_source='resolved'` crash | **FIXED** — `tickets.py:185-187` maps verdict→`ai_resolved`/`non_actionable`; `models.py:525` constraint + `schemas.py:56` + `webapp/src/types/api.ts:20` all carry `ai_resolved` (3-package C1 fix landed). |
| C2 reopen un-stuck by next sync | **FIXED** — `tickets.py:169` `resolution_cleared_at` guard. |
| M1 unbounded ingest list | **FIXED** — `routers/tickets.py:68` caps at `MAX_INGEST_TICKETS=500` → 413. |
| M2 blocking file/PIL I/O | **FIXED** — `attachments.py:63` + `:141` now `anyio.to_thread.run_sync`. |
| M3 `set_override` orphan | **FIXED** — `tickets.py:107` 404s on missing ticket. |
| H3 CVE deps | **FIXED** — fastapi 0.135.4, pillow 12.2.0, python-multipart 0.0.29, pytest 8.4.2. |
| S1 inline mime XSS | **FIXED** — `routers/attachments.py:32,107,113` allowlist + forced `attachment` disposition + nosniff. |
| F1 CRLF format gate | **FIXED** — `.gitattributes` (`* text=auto eol=lf`) + prettier `endOfLine:auto`. |
| H4 dead `INTERCOM_ACCESS_TOKEN=` line in `.env` | **NOT done** — still present (`backend/.env:4`). See T2-NEW-01. |

This makes **T1-005 the most consequential ENABLEMENT item**: the stale docs are a trap for future sessions.

---

## CONFIRMED ISSUES

### T1-005 — [ENABLEMENT] Stale review docs in package roots will mislead future sessions — **PROMOTED to MEDIUM-HIGH (enablement)**
**Files:** `backend/REVIEW-2026-05-27.md`, `webapp/REVIEW_FINDINGS.md`.
**Root cause + blast radius:** Both docs were written *before* the remediation that is now merged at HEAD. They present already-fixed bugs (C1 crash, C2 reopen, M1/M2/M3, S1, F1, H3) as **open, urgent, "fix this now"** with confident severity language and "recommended order of action." A future Claude reading `backend/REVIEW-2026-05-27.md` will "discover" the C1 crash, attempt to re-fix an already-fixed path, and burn a session chasing a ghost — or worse, re-introduce churn on a working contract. The webapp doc partially self-corrects (top banner lists fixed items) but the backend doc has **no such banner** and reads as fully live. Harness/enablement errors compound across sessions, so a stale "authoritative findings" doc at a package root is high-leverage rot.
**Recommended fix (Tier 3 / human):**
- Either delete both docs, or prepend a loud `> RESOLVED at <commit> — historical record only` banner and strike the fixed items (mirror the webapp doc's existing banner; backend doc has none).
- Move whichever survive into `docs/` (per Tier 1's instinct) so package roots stop reading like live action lists. The remediation plan already lives at `docs/superpowers/plans/2026-05-27-backend-review-remediation.md` — point the docs at it.
- **Cross-check before deleting:** the backend doc lists three *still-open* items not in the remediation merge — L1 (content-signature has no hash), C2-residual hardening, and **H4** (see T2-NEW-01). Don't lose those when pruning.
**Disposition: Promoted** (Tier 1 guessed MEDIUM; the staleness is confirmed and actively misleading → enablement priority).

### T2-NEW-01 — [CODE/ENABLEMENT] Dead `INTERCOM_ACCESS_TOKEN=` line in `backend/.env` contradicts Invariant #1 — **LOW** (latent trap)
**File:** `backend/.env:4` (`INTERCOM_ACCESS_TOKEN=`, empty).
**Root cause + blast radius:** Leftover from the pre-pivot Access-Token design (Phase 2, now superseded). `.env` is gitignored + untracked (verified — no history leak), and the value is empty, so there is **no runtime effect** (`AppConfig` has `extra="ignore"` and no such field). The risk is purely cognitive: invariant #1 says "No Intercom Access Token anywhere," and a future operator/Claude editing `.env` sees a token slot and may assume a token path exists. The PreToolUse hook Rule 1 greps for `INTERCOM_ACCESS_TOKEN` but **only under `backend/app/`** and `.env` is on the never-commit list, so the hook won't catch or flag it.
**Recommended fix:** delete `backend/.env:4`. (Can't be done by an agent — `.env` is on the Write/Edit deny-list; hand to the operator.) This is review-doc H4's second half, never actioned.
**Disposition: Confirmed-as-is** (genuinely present, genuinely harmless at runtime, genuinely a doc/clarity trap). New, low.

### T1-014 — [ENABLEMENT] qa-* command cwd handling vs allow-list — **DOWNGRADED to LOW, confirmed real-but-minor**
**Files:** `.claude/commands/qa-backend.md`, `qa-webapp.md`, `qa-all.md`; `.claude/settings.json:26-46`.
**Root cause + blast radius:** The qa command bodies are PowerShell blocks that start with `cd backend` / `cd webapp` on their own line, then run `ruff check app tests` / `npm run lint` etc. against package-relative paths. Two real frictions, both minor:
1. **cwd reset between Bash calls** (per env note) means the `cd` and the gate command must run in *one* Bash invocation (`cd backend; ruff check app tests`) — if an agent splits them, ruff runs from repo root and `app tests` won't resolve. The command docs present them as a multi-line block, which an agent *should* paste as one call, but it's not stated explicitly.
2. **The `cd` is not allow-listed**, so a compound `cd backend; ruff ...` may trigger a permission prompt on first use even though `ruff check*` is allowed. The allow-list mixes a cwd-relative form (`npm run lint*`) and an explicit `npm --prefix webapp run *` form — the latter is never used by the qa docs (which use `cd webapp`), so it's dead allow-list surface.
**Not a correctness bug** — at worst a prompt or a one-off "run from the right dir" stumble. No gate is wrong; outputs are trustworthy.
**Recommended fix (optional polish):**
- In each qa-* doc, add a one-liner: "run the block as a single shell invocation; bash cwd resets between calls."
- Either drop the unused `npm --prefix webapp run *` allow entry, or rewrite the qa-webapp/qa-all bodies to use `npm --prefix webapp run lint` (no `cd`, matches the allow entry, no prompt). Pick one form repo-wide.
**Disposition: Downgraded** (MEDIUM→LOW). Real but cosmetic in the local single-operator harness.

### T2-NEW-02 — [ENABLEMENT] check-invariants hook header says "12 invariants"; CLAUDE.md now has 13 — **LOW** (doc drift)
**File:** `scripts/check-invariants.ps1:5-6` ("the 12 cross-package invariants in CLAUDE.md").
**Root cause + blast radius:** Root CLAUDE.md now enumerates **13** invariants (playbooks = #13, added after the hook was written). The hook enforces only 6 grep rules regardless, so enforcement is unaffected — purely a stale comment. Harmless but it's the kind of off-by-one a future reader trips on when reconciling "which invariants are auto-checked."
**Recommended fix:** s/12/13/ in the docstring (or make it count-agnostic: "the cross-package invariants in CLAUDE.md"). Note the hook deliberately covers only a *subset* (6 of 13) — that's fine and worth stating.
**Disposition: Confirmed-as-is** (trivial doc drift, new).

### T1-011 — [CODE] Orphan attachment file (written pre-insert) is never GC'd — **LOW, confirmed-as-is**
**File:** `backend/app/services/attachments.py:55-78` (write before insert) + `:151-188` (sweep).
**Root cause + blast radius:** `upload_attachment` writes the file (`:62-63`) *before* `session.add` + `commit` (`:76-77`), by documented design. If the commit raises (disk full, FK, etc.), the bytes stay on disk with **no DB row**. `sweep_attachments` iterates only `NoteAttachment` rows whose `deleted_at` is past the cutoff — a file with *no row* is invisible to it forever → permanent (tiny) disk leak. **Strongly mitigated:** content-addressed naming means a later upload of the *same* bytes reuses the orphan (`if not abs_path.exists()`), so it self-heals on retry and never multiplies. For a single operator on a local disk, blast radius ≈ a few stray KB on a rare commit failure.
**Recommended fix (optional):** none needed for the threat model. If ever desired, an orphan-file pass in the daily sweep (walk `attachments_dir`, drop files whose sha has zero rows) closes it — but that's gold-plating here.
**Disposition: Confirmed-as-is** (real, negligible, by-design tradeoff documented in the docstring).

### T1-006 — [CODE] Whole-file read into memory on upload (25 MB cap) — **LOW, confirmed-as-is**
**File:** `backend/app/routers/attachments.py:64`.
**Root cause + blast radius:** `await file.read(max_bytes+1)` buffers the entire file (≤25 MB+1) in memory; no streaming to disk. With unbounded concurrent uploads that's a memory ceiling, but there is exactly one operator firing one upload at a time over localhost. The `+1`-byte trick correctly rejects oversize without holding more than the cap. Fine.
**Disposition: Confirmed-as-is** (sized for the threat model).

### T1-007 — [CODE] HTTP-date `Retry-After` ignored — **LOW, confirmed-as-is**
**File:** `backend/app/clients/openrouter.py:47-60`.
**Root cause + blast radius:** `_parse_retry_after` parses only numeric-seconds; an HTTP-date form returns `None` → falls back to computed exponential+jitter backoff. OpenRouter sends numeric `Retry-After` (also noted as review L5). Worst case on a hypothetical date header: slightly over-aggressive retry against one external API. No correctness impact.
**Disposition: Confirmed-as-is** (documented, matches review L5).

### T1-003 / T1-008 / T1-009 / T1-010 — sanctioned suppressions / catch-alls — **LOW, pass-through**
- **T1-003** (`tickets.py:505-529` `type: ignore[arg-type]` cluster): all on ORM→pydantic narrowing where the column is `str | None` / JSON and the schema field is a `Literal`/typed model — the standard "mypy can't prove the DB value is in the Literal set" pattern. No nullability drift found; the `state`/`resolved_source`/`verdict`/`chip` values are all constrained at the DB (CheckConstraints) or computed locally. Confirmed-as-is.
- **T1-008 / T1-009 / T1-010**: broad `except Exception` in sweep loops + per-ticket pipeline fallback + extension badge-refresh `catch {}` are all explicitly sanctioned (backend CLAUDE.md §3 "Background tasks catch broad Exception on purpose"; extension doctrine "degrade silently for background work"). Spot-checked: auth errors still bubble as `IntercomSessionError` in `intercom.js` (not eaten by the badge catch). No NEW silent-failure crept in. Confirmed-as-is.

---

## DISMISSED CANDIDATES

### T1-001 — Attachment path-traversal via client filename suffix — **DISMISSED**
`_extension_for` returns `Path(filename).suffix`. Verified empirically (both POSIX and Windows pathlib): `Path.suffix` is *always* the segment after the last dot of the **final path component** and can never contain `/` or `\` — `Path("../../etc/passwd").suffix == ''`, `Path("a\\b\\c").suffix == ''`. The suffix is appended to a server-derived `{sha256[:2]}/{sha256}` prefix, so the write stays inside `attachments_dir`. Worst case = a file with a goofy extension (`.<svg>`, `.%2f`); the ≤16-char cap bounds even that. The only uploader is the operator. Matches the backend review's "Path traversal: safe" verified-clean note. **No issue.**

### T1-002 — Spoofed mime bypasses inline-render protection — **DISMISSED**
`/attachments/{id}/raw` serves `content_disposition_type="attachment"` for **any** mime not in `_INLINE_SAFE_MIMES` (raster images only: png/jpeg/gif/webp/bmp), plus `X-Content-Type-Options: nosniff`. A spoofed `text/html`/`image/svg+xml` is force-downloaded, not rendered in-origin; a spoofed `image/png` containing markup won't execute under nosniff + image media-type. This is webapp-review S1, **fixed in code at HEAD** (router lines 32/107/113). Self-XSS surface for the lone operator is closed. **No issue.**

### T1-004 — renderable_type 1/12/2/24/3 mapping consistency across 3 packages — **DISMISSED (verified consistent)**
The numeric mapping is decoded **only** in `extension/intercom.js` (`INBOUND={1,12}`, `ADMIN_REPLY={2,24}`, `INTERNAL_NOTE=3`, lines 41-43) inside `normalizeConversation`, which emits the already-resolved `is_admin` boolean into `parts[]` and routes type-3 into `internal_notes[]` (lines 249-294). Backend `schemas.py:294-308` (`ConversationPartSchema.is_admin`, `HydratedTicket`) and `webapp/.../TicketConversation.vue` (`p.is_admin ? 'admin':'customer'`) consume the boolean — they only *mention* `renderable_type` in comments, never re-decode it. So invariant #3 is single-sourced (correct) and the cross-package "spread" is the `is_admin`/`parts`/`internal_notes` shape, which is consistent end-to-end. **No drift.** (The `renderable-type-change` skill still correctly forces a live-payload check if anyone edits the numeric set.)

### T1-012 — Intercom endpoint base agreement (docs/code/memory) — **DISMISSED (verified consistent)**
`intercom.js:19` `INTERCOM_BASE='https://app.intercom.com'`; manifest host permission `https://app.intercom.com/*`; extension CLAUDE.md cites `/ember/inbox/conversations/{list,id}`; MEMORY.md cites workspace `j3dxf22l` as an *example* `app_id` (stored per-operator in `chrome.storage.local.intercomAppId`, not hardcoded). All agree: base host + `ember/` path are constant; the workspace id is operator-supplied. No contradiction.

### T1-013 — Missing `.env.example` — **DISMISSED (false alarm)**
`backend/.env.example` **exists and is git-tracked** (`git ls-files` confirms `backend/.env.example`). The backend CLAUDE.md pointer is correct. *Minor note (not promoted):* the example omits the ATTACHMENT_* / AI_RESOLVE_* keys that CLAUDE.md's Configuration section documents — but all have sane defaults in `AppConfig`, so it's a completeness nit, not a broken pointer.

### T1-015 — `MAX_INGEST_TICKETS=500` not covered by a skill — **DISMISSED (correct as-is)**
`MAX_INGEST_TICKETS` is a pure backend memory/fan-out bound enforced at `routers/tickets.py:68` (→413). Unlike `MAX_BULK_IDS` (which the webapp pre-flight-warns on, hence the `bump-max-bulk-ids` skill), the ingest cap is **not** mirrored in any client contract: the extension fetches `count≈60` per state and the webapp never bulk-ingests, so neither needs to know the value. No cross-package coupling → no skill needed. Correct that it's un-skilled.

### T1-016 — Superseded phase doc could mislead — **DISMISSED (loudly marked dead)**
`docs/tasks/phase-02-intercom-superseded.md` opens with a bold `> Entire phase superseded.` banner explaining the extension pivot, and every task is prefixed `⊘` with a `Status: superseded` line. No realistic risk a future Claude reimplements the Access-Token path from it — and the PreToolUse hook Rule 1 would block any commit reintroducing `api.intercom.io`/`INTERCOM_ACCESS_TOKEN` under `backend/app/` as a backstop. Adequately fenced.

---

## Tier 1 negative findings — re-verification

Cheap re-checks done; all hold:
- **CORS** pinned (5173 + `chrome-extension://[a-z]{32}`, `allow_credentials=False`) — confirmed by both review docs + Tier 1; not re-opened. CLEAN.
- **No v-html/innerHTML/eval; no raw SQL; no hardcoded secrets** — trusted (Tier 1 + both reviews agree; webapp review explicitly re-verified the XSS double-escape). CLEAN.
- **Resolution XOR + Settings singleton CheckConstraints** — confirmed present (`models.py`); note the XOR `resolved_source` set was correctly *extended* to include `ai_resolved` (the C1 fix) and the constraint still holds. CLEAN.
- **Harness deny-list + PreToolUse hook + Stop hook** — re-read `check-invariants.ps1`: exits 0 on empty/parse-error/non-commit, only blocks `git commit`, 6 grep rules robust. STRONG (one stale comment, T2-NEW-02).

---

## Summary for Tier 3

**Confirmed-issue count by final severity:**
- HIGH: 0
- MEDIUM-HIGH (enablement): 1 — **T1-005** (stale review docs).
- LOW: 5 — T2-NEW-01 (dead .env token line), T1-014 (qa cwd/allow-list polish), T2-NEW-02 (hook "12" vs 13), T1-011 (orphan-file leak), and the cluster T1-003/006/007/008/009/010 (sanctioned, pass-through).

**No CRITICAL or genuine HIGH code bugs remain** — the ones Tier 1 worried about (path traversal, mime XSS, the AI-resolve crash) are either provably safe or **already remediated at HEAD** (`1b64aef`).

**Promoted:** T1-005 (MEDIUM→MEDIUM-HIGH enablement — stale docs actively mislead future sessions; the backend doc has no "resolved" banner).
**Downgraded:** T1-014 (MEDIUM→LOW — real cwd/allow-list friction, but cosmetic, not a correctness bug).
**Dismissed:** T1-001 (suffix can't traverse — proven), T1-002 (forced-download+nosniff+allowlist, S1 fixed), T1-004 (renderable_type single-sourced + consistent), T1-012 (endpoints agree), T1-013 (.env.example exists), T1-015 (no cross-package coupling), T1-016 (loudly fenced).
**New:** T2-NEW-01 (LOW — `INTERCOM_ACCESS_TOKEN=` still in `.env`; review H4 never actioned), T2-NEW-02 (LOW — hook docstring "12" should be "13").

**One-line disposition of each candidate:**
- T1-001 path traversal → **DISMISSED** (`Path.suffix` cannot contain a separator; proven empirically).
- T1-002 spoofed mime → **DISMISSED** (forced `attachment` + nosniff + raster allowlist; S1 fixed at HEAD).
- T1-003 type-ignore cluster → **Confirmed-as-is LOW** (standard ORM→Literal narrowing, no drift).
- T1-004 renderable_type spread → **DISMISSED** (decoded only in extension; backend/webapp consume `is_admin`; consistent).
- T1-005 stale review docs → **PROMOTED MEDIUM-HIGH** (backend doc reads as live; misleads future sessions).
- T1-006 whole-file read → **Confirmed-as-is LOW** (25 MB cap, single operator).
- T1-007 Retry-After date → **Confirmed-as-is LOW** (numeric-only; OpenRouter sends numeric).
- T1-008 sweep catch-all → **Confirmed-as-is LOW** (sanctioned; no new swallow).
- T1-009 pipeline fallback catch → **Confirmed-as-is LOW** (sanctioned per-ticket fallback).
- T1-010 extension badge catch → **Confirmed-as-is LOW** (auth errors still bubble; verified).
- T1-011 orphan attachment file → **Confirmed-as-is LOW** (real micro-leak, self-heals on identical re-upload).
- T1-012 Intercom endpoint base → **DISMISSED** (docs/code/memory agree; `app_id` is per-operator).
- T1-013 missing .env.example → **DISMISSED** (exists + tracked; minor key-completeness nit only).
- T1-014 qa cwd/allow-list → **DOWNGRADED LOW** (paste-as-one-call + drop dead `--prefix` allow entry).
- T1-015 MAX_INGEST_TICKETS un-skilled → **DISMISSED** (no client contract coupling; correct un-skilled).
- T1-016 superseded phase doc → **DISMISSED** (loudly marked dead + hook backstop).
- T2-NEW-01 dead .env token line → **NEW LOW** (delete `backend/.env:4`; review H4 residual).
- T2-NEW-02 hook "12 invariants" → **NEW LOW** (should read 13; enforcement unaffected).
