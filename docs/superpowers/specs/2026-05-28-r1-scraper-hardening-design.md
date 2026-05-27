# R.1 — Intercom scraper hardening (payload snapshot tests + unknown-type logging)

> Roadmap item **R.1** (`docs/ROADMAP.md`). Extension-only. No schema change, no
> cross-package contract change. Branch: `feat/r1-scraper-hardening` off `main`.

## Problem

`extension/intercom.js:normalizeConversation` parses Intercom's undocumented
`ember/` payloads via a **reverse-engineered** `renderable_type` mapping. Two
weaknesses:

1. **Incomplete event set.** `KNOWN_SKIPPED_RENDERABLE_TYPES = {5,6,14,71}` is
   missing event types that occur in live data. Anything not in the text set or
   the skip set fires a `console.warn` and is dropped. A live capture
   (workspace `j3dxf22l`, 2026-05-28, ~58 conversations open+closed) shows
   **types 21, 26, 31** occurring regularly — all non-text events — so the
   scraper emits false "unknown renderable_type" warnings on nearly every sync.

2. **Tests are hand-asserted, not snapshots.** `intercom.test.js` checks
   individual fields. Drift in any field nobody thought to assert (a renamed
   author key, a changed coercion, a new field) passes silently. R.1's intent
   is to lock the **full** normalizer output.

The fixtures are synthesized (no Intercom Access Token historically existed);
this design keeps them synthetic for privacy but corrects their **shapes** to
match a confirmed live capture.

## Ground truth (live capture, 2026-05-28, workspace j3dxf22l)

Verified against the operator's logged-in session via read-only `ember/` fetches.

### Complete `renderable_type` taxonomy observed

| type | meaning | data shape | handling |
|------|---------|-----------|----------|
| 1 | customer inbound (messenger) | `data.user_summary` + `blocks[{type:'paragraph',text}]` | → `parts[]`, `is_admin=false` ✓ |
| 12 | customer inbound (email) | `blocks[{type:'html',content}]` | → `parts[]`, `is_admin=false` ✓ |
| 2 | admin reply | `data.admin_summary` + paragraph blocks | → `parts[]`, `is_admin=true` ✓ |
| 24 | admin reply | `data.entity` + paragraph blocks | → `parts[]`, `is_admin=true` ✓ |
| 3 | internal team note | `data.admin_summary` + paragraph blocks | → `internal_notes[]` ✓ |
| 5 | assignment event | no blocks | skip ✓ |
| 6 | attribute/state event | no blocks | skip ✓ |
| 14 | event | no blocks | skip ✓ |
| 71 | bot/AI translation event | no blocks | skip ✓ |
| **21** | **priority change** | `{priority, previous_priority, admin_summary}`, no blocks | **skip (MISSING from set)** |
| **26** | **participant added** | `{adding_entity_type, participant_summary, adding_entity}`, no blocks | **skip (MISSING from set)** |
| **31** | **bot / workflow rule fired** | `{bot_id, rule_id, rule_name, entity, custom_bot_summary}`, no blocks | **skip (MISSING from set)** |

No other unknown types appeared once 21/26/31 are accounted for.

### Other confirmed facts

- **Timestamps**: ISO 8601 strings (`"2026-05-27T16:38:56.000Z"`), not unix
  seconds, on both list + detail. `toIso` already accepts both — no change.
- **`priority`**: boolean `false` on detail → `normalizeConversation` coerces to
  `null`. Confirmed correct.
- **Author locations** (all confirmed correct in current code):
  type 1 → `data.user_summary`; type 2 + 3 → `data.admin_summary`;
  type 24 → `data.entity` (carries `id,name,email,is_operator,is_redacted,image_url`).
- **Company is genuinely absent** from `user_summary`: `first_company: null`,
  `companies: []` in every sampled conversation. Only `company_ids` (ids, no
  name) on `user_summary` and `company_id` on the detail exist. The current
  guess `first_company?.name ?? companies?.[0]?.name` correctly yields `null` —
  it does not crash, the data just isn't there. (Resolving company name would
  require a separate companies fetch — out of scope.)
- **New ignorable fields** present but not consumed (harmless): `user_summary`
  has `pseudonym`, `company_ids`, `phone_country`; part `renderable_data` can
  carry `uploads`, `tags`, `custom_bot_summary`, `linked_ticket`,
  `seen_by_current_admin`, `translation_quality_feedbacks`.
- **Out-of-scope finding (flagged, not fixed):** type 1/2/3 parts may carry
  `uploads[]` (attachments). A message with only an upload and no text block
  yields empty `blocksToPlainText` and is dropped by `if (!body) continue`.
  Real content loss for image-only messages. Tracked for a future item; R.1
  does not change drop behavior.

