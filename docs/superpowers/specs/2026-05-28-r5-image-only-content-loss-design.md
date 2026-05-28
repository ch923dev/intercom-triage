# R.5 — Image-only message content loss (design)

> Roadmap item **R.5** (`docs/ROADMAP.md`). Surfaced 2026-05-28 during the R.1
> live capture. Extension-only fix, approach (a): synthesize placeholder body
> text for text-less parts that carry attachments, so the part is no longer
> dropped. No `HydratedTicket` contract change.

## Problem

`extension/intercom.js:normalizeConversation` drops any conversation part whose
text is empty:

```js
const body = blocksToPlainText(data.blocks);
if (!body) continue;   // intercom.js:261 (1/12), 270 (2/24), 279 (3)
```

`blocksToPlainText` (intercom.js:141-163) only reads `block.text` /
`block.content` / `block.items` — it never looks at `data.uploads`. An Intercom
message that carries **only** an attachment (image, PDF) and no text block
yields `body === ''`, hits the guard, and the entire part is dropped. The
backend never learns the message existed — real, silent content loss, end to
end. The R.1 live capture (workspace `j3dxf22l`, 2026-05-28) confirmed type
1/2/3 parts can carry `uploads[]`; it was flagged out-of-scope for R.1 and
tracked here.

## Scope (decided)

- **Trigger: text-less parts only.** Synthesize a body from `uploads[]` *only*
  when `blocksToPlainText` returns empty. Parts that already have text (with or
  without attachments) are untouched — they were never lost. Matches the
  roadmap wording "surface `uploads[]` when a part has no text."
- **Part types: all three.** Customer (1/12) and admin reply (2/24) →
  `parts[]`; internal note (3) → `internal_notes[]`. Same drop guard at all
  three sites; one shared helper, three identical call sites.
- **Format: named, fallback generic.** One line per upload. If the upload
  object exposes a name, `[attachment: <name>]`; otherwise `[attachment]`.

## Out of scope

- No `attachments[]` field on `ConversationPartSchema` / `HydratedTicket` /
  webapp `Ticket` (that is the heavier approach (b); not chosen). The contract
  is unchanged — invariant #2 holds.
- No attachment URLs in the body (Intercom-signed/expiring; prompt noise).
- No download / rendering of the attachment bytes. The popup and webapp show
  the placeholder text like any other part body.
- No backend or webapp change of any kind.

## Known unknown (carried forward)

The R.1 capture recorded that `uploads` is **present** on `renderable_data` but
did **not** capture the per-upload object shape (the field that holds the
filename — `name` vs `file_name` vs `filename`). The helper therefore tries
each candidate and **degrades to `[attachment]` when none match**. Worst case
on a shape mismatch is a generic marker — never a crash, never a re-drop.
**Verify the candidate field names against a live image payload** when one is
available; adjust the candidate list if the real field differs.

## Deliverables

### D1 — Helper + call sites (`extension/intercom.js`)

New pure helper, styled after `blocksToPlainText` (defensive, returns `''` on
junk, 8000-char cap):

```js
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
```

Each of the three guard sites changes from:

```js
const body = blocksToPlainText(data.blocks);
if (!body) continue;
```

to:

```js
const body = blocksToPlainText(data.blocks) || uploadsToPlainText(data.uploads);
if (!body) continue;
```

`||` short-circuits: a part with real text keeps its text unchanged; the
upload fallback only runs when text is empty. The guard now fires only when
there is neither text nor an attachment.

### D2 — Fixture (`extension/fixtures/conversation-attachment.json`)

One new synthetic fixture (fake PII, real structure). Parts:

| part | type | blocks | uploads | expected |
|------|------|--------|---------|----------|
| 1 | 1 (customer) | none | `[{name:"receipt.png"}]` | `parts[]` body `[attachment: receipt.png]`, `is_admin:false` |
| 2 | 1 (customer) | none | `[{}]` (no name) | `parts[]` body `[attachment]` |
| 3 | 2 (admin) | `[{text:"See attached"}]` | `[{name:"fix.pdf"}]` | `parts[]` body `See attached` (text wins; upload NOT appended) |
| 4 | 3 (internal note) | none | `[{name:"trace.log"}]` | `internal_notes[]` body `[attachment: trace.log]`, NOT in `parts[]` |
| 5 | 1 (customer) | none | none / `[]` | dropped (no text, no upload) |

`user_summary` carries `companies: []` + `first_company: null` (confirmed live
reality), consistent with the other fixtures.

### D3 — Behavioral tests (`extension/intercom.test.js`)

Append tests asserting:

1. Text-less customer part with a named upload → `parts[]` length includes it,
   body is `[attachment: receipt.png]`, `is_admin === false`.
2. Unnamed upload → body is `[attachment]`.
3. Admin part with text + upload → body is the text only; no `[attachment` in
   it (proves "text-less only" scope; the `||` does not append).
4. Text-less internal note with an upload → lands in `internal_notes[]`, body
   `[attachment: trace.log]`, and does **not** leak into `parts[]`
   (invariant #4).
5. Part with no text and no uploads → still dropped (length unchanged for that
   part).

### D4 — Snapshot (`extension/snapshot.test.js` + `fixtures/expected/`)

Add `'conversation-attachment'` to the `FIXTURES` array. Generate
`extension/fixtures/expected/conversation-attachment.json` with
`UPDATE_SNAPSHOTS=1 node --test`, eyeball it (parts has the customer +
text-wins-admin entries, internal_notes has the trace.log entry, the
no-text-no-upload part is absent), then lock it with a clean `node --test`.

### D5 — Docs + roadmap

- `extension/fixtures/README.md`: add the `conversation-attachment.json` row to
  the fixtures table.
- `docs/ROADMAP.md`: flip the R.5 ledger row to `✅ shipped` with the commit
  ref; remove R.5 from the "Still open" note near the top.

## Verification

| Check | Command / action |
|-------|------------------|
| Behavioral + snapshot green | `cd extension && node --test` → `# fail 0` |
| Snapshot stable (no UPDATE flag) | second `node --test` run, no drift |
| Manual (not automatable) | reload unpacked → Sync now → a real image-only message renders as a part with `[attachment…]` and is no longer missing; confirm no new console warnings |

## Invariants touched

- **#2 (HydratedTicket 3-package shape):** unchanged. The placeholder rides the
  existing `body` field; no new field, no backend/webapp edit.
- **#3 (renderable_type map):** unchanged. Same 1/12 / 2/24 / 3 routing; only
  the body source for text-less parts changes.
- **#4 (parts[] vs internal_notes[]):** preserved. Internal-note placeholders
  stay in `internal_notes[]`, never fed to AI.
- **#6 (content-signature cache key):** correctly *helped* — a text-less
  customer image part now exists with a timestamp, so the content signature
  advances on customer image messages (it silently never did before). Only
  customer-visible parts move the signature; that is the intended behavior.

## Test count math

Existing 14 (8 behavioral + 6 snapshot). D3 adds 5 behavioral, D4 adds 1
snapshot → 20 total, `# fail 0`.
