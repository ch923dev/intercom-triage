---
name: ingest-shape-edit
description: Use when editing the HydratedTicket shape (adding/removing/renaming a field) — fires on edits to backend/app/schemas.py near `class HydratedTicket`, extension/intercom.js near `normalizeConversation`, or webapp/src/types/api.ts near `interface Ticket`. Enforces the three-package edit so ingest does not break.
---

# Ingest shape edit checklist

The `HydratedTicket` shape spans three packages. Editing one without the other two will silently break `POST /tickets/ingest` — the backend rejects the payload with a pydantic validation error or, worse, accepts it and drops the field.

You **must** treat the field name as a single contract and edit all three sides in the same change. Build a TodoWrite list from this checklist and tick each item as you finish it.

## Three edit sites

1. **Backend (producer of the contract)** — `backend/app/schemas.py`
   - `class HydratedTicket(BaseModel)` near line 259.
   - `class TicketSchema(HydratedTicket)` near line 280 inherits from it.
   - If the new field is optional, give it a sensible default (`None`, `[]`, `""`).
   - If the new field is required, **every** ingest payload from the extension must already carry it — confirm that before merging.

2. **Extension (producer of the payload)** — `extension/intercom.js`
   - `normalizeConversation(detail)` near line 212 returns the JS object that is POSTed to `/tickets/ingest`.
   - Add the field to the returned object. Don't push it through a helper unless one already exists.
   - If derived from Intercom's payload, document the source field with a one-line JSDoc — the `renderable_type` and `parts[]` mapping is reverse-engineered and the next person needs the source.

3. **Webapp (consumer of the stored row)** — `webapp/src/types/api.ts`
   - `interface Ticket` near line 102 is the type. `HydratedTicket` itself is not re-declared on the webapp side — `Ticket` is the superset returned by `GET /tickets`.
   - Add the field. If it's nullable on the wire, type it `T | null`, not `T | undefined`.
   - If the new field needs UI, that's a separate task — surface it but don't bundle the UI work into this skill's scope.

## Verify

Before reporting done:

- [ ] `cd backend && pytest -q` — full suite green. The schema test in `tests/test_*_schemas.py` (if it touches the new field) is the canary.
- [ ] `cd backend && mypy app` clean.
- [ ] `cd webapp && npm run typecheck` clean.
- [ ] Reload the unpacked extension in `chrome://extensions`, click **Sync now** in the popup, then `curl http://127.0.0.1:4000/tickets | jq '.[0] | keys'` and confirm the new key appears.

## Don't

- Don't edit one side and "open a follow-up" for the others — the contract goes through in a single commit.
- Don't add the field to `webapp/src/types/api.ts` only because the webapp needs to render something. If the data isn't on the wire, no shape change is needed; render from existing fields.
- Don't repurpose an existing nullable field as a flag — add a new field with a clear name.
