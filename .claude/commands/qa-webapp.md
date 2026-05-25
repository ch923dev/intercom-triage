---
description: Run the webapp quality gate (lint + format + typecheck + vitest + build). Use before any webapp commit or PR.
---

Run the full webapp quality gate from `webapp/`. The gate must be green before any webapp change is mergeable.

Execute these five commands in order. Stop at the first failure and surface the output to the user — don't silently fix and rerun.

```powershell
cd webapp
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build
```

Notes:

- `npm run lint` runs with `--max-warnings 0`. A single warning is a failure.
- If `npm run format:check` is the only failure, ask the user whether to apply `npm run format` (the write variant) before proceeding. Don't auto-format without consent.
- `npm test` is `vitest run`, not watch mode. It exits on its own.
- `npm run build` does `vue-tsc --noEmit && vite build`. The build step catches type errors that `npm run typecheck` already covered, but also catches Vite-time issues (asset paths, env vars).

If `npm test` fails, report the failing test names + first ~20 lines of each failure. Don't paste the entire vitest output.

If everything passes, report `qa-webapp: green` and the test count.

$ARGUMENTS — optional vitest selector (e.g. `src/stores/selection.spec.ts` or `-t "addRange"`). Append to `npm test --` if provided.
