# Slack Bug Alerts — Manual Test Runbook

> Run this **before** merging. The automated suite (630 backend tests) mocks
> OpenRouter and Slack, so it can prove the plumbing and prove nothing about
> **detection quality** or **whether Slack actually accepts the message**. Those
> are exactly the two things that go wrong.
>
> Design: [`../specs/2026-08-13-slack-bug-alerts-design.md`](../specs/2026-08-13-slack-bug-alerts-design.md) ·
> Plan: [`2026-08-13-slack-bug-alerts.md`](./2026-08-13-slack-bug-alerts.md)

---

## Part 1 — Slack setup (do this first, ~5 minutes)

You need a **bot token** (`xoxb-…`). An incoming webhook will not work: it
returns no message `ts`, so escalation replies cannot be threaded. The client
refuses to use one.

### 1. Create the app

1. Go to <https://api.slack.com/apps> → **Create New App** → **From scratch**.
2. Name it (e.g. `Triage Bug Alerts`), pick your workspace → **Create App**.

### 2. Add the bot scopes

1. Left sidebar → **OAuth & Permissions**.
2. Scroll to **Scopes** → **Bot Token Scopes** → **Add an OAuth Scope**.
3. Add:
   - `chat:write` — required, lets the bot post.
   - `chat:write.public` — optional but recommended; lets it post to a public
     channel it has **not** been invited to. Skip this only if you plan to
     invite the bot manually (step 4).

> Add these under **Bot** Token Scopes, not User Token Scopes. A user token
> (`xoxp-`) posts as *you*, not as the app.

### 3. Install and copy the token

1. Scroll up on the same page → **Install to Workspace** → **Allow**.
2. Copy the **Bot User OAuth Token**. It starts with `xoxb-`.

> Treat it like a password. It goes in `backend/.env`, which is gitignored, and
> the repo's gitleaks rule will block a commit containing one.

### 4. Create / pick the channel and get its ID

1. Create a channel, e.g. `#bug-alerts` (private works too).
2. **If the channel is private, or you skipped `chat:write.public`:** invite the
   bot — type `/invite @Triage Bug Alerts` in the channel. Without this you will
   get `not_in_channel` or `channel_not_found`.
3. Get the channel **ID**: click the channel name → scroll to the bottom of the
   **About** tab → copy the ID (looks like `C0123ABCDEF`).

> Use the ID, not `#name`. `#name` works but breaks silently on a rename.

### 5. Wire it into `backend/.env`

```dotenv
BUG_ALERTS_ENABLED=true
SLACK_BOT_TOKEN=xoxb-your-token-here
SLACK_BUG_CHANNEL=C0123ABCDEF
BUG_ALERT_MIN_SEVERITY=medium
BUG_ALERT_MIN_CONFIDENCE=0.6
# Keep delivery OFF for now — Part 2 checks detection quality first.
BUG_ALERT_POLL_INTERVAL_SECONDS=0
BUG_ALERT_MAX_PER_CYCLE=10
```

Restart the backend, then confirm:

```bash
curl -s http://127.0.0.1:4000/health
```

Expect `"slack_configured": true` and `"status": "ok"` — Slack is deliberately
**not** in `missing_secrets`, so an unconfigured Slack never marks the service
degraded.

---

## Part 2 — Detection quality (no Slack posting yet)

Delivery is off, so nothing can reach the channel. This part answers: *is the
model any good at this?*

### Get an auth token for curl

Every route except `/health` and `/auth/*` is gated. Either log in through the
webapp and copy the bearer token, or mint a dev one:

```bash
cd backend
./.venv/Scripts/python.exe -c "
from app.config import get_config
from app.security.tokens import mint_access_token
c = get_config()
print(mint_access_token(c.session_jwt_secret, user_id=1, onlysales_id='dev',
      email='dev@local', scope='admin', ttl_seconds=3600))
"
```

```bash
export TOKEN="paste-it-here"
```

### 2a. Fast synthetic check (no Intercom, no AI cost if you want it cheap)

Post a handcrafted conversation straight into ingest and see whether it gets
flagged. This exercises prompt → parse → cache → record end to end.

```bash
curl -s -X POST http://127.0.0.1:4000/tickets/ingest \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '[{
    "id": "manual-bug-1",
    "title": "Export button does nothing",
    "state": "open",
    "priority": null,
    "created_at": "2026-08-13T09:00:00Z",
    "updated_at": "2026-08-13T09:00:00Z",
    "author": {"type": "user", "name": "Test Customer", "email": "t@example.com"},
    "url": "https://example.com/conv/manual-bug-1",
    "parts": [{
      "body": "I click Export to CSV and absolutely nothing happens. No file, no error. It worked yesterday. Every one of my 40 reports is stuck.",
      "created_at": "2026-08-13T09:00:00Z",
      "author": {"type": "user", "name": "Test Customer", "email": "t@example.com"},
      "is_admin": false
    }],
    "internal_notes": []
  }]'
```

