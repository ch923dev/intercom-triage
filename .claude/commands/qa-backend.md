---
description: Run the backend quality gate (ruff + mypy + pytest). Use before any backend commit or PR.
---

Run the full backend quality gate from `backend/`. The gate must be green before any backend change is mergeable.

Execute these four commands in order. Stop at the first failure and surface the output to the user — don't silently fix and rerun.

```powershell
cd backend
ruff check app tests
ruff format --check app tests
mypy app
pytest -q
```

If `ruff format --check` is the only failure, ask the user whether to apply `ruff format app tests` (the write variant) before proceeding. Don't auto-format without consent.

If `pytest` fails, report the failing test names + first ~20 lines of each failure. Don't paste the entire pytest output.

If everything passes, report `qa-backend: green` and the count of tests collected.

$ARGUMENTS — optional pytest selector (e.g. `tests/test_ai.py -k parse_response`). Append to the `pytest -q` line if provided.
