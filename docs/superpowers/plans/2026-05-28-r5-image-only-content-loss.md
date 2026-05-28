# R.5 Image-Only Content Loss Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `extension/intercom.js:normalizeConversation` from dropping a conversation part that carries only an attachment (no text), by synthesizing a `[attachment: …]` placeholder body from `uploads[]` when the text is empty.

**Architecture:** Extension-only, no contract change. One new pure helper `uploadsToPlainText(uploads)` in `intercom.js` (styled after `blocksToPlainText`). The three identical drop-guards (`const body = blocksToPlainText(data.blocks); if (!body) continue;`) gain a `|| uploadsToPlainText(data.uploads)` fallback — one `replace_all` edit covers all three (inbound 1/12, admin 2/24, internal note 3). The placeholder rides the existing `body` field to the backend; `HydratedTicket` is untouched (invariant #2).

**Tech Stack:** Plain ES modules, Node's built-in `node:test` + `node:assert/strict` — no deps, no bundler, no build step (extension charter).

**Spec:** `docs/superpowers/specs/2026-05-28-r5-image-only-content-loss-design.md`

**Branch:** create `feat/r5-image-only-content-loss` off `main` before Task 1.

---

## File structure

- `extension/fixtures/conversation-attachment.json` — CREATE: synthetic fixture exercising text-less parts with `uploads[]` (types 1, 2, 3) + a text+upload part + a no-text-no-upload part.
- `extension/intercom.test.js` — MODIFY: append 5 behavioral tests (after the last test, before EOF).
- `extension/intercom.js` — MODIFY: add `uploadsToPlainText` helper (after `blocksToPlainText`, ~line 163); extend the 3 body guards (~lines 260, 269, 278) via one `replace_all`.
- `extension/snapshot.test.js` — MODIFY: add `'conversation-attachment'` to the `FIXTURES` array (~lines 55-62).
- `extension/fixtures/expected/conversation-attachment.json` — CREATE (generated via `UPDATE_SNAPSHOTS=1`).
- `extension/fixtures/README.md` — MODIFY: add the new fixture row.
- `docs/ROADMAP.md` — MODIFY: flip R.5 ledger row to shipped; drop R.5 from "Still open".

---

## Task 1: Fixture + failing behavioral tests (RED)

**Files:**
- Create: `extension/fixtures/conversation-attachment.json`
- Modify: `extension/intercom.test.js` (append tests)

- [ ] **Step 1: Create the fixture**

Create `extension/fixtures/conversation-attachment.json`:

```json
{
  "_comment": "SYNTHESIZED fixture, not a real capture. Exercises R.5: text-less parts that carry uploads[]. The per-upload field names (name/file_name/filename) are a DEFENSIVE GUESS — the R.1 live capture confirmed uploads[] is present on type 1/2/3 parts but did not record the object shape. Parts: (1) customer image-only with a named upload, (2) customer attachment-only with no name, (3) admin reply with text AND an upload (text must win, upload NOT appended), (4) internal note attachment-only (-> internal_notes[]), (5) customer part with no text and no upload (still dropped). user_summary mirrors live reality: companies:[] + first_company:null.",
  "id": "1007",
  "title": "Customer sent screenshots",
  "state": "open",
  "priority": false,
  "created_at": 1716860000,
  "last_updated": 1716861000,
  "user_summary": {
    "user_id": "user-ext-777",
    "name": "Jordan Snap",
    "email": "jordan@example.com",
    "role": "user",
    "companies": [],
    "first_company": null
  },
  "renderable_parts": [
    {
      "renderable_type": 1,
      "created_at": 1716860100,
      "renderable_data": {
        "user_summary": { "user_id": "user-ext-777", "name": "Jordan Snap", "email": "jordan@example.com", "role": "user" },
        "blocks": [],
        "uploads": [{ "name": "receipt.png", "content_type": "image/png" }]
      }
    },
    {
      "renderable_type": 1,
      "created_at": 1716860200,
      "renderable_data": {
        "user_summary": { "user_id": "user-ext-777", "name": "Jordan Snap", "email": "jordan@example.com", "role": "user" },
        "blocks": [],
        "uploads": [{ "content_type": "application/pdf" }]
      }
    },
    {
      "renderable_type": 2,
      "created_at": 1716860300,
      "renderable_data": {
        "admin_summary": { "id": "admin-7", "name": "Riley Agent", "email": "riley@support.example" },
        "blocks": [{ "type": "paragraph", "text": "See attached" }],
        "uploads": [{ "name": "fix.pdf" }]
      }
    },
    {
      "renderable_type": 3,
      "created_at": 1716860400,
      "renderable_data": {
        "admin_summary": { "id": "admin-7", "name": "Riley Agent", "email": "riley@support.example" },
        "blocks": [],
        "uploads": [{ "name": "trace.log" }]
      }
    },
    {
      "renderable_type": 1,
      "created_at": 1716860500,
      "renderable_data": {
        "user_summary": { "user_id": "user-ext-777", "name": "Jordan Snap", "email": "jordan@example.com", "role": "user" },
        "blocks": []
      }
    }
  ]
}
```

- [ ] **Step 2: Append the failing tests**

Append to `extension/intercom.test.js` (after the last test, before EOF). These use the existing `fixture()` helper + `APP_ID` + `normalizeConversation` import already at the top of the file:

```js
test('R.5: text-less customer part with a named upload becomes [attachment: name] in parts[]', () => {
  const t = normalizeConversation(fixture('conversation-attachment.json'), APP_ID);

  // Parts that survive: customer img (1) + customer file (1) + admin text (2).
  // The internal note goes to internal_notes[]; the no-text-no-upload part is dropped.
  assert.equal(t.parts.length, 3);
  assert.equal(t.parts[0].body, '[attachment: receipt.png]');
  assert.equal(t.parts[0].is_admin, false);
});

test('R.5: text-less part with an unnamed upload falls back to [attachment]', () => {
  const t = normalizeConversation(fixture('conversation-attachment.json'), APP_ID);
  assert.equal(t.parts[1].body, '[attachment]');
});

test('R.5: a part with text AND an upload keeps only its text (text-less-only scope)', () => {
  const t = normalizeConversation(fixture('conversation-attachment.json'), APP_ID);
  assert.equal(t.parts[2].body, 'See attached');
  assert.equal(t.parts[2].is_admin, true);
  assert.ok(!t.parts[2].body.includes('[attachment'), 'upload must NOT be appended when text exists');
});

test('R.5: text-less internal note with an upload lands in internal_notes[], not parts[]', () => {
  const t = normalizeConversation(fixture('conversation-attachment.json'), APP_ID);
  assert.equal(t.internal_notes.length, 1);
  assert.equal(t.internal_notes[0].body, '[attachment: trace.log]');
  assert.equal(t.internal_notes[0].is_admin, true);
  // invariant #4: the note's attachment must not leak into the AI-visible parts.
  assert.ok(t.parts.every((p) => !p.body.includes('trace.log')));
});

test('R.5: a part with no text and no uploads is still dropped', () => {
  const t = normalizeConversation(fixture('conversation-attachment.json'), APP_ID);
  // Fixture has four 1/2 parts but one (the last) has neither text nor uploads,
  // so only three survive — proving the empty part is dropped.
  assert.equal(t.parts.length, 3);
});
```

- [ ] **Step 3: Run the tests, verify the new ones FAIL**

Run: `cd extension && node --test`
Expected: the R.5 tests FAIL. With current code the two text-less customer parts and the internal-note part are dropped, so `t.parts.length` is `1` (only the admin text part) and `t.internal_notes.length` is `0` — assertions like `parts.length === 3` and `parts[0].body === '[attachment: receipt.png]'` fail. The existing 14 tests still PASS.

---

## Task 2: Helper + guard wiring (GREEN)

**Files:**
- Modify: `extension/intercom.js`

- [ ] **Step 1: Add the `uploadsToPlainText` helper**

In `extension/intercom.js`, insert the helper immediately after `blocksToPlainText` closes (its `}` at ~line 163) and before the `stripHtml` function. Use this exact Edit:

old_string:
```js
  return lines
    .map((line) => line.trim())
    .filter(Boolean)
    .join('\n')
    .slice(0, 8000);
}

function stripHtml(s) {
```

new_string:
```js
  return lines
    .map((line) => line.trim())
    .filter(Boolean)
    .join('\n')
    .slice(0, 8000);
}

// Fallback body for a part that has attachments but no text block (R.5).
// The per-upload field that holds the filename is reverse-engineered (the
// live capture confirmed uploads[] exists but not its object shape), so try
// the likely names and degrade to a generic marker — never crash, never
// re-drop. One line per upload; same 8000-char cap as blocksToPlainText.
function uploadsToPlainText(uploads) {
  if (!Array.isArray(uploads)) return '';
  return uploads
    .map((u) => {
      if (!u || typeof u !== 'object') return '[attachment]';
      const name = u.name ?? u.file_name ?? u.filename ?? null;
      return typeof name === 'string' && name.trim()
        ? `[attachment: ${name.trim()}]`
        : '[attachment]';
    })
    .join('\n')
    .slice(0, 8000);
}

function stripHtml(s) {
```

- [ ] **Step 2: Wire the fallback into all three body guards**

The three guard sites (inbound 1/12, admin 2/24, internal note 3) are textually identical, so one `replace_all` Edit covers all three. In `extension/intercom.js`:

old_string (with `replace_all: true`):
```js
      const body = blocksToPlainText(data.blocks);
      if (!body) continue;
```

new_string:
```js
      const body = blocksToPlainText(data.blocks) || uploadsToPlainText(data.uploads);
      if (!body) continue;
```

- [ ] **Step 3: Run the tests, verify all PASS**

Run: `cd extension && node --test`
Expected: all PASS — `# pass 19` (14 existing + 5 new behavioral), `# fail 0`.

- [ ] **Step 4: Commit**

```bash
git add extension/intercom.js extension/intercom.test.js extension/fixtures/conversation-attachment.json
git commit -m "fix(extension): surface uploads[] for text-less parts instead of dropping

A conversation part carrying only an attachment (no text block) yielded
an empty body from blocksToPlainText, hit 'if (!body) continue', and was
dropped entirely — the backend never saw the message (R.5 content loss).
Add uploadsToPlainText: when a part has no text, synthesize an
[attachment: name] / [attachment] placeholder body from uploads[] so the
part survives. Applies to customer (1/12), admin (2/24), and internal
note (3) parts; text-bearing parts are unchanged. No contract change.

Refs R.5."
```

---

## Task 3: Snapshot coverage

**Files:**
- Modify: `extension/snapshot.test.js`
- Create (generated): `extension/fixtures/expected/conversation-attachment.json`

- [ ] **Step 1: Register the fixture in the snapshot harness**

In `extension/snapshot.test.js`, add the new fixture to the `FIXTURES` array. Use this Edit:

old_string:
```js
  'conversation-unknown-type',
  'conversation-events',
];
```

new_string:
```js
  'conversation-unknown-type',
  'conversation-events',
  'conversation-attachment',
];
```

- [ ] **Step 2: Generate the expected snapshot**

Run: `cd extension && UPDATE_SNAPSHOTS=1 node --test`
Expected: exits 0; `extension/fixtures/expected/conversation-attachment.json` is created.

- [ ] **Step 3: Eyeball the generated snapshot**

Run: `cd extension && cat fixtures/expected/conversation-attachment.json`
Expected:
- `parts` has exactly 3 entries: `[attachment: receipt.png]` (is_admin false), `[attachment]` (is_admin false), `See attached` (is_admin true).
- `internal_notes` has exactly 1 entry: `[attachment: trace.log]` (is_admin true).
- No part body contains `trace.log`.
- `author.company` is `null`; `url` ends `/conversation/1007`.

- [ ] **Step 4: Verify snapshots are stable (no UPDATE flag)**

Run: `cd extension && node --test`
Expected: all PASS — `# pass 20` (19 from Task 2 + 1 new snapshot), `# fail 0`. No drift.

- [ ] **Step 5: Commit**

```bash
git add extension/snapshot.test.js extension/fixtures/expected/conversation-attachment.json
git commit -m "test(extension): snapshot the attachment-placeholder fixture (R.5)

Refs R.5."
```

---

## Task 4: Docs + roadmap

**Files:**
- Modify: `extension/fixtures/README.md`
- Modify: `docs/ROADMAP.md`

- [ ] **Step 1: Add the fixture row to the README**

In `extension/fixtures/README.md`, add a row to the fixtures table (after the `conversation-events.json` row). Match the existing table's column layout:

```markdown
| `conversation-attachment.json`  | 1, 2, 3 with `uploads[]` (text-less) | `[attachment: …]` placeholder; text-less only |
```

(If the table's columns differ, adapt the cell content to the existing headers — the point is: name = `conversation-attachment.json`, what it covers = text-less parts carrying `uploads[]` across types 1/2/3, outcome = placeholder body instead of a dropped part.)

- [ ] **Step 2: Mark R.5 shipped in the roadmap ledger**

In `docs/ROADMAP.md`, change the R.5 ledger row (currently):

```markdown
| R.5 | Image-only message content loss | ◯ open | — | type 1/2/3 parts can carry `uploads[]`; a text-less attachment-only message yields empty body and is dropped (`intercom.js` `if (!body) continue`). Surfaced during the R.1 live capture |
```

to:

```markdown
| R.5 | Image-only message content loss | ✅ shipped | — | text-less parts carrying `uploads[]` now synthesize an `[attachment: …]` placeholder body (extension-only, no contract change) instead of being dropped; covered by behavioral + snapshot tests |
```

Then update the "Still open" note near the top of the file (line ~9): remove "R.5 (image-only message content loss — surfaced during the R.1 live capture)" from that sentence.

- [ ] **Step 3: Commit**

```bash
git add extension/fixtures/README.md docs/ROADMAP.md
git commit -m "docs(r5): mark R.5 shipped; document attachment fixture

Refs R.5."
```

---

## Manual verification (after all tasks — not automatable)

The MV3 extension has no headless harness:

- [ ] Reload the unpacked extension at `chrome://extensions`.
- [ ] Open the popup → **Sync now** (operator must be logged into Intercom) on a conversation that contains an image-only / attachment-only customer message.
- [ ] Confirm that message now appears as a ticket part whose body reads `[attachment: <filename>]` (or `[attachment]` if Intercom's upload object uses a field name other than `name`/`file_name`/`filename` — see next bullet), and is no longer missing from `GET /tickets`.
- [ ] Open the service-worker DevTools console → confirm no new warnings during sync.
- [ ] **Verify the filename field:** if the placeholder shows the generic `[attachment]` even though the message clearly had a named file, capture the real upload object shape and extend the candidate list in `uploadsToPlainText` (`u.name ?? u.file_name ?? u.filename ?? …`). This is the one defensive guess in the fix.

---

## Self-review notes

- **Spec coverage:** D1 (helper + guards) → Task 2. D2 (fixture) → Task 1 Step 1. D3 (behavioral tests) → Task 1 Step 2. D4 (snapshot) → Task 3. D5 (docs/roadmap) → Task 4. Manual verify + filename caveat → Manual section. All covered.
- **Test count math:** existing 14 + 5 behavioral (Task 1) = 19 after Task 2; +1 snapshot (Task 3) = 20 total, `# fail 0`.
- **Scope guard:** text-bearing parts unchanged (`||` short-circuits); part with neither text nor uploads still dropped (Task 1 test 5). Matches the "text-less only" decision.
- **Invariants:** #2 untouched (no field added to `HydratedTicket`); #3 routing unchanged; #4 internal-note placeholders stay in `internal_notes[]` (Task 1 test 4 asserts no leak); #6 a customer image part now correctly advances the content signature.
- **Determinism:** the fixture carries explicit top-level + per-part `created_at`, so `normalizeConversation`'s `new Date()` fallbacks never fire — the snapshot is stable across runs/machines.