Then read it back:

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:4000/bug-alerts
```

**Expect** one row: `severity` `high` or `medium`, a confidence, and `evidence`
containing the customer's actual words, `posted_at: null`.

Now post the **same payload again** and re-read. **Expect** still exactly one
row, with `occurrences` now `2`. That is the dedup guarantee — the primary key
makes a second row impossible.

Also send a non-bug (a billing question, a "how do I…") and confirm it produces
**no** row. False positives are what destroy channel trust.

### 2b. Real traffic

Run a real Intercom sync (Topbar **Sync** button, or `POST /tickets/sync`), then
read `/bug-alerts` again and judge by hand:

- Are the flagged tickets **actually** bug reports? (false-positive rate)
- Are obvious bugs being **missed**? (false-negative rate)
- Is `evidence` a real verbatim quote, or a paraphrase the model invented?
- Is the severity split sane, or is everything `medium`?

**Results of the first live run (2026-08-13, 14 detections / 13 posted / 0
duplicates).** Both remaining questions failed, and both were fixed (T179):

- **1 of 14 quotes was our own support agent**, not the customer. Now enforced in
  code (`verify_bug_evidence`), not just requested in the prompt. Audit a run
  yourself with the query below.
- **13 of 14 compressed to `medium`, 0 `high`** — the rubric read `high` as
  "platform-wide outage", so per-customer breakage never tripped it. Rubric
  widened; re-check the split on the next run.

Audit evidence provenance on any run:

```bash
cd backend
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -c "
import sqlite3, json, re
def norm(s): return ' '.join((s or '').casefold().split())
c = sqlite3.connect('data/triage.db')
for tid, sev, ev in c.execute('select ticket_id, severity, evidence from bug_alerts'):
    if not ev: continue
    row = c.execute('select parts from tickets where id=?', (tid,)).fetchone()
    parts = json.loads(row[0]) if row else []
    e = norm(ev)
    src = next((('ADMIN!!' if p.get('is_admin') else 'customer')
                for p in parts if e in norm(p.get('body'))), 'NEITHER!')
    print(src, sev.ljust(6), tid, '|', ev[:80])
