# Docs Cleanup & Interactive Hub — Design Record

> **Status:** implemented 2026-06-05 (on `main`). Author: Christian (+ Claude).
> Scope: documentation reorganization only — **no code, no behavior change**.

---

## 1. Context

The repo's documentation had accreted faster than it was curated. The root held
the three "contract source of truth" files — `spec.md` (570 lines), `plan.md`
(732), `tasks.md` (320) — mixed in with `CLAUDE.md`, `README.md`, `SECURITY.md`.
Under `docs/` sat the canonical handbook (`PROJECT.md`), the feature catalog
(`FEATURES.md`), `principles.md`, **two dead redirect stubs**
(`docs/architecture.md`, `docs/ROADMAP.md` — 8 and 6 lines pointing at
`PROJECT.md` + `_archive/`), the design archive (`superpowers/`), and the history
pile (`_archive/`).

There was no single navigable entry point. The goal: a **simplified, interactive
front door** that routes by intent, with the heavy reference material relocated
out of the repo root and grouped semantically — without losing any detail.

### 1.1 Base (where this was done)

This work was planned from a stale `design/hosted-multi-user` branch (local `main`
at `a11d667`, **before PR #8**). PR #8 — "backend-direct Intercom ingestion via
Access Token" — had already landed on `origin/main` (`50c98fd`) and rewritten the
exact files a docs cleanup touches (`CLAUDE.md`, `PROJECT.md`, `FEATURES.md`,
`spec/plan/tasks`, the READMEs). Cleaning the stale tree would have reorganized
obsolete docs and conflicted with PR #8 on merge.

**Resolution (per the owner's instruction):** fast-forward local `main` to
`origin/main` (it was 0 ahead / 2 behind — a clean FF), then perform the cleanup
directly on `main`. Unrelated working-tree WIP (intentional hook deletions,
`settings.json`/`.gitignore`/`openrouter.py` edits, scratch files) was stashed
first so the cleanup is a clean docs-only change. (A mid-session branch switch by a
parallel process had earlier landed a stray commit on `main`; it was reverted and
`main` restored to `a11d667` before the FF — hence the deliberate, stepwise base
handling here.)

---

## 2. Goals & non-goals

**Goals**

1. Relocate the contract trio (`spec.md`, `plan.md`, `tasks.md`) out of the repo
   root into `docs/contract/`, **verbatim** (history preserved via `git mv`).
2. Add a single **interactive Markdown hub** (`docs/README.md`) that routes by
   intent and renders natively on GitHub — zero build tooling.
3. Delete the two dead redirect stubs (`docs/architecture.md`, `docs/ROADMAP.md`);
   fold their navigation value into the hub.
4. Update every **live** reference to the moved/deleted files so nothing breaks.
5. Keep the root `README.md` as the repo quickstart, with a pointer to the hub.

**Non-goals**

- No content rewriting of `spec.md`/`plan.md`/`tasks.md` — moved as-is. They
  remain the contract source of truth; only their location changes.
- No reshuffling of `docs/_archive/**` or `docs/superpowers/**` (frozen history).
- No build tooling — no MkDocs/Docusaurus/wiki/HTML site (charter: no build step).
- No code, schema, API, or behavior change.

---

## 3. Result — the target tree (layout L1, "minimal-move")

```
intercom-ticket-management/
├── README.md            quickstart + a "📚 Docs → docs/" pointer
├── CLAUDE.md            (path refs updated)
├── SECURITY.md
└── docs/
    ├── README.md        NEW interactive hub (the front door)
    ├── contract/
    │   ├── spec.md      moved verbatim from root (git mv)
    │   ├── plan.md      moved verbatim from root (git mv)
    │   └── tasks.md     moved verbatim from root (git mv)
    ├── PROJECT.md  FEATURES.md  principles.md   (stay; path refs updated)
    ├── superpowers/  _archive/                  (untouched)
    └── (architecture.md, ROADMAP.md deleted — dead redirect stubs)
```

Net: **3 files moved, 2 deleted, 1 created**, plus reference edits.

L1 was chosen over flat-in-`docs/` (crowds the root) and a full reshelf into
`reference/` + `design/` (moves ~7 files, biggest ref-rewrite) — same outcome,
least breakage.

---

## 4. The hub — `docs/README.md`

"Interactive" = navigable + scannable in plain Markdown, not a generated site:

- **Intent-routed nav** — an "I want to…" table mapping a reader goal to the one
  doc that answers it.
- **Mermaid diagram** of the (post-PR-#8) architecture / data flow.
- **Collapsible `<details>`** blocks for the data-model, API-surface, and
  invariants references — present but folded so the landing stays one screen.
- A **full documentation map** table.
- **Boundary rule preserved:** the hub *links*, it never duplicates. Every fact
  keeps one home.

---

## 5. Reference rewrites

Every **live** path reference to the moved/deleted files was repointed:

- `spec.md`/`plan.md`/`tasks.md` → `docs/contract/…` across: root `CLAUDE.md`,
  `backend/CLAUDE.md`, `webapp/CLAUDE.md`, root `README.md`, `backend/README.md`,
  `docs/PROJECT.md`, `docs/FEATURES.md`, `.claude/skills/bump-max-bulk-ids/SKILL.md`
  (with the correct relative prefix per file location).
- Inside the moved files, root-relative Markdown links `](docs/…)` → `](../…)`
  (concentrated in `tasks.md`'s phase index); deleted-stub prose `docs/ROADMAP.md`
  → `docs/_archive/ROADMAP.md`.
- The repo-map ASCII trees in root `README.md` + `CLAUDE.md` were restructured to
  show `docs/` (hub + `contract/`) instead of root `spec/plan/tasks`.
- **Intentionally skipped:** `docs/_archive/**` and `docs/superpowers/**` — dated,
  frozen records. The docstring-convention shorthand `Reference: plan.md §X,
  tasks.md TXXX` in `backend/`/`webapp/` `CLAUDE.md` was also left as-is (a code
  comment convention, not a navigable link; migrating it would mean editing code
  docstrings repo-wide — out of scope).

---

## 6. Validation

- `git grep` shows no live root-path `spec/plan/tasks` references outside
  `_archive`/`superpowers`.
- A link-check resolved every relative link in the moved files and the hub.
- `git mv` preserved history (`git log --follow`).
- The commit diff touches **only** docs (`*.md` + the moved paths) — zero non-doc
  files. The stashed WIP (incl. the intentional hook deletions) and the untracked
  scratch files (`canvas.json*`) were kept out of the commit.

---

## 7. Risks & open points

- **Hook deletions resurface later:** the owner's intentional removal of
  `scripts/check-invariants.ps1` + `stop-reflection.ps1` + the `settings.json`
  hooks block was stashed (not part of this docs change). `origin/main` still
  carries (and PR #8 updated) `check-invariants.ps1`, so reconciling that deletion
  is a separate decision.
- **Parallel sessions:** this repo has no cross-session git lock; a stray branch
  switch already occurred once this session. Per root `CLAUDE.md`, concurrent work
  should use isolated worktrees.

---

## 8. Charter / invariant impact

**None.** Documentation-only: no build tooling (Markdown hub), no code, no schema,
no API change, no new dependency. The "one fact, one home" boundary rule is
preserved — the hub links rather than duplicates. The 14 cross-package invariants
are untouched.
