# R.1 Scraper Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `extension/intercom.js` emitting false "unknown renderable_type" warnings for the live event types 21/26/31, and lock the full `normalizeConversation` output behind committed snapshots so future Intercom-payload drift fails a test.

**Architecture:** Extension-only, no schema/contract change. One-line skip-set fix in `intercom.js` + comment-table update; one new event fixture; a ~15-line zero-dependency snapshot harness that diffs `normalizeConversation` output against committed `fixtures/expected/*.json`. Behavioral asserts stay in `intercom.test.js`.

**Tech Stack:** Plain ES modules, Node's built-in `node:test` + `node:assert/strict` (no deps, no bundler, no build step — extension charter).

**Spec:** `docs/superpowers/specs/2026-05-28-r1-scraper-hardening-design.md`

**Branch:** `feat/r1-scraper-hardening` (already created off `main`).

---

## File structure

- `extension/intercom.js` — MODIFY: `KNOWN_SKIPPED_RENDERABLE_TYPES` set + comment table (~lines 26-48).
- `extension/fixtures/conversation-events.json` — CREATE: pure non-text events (21/26/31/5).
- `extension/intercom.test.js` — MODIFY: append two behavioral tests (silent-skip, company-null).
- `extension/snapshot.test.js` — CREATE: zero-dep snapshot harness + one snapshot per fixture.
- `extension/fixtures/expected/*.json` — CREATE (generated): committed expected output, one per fixture.
- `extension/fixtures/README.md` — MODIFY: note the events fixture + the snapshot harness.
- `docs/ROADMAP.md` — MODIFY: mark R.1 done.
- auto-memory `intercom-user-summary-company.md` + `MEMORY.md` — MODIFY: company confirmed absent.

---

## Task 1: Skip-set fix + event fixture + behavioral tests

**Files:**
- Create: `extension/fixtures/conversation-events.json`
- Modify: `extension/intercom.js` (lines ~26-48)
- Modify: `extension/intercom.test.js` (append two tests)

- [ ] **Step 1: Create the event fixture**

Create `extension/fixtures/conversation-events.json` with the confirmed live event shapes (synthetic PII):

```json
{
  "_comment": "SYNTHESIZED fixture, not a real capture. Shapes match a 2026-05-28 live capture (workspace j3dxf22l). Pure non-text system-event parts: priority change (21), participant added (26), bot/workflow rule fired (31), assignment (5). All must be skipped SILENTLY (no unknown-type warning) and yield empty parts[]/internal_notes[]. user_summary mirrors live reality: companies:[] + first_company:null, so author.company resolves to null.",
  "id": "1006",
  "title": "Ticket with only system events",
  "state": "open",
  "priority": false,
  "created_at": 1716850000,
  "last_updated": 1716851000,
  "user_summary": {
    "id": "internal-rec-eee",
    "user_id": "user-ext-999",
    "name": "Sam Eventful",
    "pseudonym": "Blue Tiger",
    "email": "sam@example.com",
    "role": "user",
    "company_ids": ["comp-1"],
    "companies": [],
    "first_company": null,
    "phone": "+1-555-0199",
    "phone_country": "US",
    "timezone": "America/Chicago",
    "geoip_data": {
      "city_name": "Chicago",
      "region_code": "IL",
      "country_name": "United States",
      "timezone": "America/Chicago"
    }
  },
  "renderable_parts": [
    {
      "renderable_type": 21,
      "created_at": 1716850100,
      "renderable_data": {
        "priority": "priority",
        "previous_priority": "not_priority",
        "admin_summary": { "id": "admin-7", "name": "Riley Agent", "is_operator": false }
      }
    },
    {
      "renderable_type": 26,
      "created_at": 1716850200,
      "renderable_data": {
        "adding_entity_type": "admin",
        "participant_summary": { "id": "user-ext-888", "name": "Pat Participant" },
        "adding_entity": { "id": "admin-7", "name": "Riley Agent" }
      }
    },
    {
      "renderable_type": 31,
      "created_at": 1716850300,
      "renderable_data": {
        "bot_id": "bot-1",
        "rule_id": "rule-42",
        "rule_name": "Auto-assign VIP",
        "entity_type": "operator",
        "entity": { "id": "operator-1", "name": "OnlySales Bot", "is_operator": true }
      }
    },
    {
      "renderable_type": 5,
      "created_at": 1716850400,
      "renderable_data": {}
    }
  ]
}
```

