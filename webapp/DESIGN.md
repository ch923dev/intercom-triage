---
version: alpha
name: Intercom Triage
description: Operator-facing kanban board for triaging Intercom conversations. Premium-broadsheet aesthetic — warm neutrals, ink typography, a single hot accent, hairline borders.
colors:
  bg: "#faf9f6"
  panel: "#ffffff"
  ink: "#111111"
  ink-2: "#555555"
  ink-3: "#8a8a82"
  line: "#e6e3db"
  line-soft: "#efece4"
  chip-bg: "#f3efe6"
  hover: "#f5f2ea"
  accent: "#ff4d2e"
  accent-soft: "rgba(255,77,46,0.08)"
  accent-soft-2: "rgba(255,77,46,0.12)"
  bg-dark: "#0e0f0e"
  panel-dark: "#15161a"
  ink-dark: "#f5f4ef"
  ink-2-dark: "#a3a39d"
  ink-3-dark: "#6a6a64"
  line-dark: "#26282d"
  line-soft-dark: "#1e2025"
  chip-bg-dark: "#1c1d22"
  hover-dark: "#1a1b20"
typography:
  display:
    fontFamily: Geist
    fontSize: 14px
    fontWeight: 600
    lineHeight: 1
  body-md:
    fontFamily: Geist
    fontSize: 13.5px
    lineHeight: 1.35
  body-sm:
    fontFamily: Geist
    fontSize: 12.5px
    lineHeight: 1.45
  meta:
    fontFamily: Geist
    fontSize: 11px
    lineHeight: 1.2
  label-caps:
    fontFamily: JetBrains Mono
    fontSize: 10.5px
    fontWeight: 500
    letterSpacing: 0.04em
  mono-micro:
    fontFamily: JetBrains Mono
    fontSize: 9px
    fontWeight: 500
    letterSpacing: 0.04em
rounded:
  hairline: 0px
  chip: 3px
  card: 4px
  pill: 999px
spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 20px
  column: 280px
  column-gap: 16px
  flyout: 480px
components:
  card:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    typography: "{typography.body-md}"
    rounded: "{rounded.card}"
    padding: 12px
    width: 256px
  card-hover:
    backgroundColor: "{colors.hover}"
  card-selected:
    backgroundColor: "{colors.accent-soft}"
  column:
    backgroundColor: "{colors.bg}"
    width: 280px
    padding: 14px
  column-header:
    textColor: "{colors.ink-2}"
    typography: "{typography.label-caps}"
    padding: 14px
  chip:
    backgroundColor: "{colors.chip-bg}"
    textColor: "{colors.ink-2}"
    typography: "{typography.mono-micro}"
    rounded: "{rounded.chip}"
    padding: 2px 6px
  chip-accent:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.accent}"
    typography: "{typography.mono-micro}"
    rounded: "{rounded.chip}"
    padding: 3px 9px
  cat-dot:
    rounded: "{rounded.pill}"
    height: 8px
    width: 8px
  search-input:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    typography: "{typography.meta}"
    rounded: "{rounded.chip}"
    padding: 4px 10px
    width: 320px
  topbar:
    backgroundColor: "{colors.bg}"
    padding: 12px 20px
    height: 48px
  flyout:
    backgroundColor: "{colors.panel}"
    width: 480px
  banner-alarm:
    backgroundColor: "{colors.accent-soft-2}"
    textColor: "{colors.accent}"
    rounded: "{rounded.card}"
    padding: 12px
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.panel}"
    typography: "{typography.label-caps}"
    rounded: "{rounded.chip}"
    padding: 6px 12px
  button-ghost:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink-2}"
    typography: "{typography.label-caps}"
    rounded: "{rounded.chip}"
    padding: 6px 12px
  button-ghost-hover:
    backgroundColor: "{colors.hover}"
---

## Overview

**Premium broadsheet meets operator console.** The board is a horizontal kanban of triaged Intercom conversations — dense, fast-keyed, alarm-aware. The visual language borrows from print journalism (warm off-white paper, ink-black headlines, single hot accent for action) rather than from SaaS dashboards (no chrome, no gradients, no rounded "fun" shapes).

Operators live in this UI for hours. Every choice optimizes for sustained scanning:

- **Warm paper background, never pure white.** Cuts retinal glare on long sessions.
- **One accent color (Boston Clay red).** Reserved exclusively for state that demands action — overdue follow-ups, pending overrides, the "fire" beat. Never decorative.
- **Hairline borders (0.5px), not weight.** Separation comes from `--line` rules and whitespace, not card elevation. Shadows appear only on lifted surfaces (flyout, dropzone overlay).
- **Mono micro-labels in JetBrains Mono.** Used for state and meta (counts, timestamps, category names, footer). Geist carries everything human-readable.

Dark mode is a first-class peer, not an afterthought. The token table doubles the palette with `-dark` keys; live switching toggles `html[data-theme]`.

## Colors

Two palettes, swapped via `data-theme`. Light is default.

