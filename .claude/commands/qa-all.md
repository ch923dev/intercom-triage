---
description: Run both backend and webapp quality gates back-to-back. Use before a cross-package commit.
---

Run the backend gate first, then the webapp gate. Both must pass.

Don't invoke `/qa-backend` and `/qa-webapp` — re-execute their command sequences inline so the output is in one place and the user can see the full picture.

```powershell
# Backend gate
cd backend
ruff check app tests
ruff format --check app tests
mypy app
pytest -q
cd ..

# Webapp gate
cd webapp
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build
cd ..
```

Stop at the first failure and surface the output to the user. Don't silently fix and rerun.

If a format check fails, ask the user whether to apply the write variant (`ruff format app tests` for backend, `npm run format` for webapp). Don't auto-format without consent.

When both gates pass, report `qa-all: green` with a one-line summary (`backend: N tests, webapp: M tests`).

For the extension package, there is no automated gate — `/qa-extension` covers the manual reload-and-verify checklist.