- [ ] **Step 2: Write the failing tests**

Append to `extension/intercom.test.js` (after the last test, before EOF):

```js
test('live event types 21/26/31 are skipped SILENTLY (no unknown-type warning)', () => {
  const { result: t, calls } = withWarnSpy(() =>
    normalizeConversation(fixture('conversation-events.json'), APP_ID),
  );

  // Priority-change (21), participant-added (26), bot-rule (31) and
  // assignment (5) carry no conversation text — none should land anywhere.
  assert.equal(t.parts.length, 0);
  assert.equal(t.internal_notes.length, 0);
  // The whole point of the fix: these are KNOWN events, not unknown codes,
  // so they must NOT trip the reverse-engineered-mapping warning.
  assert.equal(calls.length, 0, '21/26/31 must be known-skipped, not warned');
});

test('author.company is null when companies[] is empty (confirmed live shape)', () => {
  const { result: t } = withWarnSpy(() =>
    normalizeConversation(fixture('conversation-events.json'), APP_ID),
  );

  // Live user_summary carries company_ids but no company NAME
  // (first_company:null, companies:[]). The normalizer must resolve null,
  // not throw and not invent a value.
  assert.equal(t.author.company, null);
  assert.equal(t.author.id, 'user-ext-999');
});
```

- [ ] **Step 3: Run the tests, verify the silent-skip one FAILS**

Run: `cd extension && node --test`
Expected: the `21/26/31 skipped SILENTLY` test FAILS — `calls.length` is `3` (one warn each for 21/26/31), not `0`. The `author.company` test PASSES (company is already null). The existing 6 tests still PASS.

- [ ] **Step 4: Apply the code fix in `intercom.js`**

Replace the skip-set declaration + its comment (currently around lines 44-48):

```js
// Non-text events we *expect* to skip silently: assignment/attribute changes
// (5/6/14), priority change (21), participant added (26), bot/workflow-rule
// fired (31), and bot/AI translation (71). These are known-and-ignored, so
// they must NOT trigger the unknown-type warning below — only genuinely
// unrecognized codes should. Verified against a 2026-05-28 live capture
// (workspace j3dxf22l). Keep this list in sync with the table above.
const KNOWN_SKIPPED_RENDERABLE_TYPES = new Set([5, 6, 14, 21, 26, 31, 71]);
```

Then extend the comment table above it (currently around lines 33-35) — insert these lines after the `3  — Internal team note ...` line and before the `5/6/14 ...` line:

```js
//   21 — Priority-change event               → skip
//   26 — Participant-added event             → skip
//   31 — Bot / workflow-rule event           → skip
```

- [ ] **Step 5: Run the tests, verify all PASS**

Run: `cd extension && node --test`
Expected: all tests PASS (existing 6 + 2 new). `# pass 8`, `# fail 0`.

- [ ] **Step 6: Commit**

```bash
git add extension/intercom.js extension/intercom.test.js extension/fixtures/conversation-events.json
git commit -m "fix(extension): skip live event types 21/26/31 instead of warning

Live capture (workspace j3dxf22l, 2026-05-28) shows renderable_type
21 (priority change), 26 (participant added), 31 (bot/workflow rule)
occur regularly — all non-text events. They were absent from
KNOWN_SKIPPED_RENDERABLE_TYPES, so the scraper emitted a false
'unknown renderable_type' warning on nearly every sync. Add them to
the skip set + document them. Genuinely-unknown codes still warn.

Refs R.1."
```

---

## Task 2: Snapshot harness + committed expected output

**Files:**
- Create: `extension/snapshot.test.js`
- Create (generated): `extension/fixtures/expected/*.json` (one per fixture)

- [ ] **Step 1: Write the snapshot harness + tests**

Create `extension/snapshot.test.js`:

