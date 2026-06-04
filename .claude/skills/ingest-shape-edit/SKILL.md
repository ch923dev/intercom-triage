---
name: ingest-shape-edit
description: Use when editing the HydratedTicket shape (adding/removing/renaming a field) — fires on edits to backend/app/schemas.py near `class HydratedTicket`, backend/app/services/intercom_normalizer.py near `normalize_conversation`, or webapp/src/types/api.ts near `interface Ticket`. Enforces the matched backend + webapp edit so ingest does not break.
---

# Ingest shape edit checklist

The `HydratedTicket` shape spans two packages and is produced backend-side by the normalizer. Editing the schema without the normalizer (or the webapp type) silently breaks the board — a field is dropped or never populated.

You **must** treat the field name as a single contract and edit all sites in the same change. Build a TodoWrite list from this checklist and tick each item as you finish it.

## Edit sites

1. **Backend schema (the contract)** — `backend/app/schemas.py`
   - `class HydratedTicket(BaseModel)` and `class TicketSchema(HydratedTicket)` (the board superset).
   - Optional field → sensible default (`None`, `[]`, `""`). Required field → the normalizer must always populate it.

2. **Backend normalizer (the producer)** — `backend/app/services/intercom_normalizer.py`
   - `normalize_conversation(detail, *, workspace_app_id, customer_contact)` builds the `HydratedTicket`.
   - Populate the new field from the official Intercom payload (conversation / `conversation_parts` / contact). Add a unit test in `tests/test_intercom_normalizer.py`.

3. **Webapp (consumer of the stored row)** — `webapp/src/types/api.ts`
   - `interface Ticket` is the superset returned by `GET /tickets`. Add the field; nullable on the wire → `T | null`, not `T | undefined`.
   - UI work is a separate task — surface it, don't bundle it here.

## Verify

Before reporting done:

- [ ] `cd backend && pytest -q` — full suite green (`tests/test_intercom_normalizer.py` is the canary).
- [ ] `cd backend && mypy app` clean.
- [ ] `cd webapp && npm run typecheck` clean.
- [ ] Run a sync (`curl -X POST http://127.0.0.1:4000/tickets/sync`) then `curl http://127.0.0.1:4000/tickets | jq '.[0] | keys'` and confirm the new key appears.

## Don't

- Don't edit one side and "open a follow-up" for the others — the contract goes through in a single commit.
- Don't add the field to `webapp/src/types/api.ts` only because the webapp needs to render something. If the data isn't on the wire, no shape change is needed; render from existing fields.
- Don't repurpose an existing nullable field as a flag — add a new field with a clear name.