### Surfaces

- **bg (`#faf9f6` / `#0e0f0e` dark)** — Warm off-white paper. The board, the column gutters, the body. Never pure white in light mode; never pure black in dark.
- **panel (`#ffffff` / `#15161a` dark)** — Cards, flyout, search input, popovers. The lifted surface against `bg`.
- **chip-bg (`#f3efe6` / `#1c1d22` dark)** — Pills, chips, mono labels. Sits between `bg` and `panel` on the warmth ramp.
- **hover (`#f5f2ea` / `#1a1b20` dark)** — Hover state for clickable surfaces. Always subtle; never the accent.

### Ink

A three-tier neutral hierarchy, ink-to-mist.

- **ink (`#111111` / `#f5f4ef` dark)** — Headlines, ticket titles, primary text.
- **ink-2 (`#555555` / `#a3a39d` dark)** — Body, summaries, column headers.
- **ink-3 (`#8a8a82` / `#6a6a64` dark)** — Meta, timestamps, footer, scrollbar hover.

### Lines

- **line (`#e6e3db` / `#26282d` dark)** — Hairline borders between columns, cards, drawer edges.
- **line-soft (`#efece4` / `#1e2025` dark)** — Subdivider inside a card. Half the visual weight of `line`.

### Accent

- **accent (`#ff4d2e`)** — Boston Clay. The single interaction/alarm color. Identical in both themes; the palette around it shifts, but the hot signal stays constant.
- **accent-soft (`rgba(255,77,46,0.08)`)** — Hover/selection background tint.
- **accent-soft-2 (`rgba(255,77,46,0.12)`)** — Alarm banner background, "ringing" state.

WCAG: `ink` on `bg` ≈ 18:1 (AAA). `ink-2` on `bg` ≈ 7.3:1 (AAA). `accent` on `panel` ≈ 4.0:1 (AA large only — confine to interactive chips ≥ 10.5px label-caps, never body copy).

## Typography

Two families, no more. **Geist** for prose. **JetBrains Mono** for any label that names a state, a count, or a category. The mono/sans contrast is the second-most-loaded signal after the accent color.

| Token         | Family          | Size    | Weight | Use                                          |
|---------------|-----------------|---------|--------|----------------------------------------------|
| `display`     | Geist           | 14px    | 600    | Topbar wordmark, flyout title                |
| `body-md`     | Geist           | 13.5px  | 400    | Ticket title on a card                       |
| `body-sm`     | Geist           | 12.5px  | 400    | Summary, conversation body                   |
| `meta`        | Geist           | 11px    | 400    | Timestamps, author name, footer status       |
| `label-caps`  | JetBrains Mono  | 10.5px  | 500    | Column headers, button labels, footer keys   |
| `mono-micro`  | JetBrains Mono  | 9px     | 500    | Chips, badges, category name on a card       |

**Rules:**
- Mono labels are uppercase with `0.04em` tracking. Never use mono lowercase.
- Geist headlines are never bolder than 600. Weight 700 is reserved for the wordmark in the topbar.
- Line-height stays tight on titles (1.35) and looser on summaries (1.45). Don't shrink leading to fit more rows — let the card grow.

## Layout

A single horizontally-scrolling board. Columns are fixed-width; the page never reflows responsively.

- **Column width:** 280px. Card width: 256px (column padding 14px × 2). One column = one category (or one of the always-on system columns: Resolved, proposal staging).
- **Column gap:** 16px. The gap is `--bg`, not a divider — separation is whitespace, not a line.
- **Card vertical rhythm:** 8px between cards. 12px internal padding. Cards never exceed ~5 lines of body before the summary truncates.
- **Topbar:** 48px fixed height, full width, hairline-bottomed. Hosts wordmark, view toggle pills, search (320px), tweaks, and the status pill.
- **Footer:** 1-line, hairline-topped, mono-only. Carries last-sync meta and keyboard hints.
- **Flyout:** 480px right-anchored panel. Slides in over the board; never replaces it.
- **Drawer (settings):** mirrors flyout dimensions on the right.
- **Banners (alarms):** stack top-right of the board, below the topbar. Each banner is full chip-width, accent-soft-2 background.

Keyboard is a first-class layout citizen: `←/→` scroll one `column-step` (296px = 280 + 16), `/` focuses search, `r` refreshes, `Esc` peels back state (clear search → clear selection → close flyout).

## Elevation & Depth

Elevation is **rare** and **earned**. Most surfaces sit flat on `bg` separated by `line`.

| Level | When                              | Shadow                                          |
|-------|-----------------------------------|-------------------------------------------------|
| 0     | Cards, columns, topbar, footer    | none — separation via `--line` hairline only    |
| 1     | Flyout, settings drawer           | `0 12px 32px rgba(40,30,20,0.1)` (`--shadow`)   |
| 1     | Attachment dropzone overlay       | `--shadow`                                      |
| 2     | Alarm "ringing" state             | radiating `triageRing` keyframe (accent halo)   |