```js
// Full-output snapshot tests for normalizeConversation.
//
// Run from this directory with:   node --test
// Regenerate the committed expected output with:
//   UPDATE_SNAPSHOTS=1 node --test
//
// Zero dependencies, no experimental flags (matches the extension's
// "plain ES modules, no tooling" invariant). Each snapshot locks the ENTIRE
// normalizeConversation return value to a committed fixtures/expected/<name>.json,
// so any drift in a field nobody hand-asserts still fails a test.
//
// Fixtures carry explicit per-part + top-level timestamps, so output is
// deterministic (the new Date() fallbacks in normalizeConversation are never
// hit here). console.warn is suppressed during snapshotting — the unknown-type
// fixture warns on purpose; that behavior is asserted in intercom.test.js.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { normalizeConversation } from './intercom.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const APP_ID = 'j3dxf22l';

function fixture(name) {
  return JSON.parse(readFileSync(join(HERE, 'fixtures', name + '.json'), 'utf8'));
}

function snapshot(name, value) {
  const file = join(HERE, 'fixtures', 'expected', name + '.json');
  const got = JSON.stringify(value, null, 2) + '\n';
  if (process.env.UPDATE_SNAPSHOTS) {
    writeFileSync(file, got);
    return;
  }
  const want = readFileSync(file, 'utf8');
  assert.equal(got, want, `snapshot drift for ${name} — re-run with UPDATE_SNAPSHOTS=1 if intended`);
}

// Suppress the intentional unknown-type warning during snapshotting.
function quiet(fn) {
  const original = console.warn;
  console.warn = () => {};
  try {
    return fn();
  } finally {
    console.warn = original;
  }
}

const FIXTURES = [
  'conversation-customer',
  'conversation-admin-reply',
  'conversation-internal-note',
  'conversation-mixed',
  'conversation-unknown-type',
  'conversation-events',
];

for (const name of FIXTURES) {
  test(`snapshot: ${name}`, () => {
    const out = quiet(() => normalizeConversation(fixture(name), APP_ID));
    snapshot(name, out);
  });
}
```

- [ ] **Step 2: Create the expected/ directory and generate snapshots**

Run: `cd extension && mkdir -p fixtures/expected && UPDATE_SNAPSHOTS=1 node --test`
Expected: command exits 0; six files appear under `extension/fixtures/expected/`.

- [ ] **Step 3: Eyeball the generated snapshots**

Run: `cd extension && cat fixtures/expected/conversation-events.json`
Expected: `parts` and `internal_notes` are `[]`, `priority` is `null`, `author.company` is `null`, `author.location` is `"Chicago, IL, United States"`, `url` ends `/conversation/1006`. Spot-check `conversation-mixed.json` too: `parts` has 2 entries (1 customer + 1 admin), `internal_notes` has 1.

- [ ] **Step 4: Verify snapshots are stable (second run, no UPDATE flag)**

Run: `cd extension && node --test`
Expected: all PASS — `# pass 14` (6 existing + 2 from Task 1 + 6 snapshots), `# fail 0`. No snapshot drift.

- [ ] **Step 5: Commit**

```bash
git add extension/snapshot.test.js extension/fixtures/expected/
git commit -m "test(extension): full-output snapshot harness for normalizeConversation

Zero-dep snapshot test (no experimental flags) diffing the entire
normalizeConversation return value against committed
fixtures/expected/*.json. Catches silent drift in fields the
hand-written asserts don't cover. Regenerate with UPDATE_SNAPSHOTS=1.

Refs R.1."
```

---

## Task 3: Docs, memory, roadmap

**Files:**
- Modify: `extension/fixtures/README.md`
- Modify: `docs/ROADMAP.md`
- Modify: `C:/Users/De Asis PC/.claude/projects/F--Claude-Projects-niche-intercom-ticket-management/memory/intercom-user-summary-company.md`

- [ ] **Step 1: Update the fixtures README**

In `extension/fixtures/README.md`, add a row to the `renderable_type` codes table (after the `conversation-unknown-type.json` row):

```markdown
| `conversation-events.json`      | 21, 26, 31, 5 (events)    | skipped silently   |
```

And append this paragraph after the table:

