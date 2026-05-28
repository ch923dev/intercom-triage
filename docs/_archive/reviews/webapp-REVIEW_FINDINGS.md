# Webapp Review — Findings (2026-05-27)

In-depth review of `webapp/` (Vue 3 + Pinia + TS SPA). Three parallel review passes — architecture/quality, security, correctness — plus quality-gate run.

> **Update — fixes landed on branch `fix/webapp-review-batch`:** C1, C2, C3, F1, S1, S3, A1
> are FIXED + tested (webapp 58 tests / backend 240 tests green; both format gates green).
> Remaining open (not in this batch): S2 (no-auth CSRF, by design), S4 (CSP), S5
> (`ticket.url` scheme), A2–A7 quality items. See per-item status tags below.

**Threat model:** single-operator local tool. Backend `127.0.0.1:4000`, webapp dev `127.0.0.1:5173`, Vite proxies `/api/*`. Only attacker-controlled input = Intercom conversation content typed by customers. No auth by design.

## Quality gate status

| Gate | Result |
|------|--------|
| `npm run lint` | ✅ pass (0 warnings) |
| `npm run typecheck` | ✅ pass |
| `npm test` | ✅ 49 tests, 8 files pass |
| `npm run build` | ✅ built (402 KB js / 141 KB gzip) |
| `npm run format:check` | ❌ **53 files flagged — CRLF vs LF, see F1** |

## Verdict on "is the auth/trust model breakable?"

There is **no authentication at all** between webapp and backend — deliberate, documented single-operator-localhost choice. The only protection is the backend binding to `127.0.0.1`. Real residual exposure: a malicious website the operator visits can fire unauthenticated *state-changing* cross-origin requests (`POST /tickets/{id}/resolve`, `/reopen`, multipart `/attachments`) — CORS hides the *response* but not the *write* (see S2). No remote XSS, no secret leakage, no token anywhere. XSS of customer content is **well-defended** (double layer: extension `stripHtml` on ingest + Vue auto-escape on render; zero `v-html` in codebase).

---

## CRITICAL / HIGH

### C1 — `silentRefresh()` clobbers in-flight optimistic mutations  — **Critical**
`src/App.vue` auto-sync + `src/stores/tickets.ts:132-146`
Auto-sync skips only when `tickets.loading` is true, but `loading` is set **only** by `refresh()`. None of the optimistic mutators (`markResolved`, `applyOverride`, `editTicket`, `reopen`, `bulk*`) set it. So an auto-sync tick landing mid-mutation wholesale-replaces both ticket arrays with server state that doesn't yet reflect the pending write. Failure modes:
- Optimistic card jumps back to old column for a frame (flicker).
- A just-resolved ticket reappears in the open column (POST not yet committed server-side).
- **Index-based rollback corruption**: `markResolved`/`reopen` capture `idx` then `splice(idx, 0, original)` on failure — but the array was replaced by the refresh, so `idx` is meaningless → wrong-position reinsert or lost row.
- `pendingOverrides` is never reconciled against the refreshed list → grows unbounded across the session.
**Fix:** add a `mutating` counter (increment at top of each optimistic action, decrement in `finally`); `silentRefresh()` and the visibilitychange handler early-return when `>0`. Index rollbacks should re-find by id, not trust captured `idx`. Prune `pendingOverrides` against fresh list.

### C2 — `snooze()` drops banner before the await, no rollback — **High**
`src/stores/followups.ts:169-173`
```js
async function snooze(ticketId, minutes) {
  dismissBanner(ticketId);                      // banner gone immediately
  const saved = await api.snoozeFollowup(...);   // if this throws…
  map.value = { ...map.value, [ticketId]: saved };
}
```
On API failure the banner is gone but `due_at` stays in the past and `fired` stays false → next `tick()` (1 Hz) re-qualifies it as due and **re-fires the banner every second** in a loop. Caller `AlarmBanners.vue` uses fire-and-forget `void followups.snooze(...)` with no `.catch` → unhandled rejection. Every other followups mutator snapshots + rolls back; `snooze` is the lone exception.
**Fix:** snapshot `previous`, optimistic update before await, `rollback` + re-raise banner in `catch`. Add `.catch` in `AlarmBanners.vue`.

