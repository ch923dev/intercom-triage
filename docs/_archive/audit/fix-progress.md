# Fix Progress — from .audit/FINAL.md

Status legend: Pending · Fixed-awaiting-review · Merged · Dismissed-with-reason · Deferred-to-human

| Finding | Sev | Tag | Batch | Status |
|---------|-----|-----|-------|--------|
| #1 stale backend review doc | MED-HIGH | ENABLEMENT | Batch 1 — stale-review-doc | Merged (bf1ed49, banner approach) |
| #3 invariant-count docstring 12→13 | LOW | ENABLEMENT | Batch 2 — invariant-count-docstring | Merged (8936178) |
| #4 qa command scoping + dead allow-list | LOW | ENABLEMENT | Batch 3 — qa-command-scoping | Merged (c90e81f, approach (a) npm --prefix) |
| #5 orphan attachment file on failed commit | LOW | CODE | Batch 4 — attachment-orphan-cleanup | Merged (f0fa441) — operator chose to fix despite by-design docstring; unlink fresh file on commit failure + 2 regression tests; qa-backend green (249) |
| #2 dead INTERCOM_ACCESS_TOKEN line in .env | LOW | CODE | — | Deferred-to-human (.env on Write/Edit deny-list) |
| #8 live OPENROUTER_API_KEY in .env | INFO | CODE | — | Deferred-to-human (no fix; awareness only) |
| #6 sanctioned except/catch cluster | LOW | CODE | — | No-action (report: "None required" — sanctioned) |
| #7 type-ignore + 25MB in-mem read | LOW | CODE | — | No-action (report: "None required") |

## Dismissed candidates (leave alone unless instructed)
T1-001, T1-002, T1-004, T1-012, T1-013, T1-015, T1-016 — see FINAL.md Dismissed section.

## Regression check — 2026-05-27 (HEAD f0fa441, baseline 1b64aef)
PASS. Re-ran the 3-tier funnel (2 isolated subagents + synthesis) → [FINAL-regression-2026-05-27.md](./FINAL-regression-2026-05-27.md).
- All 4 merged fixes (#1/#3/#4/#5) present + correct; #5 tests proven not false-green; backend gate 249 green.
- No regressions; #2/#8 unchanged (operator-only); #6/#7 + all dismissed candidates hold.
- 1 net-new **INFO** introduced by #5 — **R1**: concurrent identical-byte upload could wrong-delete a committed sibling's file (`attachments.py:64,83-84`). Threat-model-bounded (single-operator, sequential UI). No fix recommended.

| Finding | Sev | Status |
|---------|-----|--------|
| R1 concurrent-upload wrong-delete window | INFO | No-action (threat-model-bounded; introduced by #5 fix) |
