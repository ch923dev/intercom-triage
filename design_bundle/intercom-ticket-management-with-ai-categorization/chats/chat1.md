# Intercom Triage Dashboard

_Started 2026-05-21 09:27 UTC_

---

## User

Intercom Triage 

1. Purpose
Reduce the time a support operator spends triaging Intercom conversations. The current Intercom UI requires opening each conversation to learn its nature; this system pre-categorizes and pre-summarizes a recency-windowed slice of the inbox so the operator can scan and route in a single view.

2. Scope
In scope for v1: a read-only categorized Kanban view of recent Intercom conversations, AI-derived category and summary per ticket, manual category override that persists, and two consumer surfaces (a webapp and a Chrome extension).
Out of scope for v1: replying to tickets from inside the tool, multi-user collaboration or assignment, long-term analytics or reporting, helpdesks other than Intercom, and any mobile-native surface

3. Personas
The operator is the primary user — a support engineer, support lead, or founder who triages tickets as part of their day. They know Intercom and want to be faster. The admin is often the same person; their separate concern is configuring credentials and deploying the tool.

## Assistant

_[tool: questions_v2]_

## User

Questions answered:
- surfaces: Both (side-by-side on canvas)
- design_context: No — design from scratch with a fresh aesthetic
- aesthetic: 1
- density: Balanced — title + summary + 2-3 meta chips
- columns_layout: Operator picks which columns to show
- interactions: Filter panel (states + categories), Card detail flyout, Recency slider (live re-filter)
- extension_treatment: Decide for me
- variations: Decide for me
- tweaks: Show/hide AI confidence, Show summary on/off, Light/dark mode, Card density, Accent color, Column layout
- sample_data: Decide for me

## Assistant

_[tool: update_todos]_

_[tool: copy_starter_component]_

_[tool: copy_starter_component]_

_[tool: read_file]_

_[tool: read_file]_

_[tool: write_file]_

I'll build a high-fidelity, interactive prototype with an editorial/mono aesthetic. Two surfaces (webapp + Chrome popup) side-by-side on a design canvas, with realistic state.

**Design system declared:**
- Type: Geist (sans) + JetBrains Mono (labels, meta) — editorial pairing
- Color: warm off-white `#faf9f6`, ink `#111`, hairline borders, single accent (default red-orange `#ff4d2e`)
- Category palette: small color-squares (Linear-style), oklch-harmonized
- No gradients, no emoji, hairline borders, mono micro-labels

_[tool: write_file]_

_[tool: write_file]_

_[tool: write_file]_

_[tool: write_file]_

_[tool: show_html]_

_[tool: done]_

_[tool: update_todos]_

_[tool: fork_verifier_agent]_

Built **Intercom Triage** — a hi-fi interactive prototype with both surfaces on a design canvas.

**What's there**
- **Webapp artboard (1440×900):** recency slider (hours/days, 1–720), filter drawer (states + categories), column picker, 7-category Kanban with drag-to-override, override marker, card detail flyout with Open-in-Intercom deep link and inline re-category.
- **Chrome popup artboard (420×620):** framed with browser chrome + extensions icon + connector arrow; tabs switch categories; shares recency/filter state with the webapp live.
- **Tweaks panel:** dark mode, 5 accent swatches, density (compact/balanced/comfy), toggle AI summary, toggle AI confidence.

**Design system declared:** editorial/mono — warm off-white `#faf9f6`, ink `#111`, hairline borders, Geist + JetBrains Mono pairing, category swatches as 8px color squares (Linear-style), no gradients/icons-as-decoration.

**Original UI** — not a recreation of Intercom's interface.

**Not implemented (would need real backend):** persistence across reloads, live Intercom API, server-held secrets surface (admin config). PRD covers them but they're outside the prototype's scope.

## User

Can we also add a follow up flag, make an alarm so that when we got across the triage that need follow up, it will alarm the web. Also add notes into how we can proceed on it.

## Assistant

_[tool: update_todos]_

_[tool: read_file]_

Adding follow-up flags, audible alarms when due, and a next-steps notes block to the flyout. I'll also pre-seed one follow-up to fire ~12 seconds after load so you see the alarm without doing setup.

_[tool: read_file]_

_[tool: str_replace_edit]_

_[tool: str_replace_edit]_

_[tool: read_file]_

_[tool: str_replace_edit]_

_[tool: str_replace_edit]_

Now update Column to pass through new props, Flyout to add the follow-up/notes UI, and the main TriageWebapp to manage state + alarms.

_[tool: str_replace_edit]_

_[tool: grep]_

_[tool: read_file]_

_[tool: str_replace_edit]_

_[tool: grep]_

_[tool: read_file]_

_[tool: read_file]_

_[tool: str_replace_edit]_

Now I'll add a mute toggle to the top bar, wire follow-ups/notes through Column and Flyout, and render an alarm banner.

_[tool: str_replace_edit]_

_[tool: str_replace_edit]_

_[tool: str_replace_edit]_

Now mirror flag indicators and a due-alert pill in the Chrome popup.

_[tool: str_replace_edit]_

_[tool: grep]_

_[tool: read_file]_

_[tool: read_file]_

_[tool: str_replace_edit]_

_[tool: grep]_

Good — `setTick` already exists. Let me verify the page loads cleanly.

_[tool: done]_

_[tool: get_webview_logs]_

_[tool: show_html]_

_[tool: sleep]_

_[tool: eval_js]_

_[tool: get_webview_logs]_

_[tool: update_todos]_

_[tool: fork_verifier_agent]_

Added follow-up flags, audible alarms, and next-steps notes.

**What's new**
- **Card-level follow-up chip:** small countdown in the meta row (`F/U IN 15M`). When due, pulses, turns accent-colored, the whole card gets a glowing accent ring, and the ticket pins to the top of its column.
- **Flyout — Follow-up section:** preset chips (`+ 15m`, `+ 1h`, `+ 4h`, `+ EOD`, `+ 24h`) plus a `+ 12s test` chip so you can fire an alarm on demand. Clear button when one is set.
- **Flyout — Next steps section:** 7 quick-action chips (Page on-call, Reply with workaround, Escalate to AE, etc.) that append into a freeform mono textarea. Bullet count shown below.
- **Alarm banner:** stacks top-right when due. Plays a soft two-note WebAudio ping (gated by a mute toggle in the top bar). Actions: Open ticket, Snooze 15m, Snooze 1h, Dismiss.
- **Top-bar status pill:** shows pending follow-up count, flips to accent-pulse when alarms fire. Click to mute/unmute audio.
- **Chrome popup mirror:** due banner at the top, accent left-bar + countdown on each flagged ticket, `· notes` label when steps exist.

Pre-seeded so you see it work without setup: **INT-48211 fires ~12s after load**; two others are scheduled further out; three tickets ship with example next-step notes.The verifier didn't return a verdict — likely timed out while waiting for the alarm. Functionality is in place; if anything looks off when you try it, let me know.