No stacked z-axis games. Either it's flush, or it's floated — nothing in between.

## Shapes

The geometry is rectilinear and quiet.

- **hairline (0px)** — Hairline-separated surfaces (topbar, footer, column dividers). No corner radius at all.
- **chip (3px)** — Chips, pills, badges, search input, buttons. The "small printed sticker" radius.
- **card (4px)** — Cards, banner, flyout panels. One step up from chip; reads as paper, not as a balloon.
- **pill (999px)** — Status dots, count badges, the CatDot category swatch. Reserved for things that read as a dot or capsule by silhouette.

No radius above 4px on any rectangular surface. Anything that wants to be round goes all the way to a pill — never half-rounded.

## Components

### Cards (`TicketCard`)

Flat panel, 256×auto, `card` radius, hairline border. Hover swaps to `hover` background. Bulk-selected uses `accent-soft` background and a 2px accent left-rule. Cards open the flyout on click; drag re-categorizes.

### Columns (`Column`, `ResolvedColumn`, `FollowupColumn`)

Fixed 280px width, `bg` surface (not `panel` — they're channels in the paper, not lifted surfaces). Header is `label-caps`, ink-2, with the live count as a `chip` to the right. Empty columns collapse to a 24×8 padding stub when `settings.hide_empty_categories` is on.

### Chips & dots (`Mono`, `CatDot`, `ResolutionChip`)

- **Mono chip** — `chip-bg` background, `mono-micro` typography, 2×6 padding. Carries category names, counts, "AI" / "OVR" / "FIRED" labels.
- **CatDot** — 8×8 `pill`, color sourced from the category's `color` field. Sits left of the title on every card.
- **ResolutionChip** — `chip-accent` styling. Three states: `ai_resolved`, `ai_reopened`, `new_reply`. Dismissible.

### Buttons

There are no traditional buttons in body content. Actions live on chips and icon-only ghost buttons.

- **Primary** — accent background, panel text, `chip` radius. Used sparingly: bulk-action confirms, "Sync now" in the extension callout.
- **Ghost** — panel background, ink-2 text, `chip` radius, hover lifts to `hover`. Used for dismiss, snooze, settings toggles.

### Flyout (`TicketFlyout` + `components/ticket/*`)

Right-anchored 480px panel, `panel` surface, `--shadow` elevation. Contains: `TicketHeader` (title + meta + customer identity: name / email / Intercom user ID + state), `TicketConversation` (alternating customer/admin parts), `TicketEntryForm` + `TicketEntryTimeline` (time-tabled notes), `TicketFollowup` (due-at picker), `TicketAttachmentBin`, `TicketResolution`, `TicketCategoryPicker`. Each subcomponent owns its own border-bottom hairline; nothing stacks shadows.

Detail-pane sections (Category, Follow-up, Next-step notes, Playbooks, Resolution) wrap in `CollapsibleSection` — the `.block` hairline + mono `label-caps` header become a click target with a rotating `▾` chevron (ink-3). Collapsed state is sticky per section (`localStorage` key `triage.flyout.collapse.<section>`), shared across tickets, not per-ticket.

### Banners (`AlarmBanners`)

Top-right stack of `banner-alarm` chips. Each banner enters via `triageSlide` (20px right → 0, fade in). The active banner pulses (`triagePulse`) until acknowledged.

### Search input

320px, `chip` radius, panel surface. Live-filters `tickets.visibleTickets` against title/summary/author. `/` focuses it; first `Esc` clears + blurs.

## Do's and Don'ts

**Do**
- Reach for the accent only for action or alarm. Overdue follow-up = accent. Pending category override = accent. Selected row = accent. Everything else stays in the neutral ramp.
- Use hairline borders (`var(--hairline) solid var(--line)`) for separation. Whitespace + a 0.5px rule reads as more premium than a heavier 1px line.
- Keep mono labels uppercase, ≤ 11px, with the `0.04em` tracking. They're a typographic system, not stylistic flair.
- Test every color change in both themes. The dark palette is not an inversion — `ink-3` shifts on the warmth axis, not the brightness axis.
- Use tokens (`var(--ink-2)`, `var(--radius-card)`). Hex literals in component CSS are a regression.

**Don't**
- Don't introduce a second accent color. There is one hot color. Status colors (red/yellow/green) belong on chips with mono labels, not as accents.
- Don't add gradients, blurred backdrops, or glass effects. The aesthetic is print, not iOS.
- Don't round corners above 4px on rectangles. If it wants to be round, make it a pill.
- Don't elevate cards. Shadows belong to lifted surfaces only (flyout, dropzone). Card hover is a background swap, not a lift.
- Don't add new fonts. Geist + JetBrains Mono is the entire system.
- Don't pad above 20px outside the topbar/footer. The board's density is a feature; loose padding breaks the scanning rhythm.
- Don't replace mono labels with lowercase Geist for "readability." The mono/sans contrast is load-bearing for instant state recognition.
