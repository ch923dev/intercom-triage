---
name: part-type-change
description: Use when editing the Intercom `part_type` mapping (comment / note / event routing to parts[] vs internal_notes[] vs skip) — fires on edits to backend/app/services/intercom_normalizer.py, backend/app/schemas.py, or webapp/src/components/ticket/TicketConversation.vue that reference part_type or the parts/internal_notes split. Forces a live-payload check because the routing is the customer-visible vs team-only boundary (invariant #4).
---

# Part type change checklist

Intercom's official `part_type` is a documented string on each conversation part. The mapping is far more stable than the old reverse-engineered numeric `renderable_type` codes, but the routing is still load-bearing: it decides what the AI sees vs what stays team-only (invariant #4).

Current mapping (in `backend/app/services/intercom_normalizer.py`):

| part_type | author.type | Destination | Fed to AI? |
|-----------|-------------|-------------|------------|
| `source` (opening message) | user/lead/contact | `parts[]` (is_admin=false) | yes |
| `source` | admin/bot | `parts[]` (is_admin=true) | yes |
| `comment` | user/lead/contact | `parts[]` (is_admin=false) | yes |
| `comment` | admin/bot/team | `parts[]` (is_admin=true) | yes |
| `note` | admin/bot | `internal_notes[]` | **no** |
| `assignment`/`open`/`close`/`snoozed`/… | any | skip | no |
| unknown | any | skip + `log_event("intercom.unknown_part_type")` | no |

Build a TodoWrite list from this checklist.

## Required evidence

You **must** confirm a change against a real Intercom payload. The router is a one-way valve: a customer message misrouted as an event silently disappears from the AI prompt; a `note` misrouted as `comment` leaks team-only context into the model (invariant #4 violation).

- [ ] Fetch a live conversation via the official API: `curl -H "Authorization: Bearer $INTERCOM_ACCESS_TOKEN" -H "Intercom-Version: 2.13" https://api.intercom.io/conversations/<id> | jq '.conversation_parts.conversation_parts[] | {part_type, author: .author.type, body}'`.
- [ ] Confirm the `part_type` / `author.type` you're adding or changing matches the live payload.

If you cannot get a live payload, **stop and ask**. Do not infer from a forum post or LLM training data. Pin `INTERCOM_API_VERSION` and re-verify after any version bump (the enum can shift).

## Edit sites

1. **`backend/app/services/intercom_normalizer.py`** — `normalize_conversation` + the `_SKIP_PART_TYPES` / `_ADMIN_AUTHOR_TYPES` sets. The `parts[]` vs `internal_notes[]` split is the load-bearing decision. Add/adjust a unit test in `tests/test_intercom_normalizer.py`.
2. **`backend/app/schemas.py`** — `ConversationPartSchema.is_admin` is the resulting boolean; no change unless you add a field.
3. **`webapp/src/components/ticket/TicketConversation.vue`** — renders parts in the flyout; styling only unless you render a new category.

## Verify

- [ ] `cd backend && pytest -q tests/test_intercom_normalizer.py tests/test_sync_service.py` — green; the `note → internal_notes, never parts` test is the canary.
- [ ] `cd backend && mypy app` clean.
- [ ] After a sync, `curl http://127.0.0.1:4000/tickets | jq '.[] | {parts: (.parts | length), internal_notes: (.internal_notes | length)}'` — sanity-check the split landed.

## Don't

- Don't fold `internal_notes[]` into `parts[]` for "simplicity." That feeds team-only text into the AI prompt — an FR-level invariant violation (#4).
- Don't add a new `part_type` without an example payload pasted into the PR.
- Don't widen the skip set without checking what the skipped events were.
- Don't trust this skill's mapping table over the live payload. The table is documentation; the payload is truth.