```markdown
## Snapshots

`extension/snapshot.test.js` locks the full `normalizeConversation` output for
every fixture to `fixtures/expected/<name>.json`. After intentionally changing
a fixture or the normalizer, regenerate with `UPDATE_SNAPSHOTS=1 node --test`
and review the diff before committing. The fixtures are synthetic but
shape-matched to a 2026-05-28 live capture (workspace `j3dxf22l`).
```

- [ ] **Step 2: Mark R.1 done in the roadmap ledger**

In `docs/ROADMAP.md`, change the R.1 ledger row (currently):

```markdown
| R.1 | Payload snapshot tests + unknown-type logging | ◯ open | — | highest-value hardening next |
```

to:

```markdown
| R.1 | Payload snapshot tests + unknown-type logging | ✅ shipped | — | live capture found event types 21/26/31 unmapped → false warns; added to skip set + full-output snapshot harness |
```

Also update the "Still open" note near the top of the file: remove "R.1 (payload snapshot tests)" from the open list.

- [ ] **Step 3: Update the company memory**

Overwrite `C:/Users/De Asis PC/.claude/projects/F--Claude-Projects-niche-intercom-ticket-management/memory/intercom-user-summary-company.md` body to record the confirmation (keep the frontmatter `name`/`type`, update `description`):

```markdown
---
name: intercom-user-summary-company
description: Intercom user_summary has NO company name (first_company:null, companies:[]); only company_ids + detail company_id exist. Confirmed via live capture 2026-05-28.
metadata:
  type: reference
---

Live capture (workspace `j3dxf22l`, 2026-05-28, ~58 conversations) confirms:
`user_summary.first_company` is always `null` and `user_summary.companies` is
always `[]`. The only company linkage present is `user_summary.company_ids`
(ids, no name) and the detail-level `company_id`. So the webapp company field
is genuinely null from this payload — resolving a company NAME would need a
separate companies-endpoint fetch (out of scope).

`extension/intercom.js:authorFromSummary` computes
`first_company?.name ?? companies?.[0]?.name ?? null` → correctly yields `null`,
no crash. Locked by the `author.company is null` test + the
`conversation-events.json` snapshot. See [[intercom-session-pivot]].
```

Then update the matching line in `MEMORY.md` to reflect "confirmed":

```markdown
- [Intercom user_summary company](intercom-user-summary-company.md) — CONFIRMED 2026-05-28: no company name in user_summary (first_company null, companies []); only company_ids + detail company_id.
```

- [ ] **Step 4: Run the full gate one last time**

Run: `cd extension && node --test`
Expected: all PASS, `# fail 0`.

- [ ] **Step 5: Commit**

```bash
git add extension/fixtures/README.md docs/ROADMAP.md
git commit -m "docs(r1): mark R.1 shipped; document events fixture + snapshot workflow

Refs R.1."
```

(The memory files live outside the repo and are not committed.)

---

## Manual verification (after all tasks)

Not automatable — the MV3 extension has no headless harness:

- [ ] Reload the unpacked extension at `chrome://extensions`.
- [ ] Open the popup → **Sync now** (operator must be logged into Intercom).
- [ ] Open the service-worker DevTools console → confirm **no**
  `unknown renderable_type 21` / `26` / `31` warnings appear during sync.
- [ ] Confirm tickets still render with the same `parts` / `internal_notes` as before (the fix only changes which event codes warn, not message handling).

---

## Self-review notes

- **Spec coverage:** D1 → Task 1 Step 4. D2 (events fixture) → Task 1 Step 1. D3 (snapshot harness) → Task 2. D4 (behavioral tests) → Task 1 Steps 2/4. D5 (docs/memory/roadmap) → Task 3. All covered.
- **Test count math:** existing 6 + Task 1 adds 2 = 8 after Task 1; Task 2 adds 6 snapshots = 14 total.
- **Determinism:** every fixture carries explicit `created_at` (top-level + per-part) and `last_updated`, so `normalizeConversation`'s `new Date()` fallbacks never fire — snapshots are stable across runs/machines.
- **No contract change:** `HydratedTicket` shape, backend, webapp all untouched (invariant #2 holds). `KNOWN_SKIPPED_RENDERABLE_TYPES` is internal to `intercom.js`.