"
```

Every line should read `customer`. An `ADMIN!!` or `NEITHER!` after T179 means
the guard regressed.

> **Nothing changed, nothing detected.** Sync skips unchanged conversations
> server-side, and conversations categorized before migration 0027 carry no
> verdict (there is no backfill, by design). If `/bug-alerts` is empty, that is
> expected — either wait for new traffic, or against a **dev** database force a
> re-read with `DELETE FROM tickets;` followed by an unbounded sync.

### 2c. Categorization drift — the one the test suite cannot see

The AI tests use canned responses, so they cannot detect that adding a fifth
judgement made the model worse at the first four. This is the same blind spot
that let the `json_schema` → 400 regression ship green.

Compare categories and summaries on the same tickets before and after. If
categorization visibly degraded, the fifth facet is too much for one call and
detection needs its own (paid) call — stop and say so rather than shipping it.

### 2d. Re-pick the confidence floor

`BUG_ALERT_MIN_CONFIDENCE=0.6` is an **admitted guess** — unlike the
needs-review threshold, which is calibrated against a labelled corpus. Look at
the confidences you actually got and set it where it separates the real reports
from the noise. Only then continue.

---

## Part 3 — Slack end-to-end

Turn delivery on:

```dotenv
BUG_ALERT_POLL_INTERVAL_SECONDS=60
```

Restart. Within a minute you should see a post in the channel.

Check each of these:

| # | Do this | Expect |
|---|---|---|
| 1 | Wait one interval | A card lands with a severity-coloured left rail: emoji + severity + the title as a link to the conversation; the customer quote blockquoted; reporter name / email / user id / location; ticket state + age; owner; the AI summary; then category · confidence · seen-count · priority · sentiment · labels · ticket id |
| 2 | Wait another interval | **No second post.** `posted_at` is now set; the outbox is empty |
| 3 | Re-run the same sync / re-post the synthetic ticket | **Still no second post** — occurrences bumps, delivery does not |
| 4 | Raise a severity by hand: `UPDATE bug_alerts SET severity='high' WHERE ticket_id='manual-bug-1';` | A short **threaded reply** under the original message ("⬆️ Escalated medium → high"), not a new card |
| 5 | Lower it back to `medium` | Nothing posted |
| 6 | `POST /bug-alerts/manual-bug-1/dismiss`, then create a fresh detection for it | Nothing posted, ever again |
| 7 | Break the token (`SLACK_BOT_TOKEN=xoxb-nope`), restart, let a new alert accrue | Nothing posted; rows stay `posted_at: null`; a warning is logged |
| 8 | Restore the token, restart | The held alerts post — the outbox self-healed across a restart |
| 9 | Grep the backend log for a phrase from a customer quote | **Zero hits.** Evidence text must never reach a log line (NFR-016) |
| 10 | Watch a sync while Slack is slow/broken | Sync latency is unaffected — delivery is a separate loop and is never called inside `SYNC_LOCK` |

### Results of the live Part 3 run (2026-08-13)

All ten checks executed against the real workspace. Synthetic tickets
`manual-bug-1` / `manual-bug-2` were ingested through `POST /tickets/ingest` for
the checks that need controlled state.

| # | Result |
|---|---|
| 1 | Card posted for `manual-bug-1` (`high`, 0.95, verbatim customer quote, `ts 1786610549.685039`) |
| 2–3 | Re-posting the identical payload bumped `occurrences` 1→2 and posted **nothing**; Slack post count held at 4 across 2.5 poll cycles |
| 4 | Verified on real traffic: two tickets escalated `medium`→`high`, both landed as threaded replies with `slack_ts` unchanged |
| 5 | `severity` lowered below `posted_severity` → nothing posted |
| 6 | Dismissed, then re-armed under **both** delivery branches at once (`posted_at=NULL` *and* `severity` > `posted_severity`) → nothing posted. A genuine re-detection (new customer message → new content signature → real AI call) bumped `occurrences` to 3 and left `dismissed_at` intact |
| 7 | `SLACK_BOT_TOKEN=xoxb-nope` → three cycles of `bug_alert_delivery_auth_error` (WARNING), `posted_at` stayed `NULL`, pass aborted after the first row |
| 8 | Token restored + restart → the held alert drained on the next cycle (`posted_at 08:55:35Z`, new `ts`) — the outbox self-healed across a process restart |
| 9 | Every stored `evidence` string probed against the full backend log in overlapping 6-word windows: **0 hits** |
| 10 | Ingest latency unchanged while the token was broken — delivery failed in its own loop |

> **Reading the log during check 7.** A rejected post still emits
> `external_call op=slack.post_message outcome=ok`, because `logged_call` wraps
> only the HTTP request and Slack reports `invalid_auth` as HTTP 200. The line
> that tells the truth is the `bug_alert_delivery_auth_error` WARNING beside it.
> Do not read `outcome=ok` as "Slack accepted it".

### Common Slack errors and what they mean

| Error in the log | Cause | Fix |
|---|---|---|
| `invalid_auth` | Token wrong, revoked, or a user token | Re-copy the **Bot User OAuth Token** (`xoxb-`) |
| `channel_not_found` | Wrong ID, or a private channel the bot cannot see | Check the ID; `/invite` the bot |
| `not_in_channel` | Bot not a member and `chat:write.public` not granted | `/invite` the bot, or add the scope and reinstall |
| `missing_scope` | `chat:write` not granted | Add the scope, then **reinstall** the app (scope changes need reinstall) |
| `ratelimited` | Too many posts | Automatic — it backs off and retries. Lower `BUG_ALERT_MAX_PER_CYCLE` if persistent |

---

## Part 4 — Sign-off

- [x] `/health` reports `slack_configured: true`, `status: ok`, Slack absent from `missing_secrets`
- [x] Detection flags real bugs and leaves non-bugs alone (2b)
- [x] Evidence quotes are verbatim, not paraphrased (2b)
- [x] Every evidence quote is attributed to the **customer**, never an agent (2b audit query)
- [x] The severity split is not entirely `medium` (2b) — `3 high / 12 medium / 1 low`
- [ ] Categorization quality did **not** degrade (2c) — **outstanding**, needs an operator eye on the board
- [ ] `BUG_ALERT_MIN_CONFIDENCE` re-picked from observed data (2d) — **outstanding**; `0.6` has rejected nothing, observed range 0.65–0.95
- [x] All ten Part 3 checks pass, especially #2, #3 and #6 (no duplicate posts)
- [x] No evidence text anywhere in the logs (#9)
- [x] `alembic current` → `0027`, `alembic heads` → single head
- [x] Backend gate green (`ruff` + `format` + `mypy` + `pytest`) — 643 passed
- [ ] Webapp gate green (unchanged in v1, run it to prove that)