### C3 — `tick()` has no banner-dedup guard — **Medium/High**
`src/stores/followups.ts:218-232`
`tick()` pushes a new banner unconditionally for any `!f.fired && due_at<=now`. After a reschedule-to-past (`rescheduleToBucket` → `setFollowup` sets `fired:false` with a past `due_at`) a second banner stacks for a ticket that already has one → duplicate `:key` render warning + `banners` array bloat.
**Fix:** `if (banners.value.some(b => b.ticketId === f.ticket_id)) continue;` before push.

---

## SECURITY (all LOW–MEDIUM given local-only model)

### S1 — Attachments served `inline` with client-controlled mime — **Medium**
`backend/app/routers/attachments.py:91-96` serves bytes with `media_type=row.mime` (client-supplied) and `content_disposition_type="inline"`. `AttachmentList.vue` opens `raw_url` in a new tab. An uploaded `text/html` or SVG executes script in the backend origin. Mitigating: only the *operator* uploads (no customer upload path) → self-XSS / tricked-operator, not remote.
**Fix:** `Content-Disposition: attachment` (force download) + `X-Content-Type-Options: nosniff` + mime allowlist.

### S2 — No auth → CSRF-reachable state-changing writes — **Low–Medium**
No `Authorization` header anywhere (`src/api/client.ts`). CORS (`allow_credentials=False`) blocks reading responses cross-origin but not the side effects of simple/near-simple requests. `resolve`/`reopen` (empty body) and multipart upload are candidates a malicious page could fire.
**Fix (if hardening):** require a custom header (`X-Requested-By`) on mutating routes to force a preflight, or check `Origin`. Defensible to leave under the documented model.

### S3 — No attachment file-type allowlist or size cap — **Medium**
`AttachmentDropzone.vue` accepts any file; backend `await file.read()` loads whole file into memory (local DoS via huge file). Trusts client `content_type`.
**Fix:** client + server size cap, mime allowlist.

### S4 — No CSP header; external font origin loaded — **Low**
`index.html` ships no CSP, loads Google Fonts. No current sink to exploit, but CSP is the standard backstop if `v-html` is ever added.

### S5 — `ticket.url` rendered as `href` without scheme validation — **Low**
`TicketHeader.vue:189` binds Intercom-derived `:href`. URL is extension-constructed (not free-typed), so low risk; validate `https://` prefix as defense-in-depth.

**Checked clean:** no `v-html`/`innerHTML`/`eval` anywhere · conversation content double-escaped · no secrets in source or `dist/` · no Intercom token · `rel="noopener"` on all `target=_blank` · no path traversal (attachments content-addressed by sha256) · localStorage holds only display prefs.

---

## ARCHITECTURE / QUALITY

### A1 — `editTicket` silently no-ops on resolved tickets — **Medium**
`src/stores/tickets.ts:156-190` searches only `state.value.tickets` (open list). The flyout can display *resolved* tickets; editing a resolved ticket's title → `findIndex` returns -1 → edit silently does nothing, no error surfaced.
**Fix:** search both lists like `setAiResolve`/`dismissChip` do, or surface the no-op.

### A2 — `Ticket.note` field is dead on the read path — **Medium**
`src/types/api.ts:144` — `Ticket.note` arrives in every `/tickets` payload but nothing reads it; the card/flyout read from the standalone `notes` store instead. Three note channels (`Ticket.note`, `notes` store, `noteEntries` store), one unused. Deliberate keep-or-cut decision needed (ties to the documented notes/noteEntries debt).

