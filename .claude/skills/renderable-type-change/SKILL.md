---
name: renderable-type-change
description: Use when editing the Intercom `renderable_type` mapping (the 1/12/2/24/3 numeric codes for customer/admin/internal-note message types) — fires on edits to extension/intercom.js, backend/app/schemas.py, or webapp/src/components/ticket/TicketConversation.vue that reference renderable_type or the numeric codes. Forces a live-payload check before merging because the mapping is reverse-engineered and unstable.
---

# Renderable type change checklist

Intercom's `renderable_type` is an undocumented integer on each conversation part. The mapping below is reverse-engineered — it can change without notice and there is no spec to reference. Treat any change as load-bearing.

Known mapping (do not change without payload evidence):

| Code | Meaning | Visible to customer? | Fed to AI? |
|------|---------|----------------------|------------|
| 1, 12 | Inbound customer message | yes | yes |
| 2, 24 | Admin reply (operator → customer) | yes | yes |
| 3 | Internal team note (admin-only) | no | **no** |
| 5, 6, 14, 71 | Events (state change, assignment, etc.) | n/a | no (skip) |

Build a TodoWrite list from this checklist.

## Required evidence

You **must** confirm the change against a real Intercom payload before editing the mapping. The classifier is a one-way valve: a customer message misrouted as an event silently disappears from the AI prompt; an internal note misrouted as customer-visible leaks team-only context into the model.

- [ ] Open a live conversation in the popup. Click **Sync now**.
- [ ] Inspect the raw payload — the easiest path is `chrome://extensions → service worker → console`, then run a fetch against `https://app.intercom.com/ember/inbox/conversations/<id>` with `credentials: 'include'`.
- [ ] Confirm the numeric code in the live payload matches what you're about to add or change.

If you cannot get a live payload, **stop and ask**. Do not infer from a forum post or LLM training data.

## Edit sites

1. **`extension/intercom.js`** — the classifier lives in `normalizeConversation`. The `parts[]` vs `internal_notes[]` split is the load-bearing decision.
2. **`backend/app/schemas.py`** — `ConversationPart.is_admin` is derived from the type on the extension side; the backend only validates the resulting boolean. No change needed unless you're adding a new boolean.
3. **`webapp/src/components/ticket/TicketConversation.vue`** — renders parts in the flyout. May style customer vs admin differently; no logic change unless you're rendering a new category.

## Verify

- [ ] Backend AI tests still pass: `cd backend && pytest -q tests/test_ai.py`.
- [ ] After reloading the extension, **Sync now** and confirm in the popup that:
  - A conversation with an internal note shows only the customer-visible parts in the flyout.
  - The internal note appears in the "Internal notes" section, not the main thread.
- [ ] `curl http://127.0.0.1:4000/tickets | jq '.[] | {parts: (.parts | length), internal_notes: (.internal_notes | length)}'` — sanity-check that the split landed.

## Don't

- Don't fold `internal_notes[]` into `parts[]` for "simplicity." That break would feed team-only text into the AI prompt — an FR-level invariant violation.
- Don't add a new code without an example payload pasted into the PR.
- Don't widen the "skip" set without checking what the skipped events were — losing a state-transition event we relied on elsewhere will surface as a phantom data-flow bug.
- Don't trust this skill's mapping table over the live payload. The table is documentation; the payload is truth.
