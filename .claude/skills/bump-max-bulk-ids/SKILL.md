---
name: bump-max-bulk-ids
description: Use when changing the MAX_BULK_IDS constant (the per-request cap on bulk ticket operations) in backend/app/config.py — fires on edits to that constant or to backend/app/schemas.py:BulkTicketIds. Enforces backend + webapp + tests coverage so the cap stays consistent end-to-end.
---

# MAX_BULK_IDS bump checklist

`MAX_BULK_IDS` (default 200) bounds the number of ticket ids accepted in a single bulk request. It exists for two reasons that you must respect when bumping it:

1. **Memory + transaction size on the backend.** Every bulk path loads the rows, applies the change, and commits once at the end of the loop. 200 was picked because larger batches risk SQLite write contention and long-running transactions blocking the AI cache sweep.
2. **UX latency on the webapp.** The webapp blocks the UI while a bulk request is in flight. At 200 rows the round-trip is ~1s on localhost; doubling it doubles the user-visible delay.

Build a TodoWrite list from this checklist.

## Edit sites

1. **`backend/app/config.py`** — `MAX_BULK_IDS` constant. The change goes here first.
2. **`backend/app/schemas.py`** — `BulkTicketIds` enforces the cap with a pydantic validator. Verify the validator still reads from `MAX_BULK_IDS` (it should — it imports the constant) so no second edit is needed.
3. **`backend/tests/test_bulk_schemas.py` + `backend/tests/test_bulk_api.py`** — both files exercise the cap. If a test hardcodes the literal `200` instead of importing the constant, update it.
4. **`webapp/src/`** — the webapp does **not** currently pre-flight the cap. If you are bumping the limit, also add a pre-submit warning in `BulkActionBar.vue` (or wherever the bulk selection is dispatched from). If you skip the webapp side, the webapp will submit a too-large request and surface the backend's 422 as a generic error — bad UX.

## Verify

- [ ] `cd backend && pytest -q tests/test_bulk_schemas.py tests/test_bulk_api.py` — both green.
- [ ] `cd backend && pytest -q` — full suite green (the constant is referenced from a few other tests).
- [ ] `cd backend && mypy app` clean.
- [ ] `cd webapp && npm run typecheck` clean, and if you touched a component, `npm run lint` clean (zero warnings).
- [ ] Manual: open the webapp, select more than the new cap, attempt a bulk resolve. Confirm the operator sees a clear pre-submit warning (if you added one) rather than a server-side 422.

## Don't

- Don't make `MAX_BULK_IDS` configurable via env var. It's a deliberate code-level constant — changing it is a code change because both sides ship together.
- Don't bump above ~1000 without checking the SQLite WAL behavior. Past a few hundred rows the single-commit pattern can hold the write lock long enough to interfere with the AI cache sweep loop in `backend/app/services/cache.py`.
- Don't lower the cap without checking the webapp's bulk-select UX — if a UI flow routinely needs more than the new limit, lowering the cap will make the product feel broken.
- Don't update spec.md / plan.md / README.md "later." The 200 figure is cited there too — grep for it and update in the same commit.