## Deliverables

### D1 — Code fix (`extension/intercom.js`)

Add the three confirmed event types to the skip set and document them:

```js
const KNOWN_SKIPPED_RENDERABLE_TYPES = new Set([5, 6, 14, 21, 26, 31, 71]);
```

Extend the comment table (the `1/12/2/24/3/5/6/14/71` block, lines ~26-48) with
`21` priority-change, `26` participant-added, `31` bot/workflow-rule. No other
normalizer change. The genuinely-unknown path (unrecognized code → `console.warn`
with code + conversation id, no body, then skip) is unchanged.

### D2 — Fixtures (`extension/fixtures/`)

Synthetic payloads, real structure, fake PII. Correct the existing five to the
confirmed shapes, then add two. Every `user_summary` carries the real key set
(`pseudonym`, `company_ids: [...]`, `companies: []`, `first_company: null`,
`geoip_data`, `user_id`, `id`, `role`, `timezone`, `phone`).

| fixture | covers |
|---------|--------|
| `conversation-customer.json` | type 1 messenger paragraph blocks (existing, shape-corrected) |
| `conversation-admin-reply.json` | type 2 (`admin_summary`) + type 24 (`entity`) (existing) |
| `conversation-internal-note.json` | type 3 → `internal_notes[]`, customer-visible split (existing) |
| `conversation-mixed.json` | 1 + 24 + 3 + a skipped `5` (existing) |
| `conversation-unknown-type.json` | genuinely unknown code (e.g. `999`) → warn + skip (existing) |
| `conversation-email.json` | **NEW** — type 12 `{type:'html',content}` block → plain text in `parts[]` |
| `conversation-events.json` | **NEW** — types `21,26,31` (+ a `5`) with real event data shapes, no text blocks → **silent** skip |

### D3 — Snapshot harness (`extension/snapshot.test.js`)

Zero-dependency, no experimental flags. One snapshot per fixture; full
`normalizeConversation` output committed under `fixtures/expected/<name>.json`.

```js
function snapshot(name, value) {
  const file = join(HERE, 'fixtures', 'expected', name + '.json');
  const got = JSON.stringify(value, null, 2) + '\n';
  if (process.env.UPDATE_SNAPSHOTS) { writeFileSync(file, got); return; }
  assert.equal(got, readFileSync(file, 'utf8'));
}
```

- `UPDATE_SNAPSHOTS=1 node --test` regenerates the expected files.
- Snapshots normalize the volatile `created_at`/`updated_at` fallbacks: fixtures
  must carry explicit timestamps so output is deterministic (no `new Date()`
  fallback path in snapshotted cases).
- Committed expected JSON gives a readable diff in PRs.

### D4 — Behavioral tests (`extension/intercom.test.js`)

Keep existing invariant/privacy asserts. Add three:

- **`21/26/31 events skip SILENTLY`** — `conversation-events.json` → `parts`
  and `internal_notes` empty, `console.warn` call count === 0. Locks D1.
- **`email (type 12) html block → plain text`** — `conversation-email.json` →
  one `parts[]` entry, HTML stripped + entities decoded, `is_admin=false`.
- **`author.company is null when companies empty`** — any fixture →
  `author.company === null`. Locks the confirmed company reality.

### D5 — Docs / memory

- Update auto-memory `intercom-user-summary-company`: company name confirmed
  absent; only `company_ids` + detail `company_id` carry company linkage.
- `docs/ROADMAP.md` ledger: mark R.1 `done` with the commit; add the type
  21/26/31 finding to the execution notes.
- `extension/fixtures/README` (if present): note fixtures are synthetic but
  shape-matched to the 2026-05-28 live capture.

## Non-goals

- No real customer payloads committed (PII). Synthetic only.
- No `uploads[]`/attachment handling change (flagged for a future item).
- No company-name resolution (would need a companies endpoint fetch).
- No backend/webapp change. Extension-only; `HydratedTicket` shape untouched
  (invariant #2 holds).
- No build step, bundler, or npm dependency (extension charter).

## Verification

- `cd extension && node --test` → all green (existing 6 + new behavioral + new
  snapshots).
- `cd extension && UPDATE_SNAPSHOTS=1 node --test && node --test` → second run
  green with no diff (snapshots stable).
- Manual: reload unpacked extension → Sync now → DevTools console shows **no**
  `unknown renderable_type 21|26|31` warnings (and still warns on a real unknown).
