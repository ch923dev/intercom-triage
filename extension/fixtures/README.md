# Intercom payload fixtures

Representative `GET /ember/inbox/conversations/{id}` detail payloads used by
`extension/intercom.test.js` to exercise `normalizeConversation`.

**These are SYNTHESIZED, not real captures.** They were hand-built from the
fields `normalizeConversation` actually reads (see `extension/intercom.js`):
top-level `id` / `title` / `state` / `priority` / `created_at` /
`last_updated` / `user_summary`, and per-part `renderable_type` /
`renderable_data` (`blocks`, `user_summary`, `entity`, `admin_summary`) /
`created_at`. No Intercom Access Token exists, so we cannot ship a real
capture here.

**Operator: replace these with real captured payloads when you have them.**
Open the popup, sync, and copy a raw conversation detail response from the
network tab (scrub PII first), keeping the same `renderable_type` codes so the
tests stay meaningful. The shape only needs the fields the normalizer reads;
extra fields are ignored.

`renderable_type` codes covered (mapping is reverse-engineered — see
`extension/CLAUDE.md`):

| Fixture                         | renderable_type(s)        | Goes to            |
|---------------------------------|---------------------------|--------------------|
| `conversation-customer.json`    | 1 (Messenger), 12 (email) | `parts[]`          |
| `conversation-admin-reply.json` | 2, 24                     | `parts[]`          |
| `conversation-internal-note.json` | 3                       | `internal_notes[]` |
| `conversation-mixed.json`       | 1, 24, 3, 5 (event)       | split + skip       |
| `conversation-unknown-type.json`| 1, 999 (unknown)          | part + warn+skip   |
| `conversation-events.json`      | 21, 26, 31, 5 (events)    | skipped silently   |

## Snapshots

`extension/snapshot.test.js` locks the full `normalizeConversation` output for
every fixture to `fixtures/expected/<name>.json`. After intentionally changing
a fixture or the normalizer, regenerate with `UPDATE_SNAPSHOTS=1 node --test`
and review the diff before committing. The fixtures are synthetic but
shape-matched to a 2026-05-28 live capture (workspace `j3dxf22l`).