### A3 — `ticketsForColumn` re-sorts on every render, twice per column — **Medium (perf)**
`src/components/Board.vue:29-50` is a plain function (not `computed`); `[...list].sort()` runs per render, and `visibleColumns` calls it again → clone+sort ≥2× per column. The 1 Hz `followups.now` tick drives re-render → re-sorts every column once a second.
**Fix:** memoize into a `computed` map, or move the due-pinning sort into the store getter.

### A4 — `TicketCard` not keyboard-accessible — **Medium (a11y)**
`src/components/TicketCard.vue` opens flyout on `@click` from an `<article>` with no `tabindex`/`role`/keydown. Core "open ticket" action unreachable by keyboard. Same for click-to-edit title in `TicketHeader`.

### A5 — `time.ts` parses naive (non-`Z`) datetimes as local — **Medium (latent)**
`src/utils/time.ts` + `followups.ts` use `new Date(iso)` / `Date.parse`. Correct **only** because backend Pydantic enforces the `Z` suffix (invariant #5). If any field ever ships naive, all relative times + alarm firing shift by the UTC offset, with no test catching it.
**Fix:** add `time.spec.ts` covering Z vs naive; optionally normalize defensively.

### A6 — DESIGN.md vs flyout drift — **Low/Medium (doc)**
`TicketFlyout.vue` is a centered modal (`min(1240px,96vw)`, `border-radius:14px`, scale-pop) but DESIGN.md specifies a 480px right-anchored slide-in with 4px radius ("no radius above 4px"). Doc and code contradict — reconcile per the project's "DESIGN.md is source of truth" rule.

### A7 — Minor — **Low**
- Hardcoded `#c34a2b` in `TicketCard.vue:49` `confColor` (should be a `--confidence-low` token).
- `as unknown as` double-cast in `BulkActionBar.vue:80` `runBulk` defeats the typed `BulkResult` — constrain `T extends BulkResult`.
- `setAiResolve`/`dismissChip` mutate fields in place vs the store's immutable-replace pattern (works via deep reactivity, but inconsistent + no snapshot).

---

## PROCESS

### F1 — `format:check` gate is red on Windows (CRLF vs LF) — **Medium**
Git stores files as `lf` but checks out `crlf` on Windows (`autocrlf`), there's **no `.gitattributes`**, and `.prettierrc.json` has no `endOfLine` → prettier defaults to `lf` and flags all 53 files. The operator **cannot pass `npm run format:check` locally on Windows** (CI/Linux would pass). This is the cross-package format gate currently failing.
**Fix:** add repo-root `.gitattributes` with `* text=auto eol=lf` and renormalize (`git add --renormalize .`), or set prettier `"endOfLine": "auto"`. Pick one and apply repo-wide.

---

## TEST COVERAGE GAPS (highest value first)

Only `tickets.spec.ts` exists for the tickets store, covering just `markNonActionable` + resolved getters. **No spec** for `followups.ts`, `categories.ts`, `notes.ts`, `settings.ts`, `tweaks.ts`, `view.ts`.
1. Auto-sync vs optimistic-mutation race (C1) — most dangerous untested path.
2. The six untested `tickets` rollback paths (`markResolved`, `reopen`, `applyOverride`, `editTicket`, `bulkResolve`, `bulkReopen`/`bulkRecategorize`).
3. `followups.ts` `tick()` / `snooze` / `bucketOf` (C2/C3) — entirely untested.
4. `time.ts` Z-suffix handling (A5).

---

## Recommended order

1. **C1** mutation-in-flight guard (data-corrupting race).
2. **C2** snooze rollback + `AlarmBanners` `.catch` (visible re-fire loop).
3. **F1** `.gitattributes`/prettier (unblocks the format gate on Windows).
4. **S1 + S3** attachment serving + upload caps (cheapest real security hardening).
5. **C3, A1** then the rest.

Nothing is critically broken in normal use; the build and tests are green. C1 and C2 are the two paths most likely to misbehave once auto-sync is on.
