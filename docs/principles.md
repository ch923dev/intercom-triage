# Engineering principles

These four principles override Claude Code defaults. Every package's `CLAUDE.md` assumes them. Apply on every change.

## 1. Think Before Coding

Don't assume. Don't hide confusion. Surface tradeoffs.

- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

Minimum code that solves the problem. Nothing speculative.

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" / "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If 200 lines could be 50, rewrite it.

## 3. Surgical Changes

Touch only what you must. Clean up only your own mess.

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.
- Remove imports your change made unused. Don't remove pre-existing dead code unless asked.

The test: every changed line traces directly to the user's request.

## 4. Goal-Driven Execution

Define success criteria. Loop until verified.

Transform tasks into verifiable goals before writing code. For multi-step work, state the plan up front:

```
1. [step] → verify: [check]
2. [step] → verify: [check]
```

"Make it work" is not a success criterion. Name the test, the click-path, the curl, or the `/metrics` counter that proves the change.

The repo-wide quality gates live in the root `CLAUDE.md` quality-gates table — run them before declaring a change complete.
