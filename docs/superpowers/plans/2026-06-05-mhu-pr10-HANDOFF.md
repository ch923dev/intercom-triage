# MHU PR #10 — Resume / Kickoff Handoff

**Date:** 2026-06-05 · **Branch:** `feat/mhu-auth` (PR #10, OPEN) · **Status:** 8/18 tasks done, paused for review.

This is the resume brief for the next session continuing the MHU PR #10 build. Read this, then the plan, then continue.

---

## 0. TL;DR

You are continuing one combined PR (#10, `feat/mhu-auth`) that adds, on top of the already-built hosted-auth core: **(1) two security fixes** from a code review, **(2) Phase 2 attribution** (who resolved / who recategorized), **(3) Phase 3 assignment + My-Queue**. Execution uses the **subagent-driven-development** workflow (implementer subagent → spec-compliance review → code-quality review, per task). **8 tasks are done and reviewed**; resume at **Task 8b**.

- **Plan (source of truth, task-by-task with code):** `docs/superpowers/plans/2026-06-05-mhu-pr10-security-attribution-assignment.md`
- **Design spec:** `docs/superpowers/specs/2026-06-05-multi-hosted-user-design.md`
- **Roadmap/review context:** `~/.claude/plans/do-an-indepth-review-twinkling-bee.md` (the prior session's review + roadmap)

---

## 1. Where to work (CRITICAL)

- **Worktree:** `F:\Claude Projects\niche\intercom-ticket-management\.claude\worktrees\mhu-auth` — branch `feat/mhu-auth`. ALL edits/tests/commits happen here. (The main repo dir is on a different branch — do NOT edit there.)
- **Backend has NO venv in the worktree.** Run all backend Python tooling via the **MAIN repo venv** by absolute path, from `<worktree>\backend`:
  - tests: `& "F:\Claude Projects\niche\intercom-ticket-management\backend\.venv\Scripts\python.exe" -m pytest -q <args>`
  - ruff: `& "F:\Claude Projects\niche\intercom-ticket-management\backend\.venv\Scripts\ruff.exe" check app tests`
  - format check: `& "...\backend\.venv\Scripts\ruff.exe" format --check app tests`
  - mypy: `& "...\backend\.venv\Scripts\python.exe" -m mypy app`
  - schema smoke: `& "...\backend\.venv\Scripts\python.exe" -m app.models`
  (cwd = `<worktree>\backend`, so `import app` resolves to the worktree source.)
- **Webapp** uses the worktree's own `node_modules` (present): run `npm` from `<worktree>\webapp` as written.
- **PowerShell** on Windows; use `&` to invoke a quoted exe path.

## 2. Git hygiene (CRITICAL)

- Plain `git add <specific files>` + `git commit` ONLY. **NEVER** `git add -A` / `git add .` / `git add -u`.
- **NEVER** rebase / amend / reset (policy-denied via Bash; also history-rewrite is denied).
- **Do NOT touch or stage `backend/.env.example`** — it has an uncommitted local edit with **real dev secrets**. Leave it.
- Commits stay LOCAL. Do not `git push` unless the user asks.

## 3. Known gotcha — one expected test failure

`backend/tests/test_auth_config.py::test_auth_defaults` FAILS **only in this worktree** because the local `backend/.env` sets `SESSION_COOKIE_SECURE=false` (plain-http dev) and the test asserts the *default* `True`. It is an environment artifact — passes on a clean clone / CI. **Do not "fix" it.** When running the broad suite, deselect it:
`pytest -q --deselect tests/test_auth_config.py::test_auth_defaults`.

---

## 4. What's DONE (8 commits, all reviewed + Approved, LOCAL/unpushed)

On top of prior PR #10 head `63ca4c7`:

| SHA | Task | What |
|---|---|---|
| `69b8309` | 1 | rate-limit bucket eviction (bounds memory) |
| `222303d` | 2 | login limiter split per-IP AND per-email |
| `370a9ce` | 3 | `sessions.prev_refresh_token_hash` + migration **0022** |
| `f3e9ff5` | 4 | refresh **reuse-detection** → revokes session chain |
| `d344f82` | 5 | seed `User(id=1)` in `tests/conftest.py` (FK target) |
| `3d0fad2` | 6 | migration **0023**: `tickets.resolved_by`, `overrides.acted_by` (batch_alter_table named FKs — preserves all CHECK constraints, verified) |
| `1e22220` | 7 | `UserRef` schema + 4 board fields on `TicketSchema` (NOT HydratedTicket) |
| `71cb4ed` | 8 | thread `resolved_by`/`acted_by` through resolve + override (single+bulk); `clear_resolution` nulls `resolved_by`; routers inject `CurrentUser`; AI/system paths stay NULL |

Review the set: `git log --oneline --stat 63ca4c7..HEAD`. Suite: **493 passed** (+ the 1 known env failure above).

---

## 5. RESUME HERE — remaining tasks

Follow the plan file task-by-task. Use subagent-driven-development (§7 below). Migration chain continues **0024** next.

- **Task 8b** *(added by decision)* — stamp `resolved_by` on **manual mark-non-actionable** (single + bulk). Christian decided YES: a manual non-actionable IS an operator resolve, so attribute it like manual resolve. Also add a bulk-path attribution test (reviewer's Task-8 minor note). Full steps in the plan.
- **Task 9** — `get_tickets` user-join: populate the `resolved_by`/`acted_by`/`assigned_to` `UserRef` fields on the board response. **These fields are declared (Task 7) but still return `null` until this task.**
- **Task 10** — webapp: `UserRef` type + "resolved by X" display in the flyout (`TicketResolution.vue`).
- **Tasks 11–15** — Phase 3 assignment: migration **0024** (`tickets.assigned_to` + `assigned_at`), assign + bulk_assign endpoints, trim `GET /users` to id+name (review Finding #4), webapp `myTickets` getter + `myQueueOnly` toggle + `AssigneePicker.vue` + card tag + Topbar chip.
- **Tasks 16–18** — full backend + webapp quality gates; contract/charter docs (spec v2.0, plan §19, tasks T167–T170, CLAUDE.md scope pivot + 5 MHU invariants); end-to-end manual verification.

**Don't forget in Task 17 (docs):** document the **double-refresh / two-tab revoke tradeoff** (inherent to refresh rotation + reuse-detection) as a code comment in `rotate_session` + a note in plan §19 / the refresh invariant. Reviewer flagged it on Task 4; acceptable for small-team scope, but must be written down.

---

## 6. Decisions already made (do not re-litigate)

- **One combined PR (#10)** carries security fixes + attribution + assignment. (User confirmed "everything in PR #10".)
- **Manual non-actionable → stamp `resolved_by`** (Task 8b). YES.
- **Settings stays a shared team-wide singleton** — no per-user prefs table. Personal view prefs stay in per-browser `localStorage` (`tweaks`, `savedViews`).
- **pgvector / semantic-layer-on-Postgres = deferred** (separate later design). Hosted v1 runs with embeddings/clustering OFF; `/health` flags it.
- **Per-user follow-ups/notes = Phase 4, OUT of this PR.** (Note: design §5.2 wrongly says `note_entries.user_id` "already exists" — it does NOT; Phase 4 must ADD it.)
- **Branch base confirmed:** PR #10 → `main`; merging it brings the extension removal into main too (PR #9 never landed on main). Confirmed acceptable.

---

## 7. Workflow to follow (subagent-driven-development)

For EACH remaining task:
1. Dispatch an **implementer** subagent (general-purpose, model sonnet for backend/integration). Paste the FULL task text from the plan + the §1/§2/§3 environment rules above (subagents have fresh context — they don't know any of this unless you tell them). Implementer does TDD, runs scoped tests + gates, commits scoped, self-reviews, reports status + new SHA + prior SHA.
2. Dispatch a **spec-compliance review** subagent (read the diff `git diff <prior> <new>`, verify against the task spec — do NOT trust the report).
3. Dispatch a **code-quality review** subagent (only after spec ✅). For migration tasks, MAKE IT VERIFY constraint/index preservation via a fresh `alembic upgrade head` + `sqlite_master` DDL dump (Task 6's batch rebuild precedent).
4. Fix loops until both reviews pass, then next task. Don't pause between tasks except for a genuine blocker or decision.

Models: sonnet for backend/integration + reviews; haiku acceptable only for trivial mechanical webapp/type edits (but the worktree-venv command complexity has made sonnet the safer default).

## 8. Quality gates (before the PR is pushed)

- Backend (from `<worktree>\backend`, main venv): `ruff check app tests` && `ruff format --check app tests` && `python -m mypy app` && `pytest -q --deselect tests/test_auth_config.py::test_auth_defaults`
- Webapp (from `<worktree>\webapp`): `npm run lint && npm run format:check && npm run typecheck && npm test && npm run build`

## 9. Invariants to keep (repo CLAUDE.md)

- New attribution/assignment fields are **board-state only** — on `TicketSchema`/`Override`, **never on `HydratedTicket`** (cross-package invariant #2).
- Naive-UTC in DB (`naive_utcnow()`); `Z`-suffixed on the wire (`UTCDatetime`).
- Services own commits; routers stay thin. `MAX_BULK_IDS=200` honored by bulk_assign.
- Migrations forward-only, strictly chained (next = 0024); only this branch adds migrations.
