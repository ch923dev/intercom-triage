# Playbooks — design spec

**Status:** approved (brainstorm) — implementation plan pending
**Date:** 2026-05-26
**Author:** Christian + Claude

## Summary

Add **playbooks**: reusable next-steps recipes captured from a solved ticket and
surfaced on its siblings. The operator investigates and resolves one ticket,
saves the resolution as a playbook (optionally AI-drafted from that ticket),
and every other ticket in the same category shows that playbook in its flyout.

A playbook is durable, operator-owned knowledge — **not** a cache. It is stored
in a dedicated `playbooks` table, survives re-syncs, and is never auto-busted by
new customer messages. The AI is an on-demand *drafter*, not a live suggester:
its output is saved into a playbook, not discarded.

Surface is **webapp-only**: a flyout section on each ticket plus a standalone
library page. No backend Intercom client, no extension surface, no new
cross-package ingest shape.

## Motivation

Today every ticket is handled in isolation. When a wave of tickets share one
root cause ("double-charge after plan upgrade"), the operator solves the first,
then re-derives the same steps by memory for each sibling. The investigation
that cracked the issue lives only in that one ticket's `note_entries`; there is
no cross-ticket query layer and nothing surfaces the earned recipe on the
others.

The workflow we want:

> Cluster of tickets, same issue. Investigate and resolve one. From that ticket,
> capture "here's how you handle this." Every sibling in the category now shows
> the recipe — one glance = next steps.

## Decisions (from brainstorm)

1. **Hybrid engine** — rule-based surfacing (category-filtered list, always on,
   zero AI) + an optional on-demand LLM drafter. Not a per-open AI call.
2. **Memory table, not cache** — a cache is regenerable data keyed by content
   signature (inv #6) and auto-busts on the next customer reply. A playbook is
   earned knowledge that must persist. Wrong tool to cache it.
3. **Many playbooks per category** — a category ("Billing") holds several
   distinct issues, each its own playbook with a short `label`.
4. **Category-filtered surfacing, operator picks** — the flyout lists every
   playbook in the ticket's *effective* category (override beats AI). The
   operator eyeballs which fits. No per-ticket tagging, no auto-match in v1.
5. **AI = drafter, output saved** — clicking "Draft with AI" builds a recipe
   from the ticket, fills an editable textarea; the operator edits and saves.
   The draft itself is ephemeral (one call per click, never stored on its own,
   no fallback row). Superseded the earlier "ephemeral live suggestion" framing.
6. **internal_notes excluded from the AI drafter** (inv #4) — the drafter reads
   customer-visible `parts[]` + operator `NoteEntry`/`TicketNote` only.
   internal_notes may still be *displayed* to the operator.
7. **Two webapp surfaces** — flyout section (per-ticket) + standalone library
   page (manage all playbooks by category). No extension/popup surface.

## Data model

### New table — `playbooks`

```python
class Playbook(Base):
    __tablename__ = "playbooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)          # issue name
    body: Mapped[str] = mapped_column(Text, nullable=False)           # the recipe
    source_ticket_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

- `category_id` required — a playbook always lives in a category. Uncategorized
  / proposal-bucket tickets show no playbooks in v1.
- `label` + `body` required and non-empty.
- `source_ticket_id` informational; `ON DELETE SET NULL` so a removed exemplar
  doesn't orphan the recipe.
- Timestamps are naive UTC, `Z`-suffixed on the wire (inv #5).
- `archived_at` soft-retires a playbook when the issue dies; archived rows hidden
  from the flyout, shown in the library under `?include_archived`.
- No content-signature column, no auto-bust. Playbooks survive ingest /
  re-sync untouched (same stickiness spirit as inv #8).

## Backend (isolated module — Approach A)

- `models.py`: `Playbook`.
- `schemas.py`: `PlaybookCreate`, `PlaybookUpdate`, `PlaybookRead`.
- `services/playbooks.py`:
  - `list_for_category(category_id, include_archived=False)`
  - `list_for_ticket(ticket_id)` — resolves the ticket's **effective** category
    (override beats AI, reusing existing resolution logic) then lists its
    active playbooks.
  - `create`, `update`, `archive`, `list_all`.
  - `draft_from_ticket(ticket_id)` — builds a prompt from customer-visible
    `parts[]` + operator `NoteEntry`/`TicketNote`, **excludes `internal_notes[]`
    (inv #4)**, calls the existing OpenRouter client through `ai/pipeline`,
    returns draft text. Not saved, not cached; on failure returns nothing and
    the operator writes the body manually.
- `routers/playbooks.py`:

  | Endpoint | Method | What |
  |----------|--------|------|
  | `/playbooks?ticket_id=` | GET | Active playbooks for the ticket's effective category (flyout) |
  | `/playbooks?category_id=` | GET | Library list (`&include_archived` to include retired) |
  | `/playbooks` | POST | Create (`category_id`, `label`, `body`, optional `source_ticket_id`) |
  | `/playbooks/{id}` | PATCH | Edit `label` / `body` |
  | `/playbooks/{id}/archive` | POST | Soft-retire (and un-archive) |
  | `/playbooks/draft` | POST | `{ticket_id}` → ephemeral AI draft body |

- Alembic migration adds the table.

## Frontend (webapp only)

- `types/api.ts`: `Playbook` interface.
- `api/client.ts`: playbook calls.
- `stores/playbooks.ts`: state keyed by category, optimistic CRUD (snapshot →
  mutate → API → rollback, the existing store pattern).
- **Flyout section** (`TicketFlyout.vue`): a "Playbooks" panel listing the
  playbooks for the ticket's effective category (label + collapsible body).
  A **"Save as playbook"** action opens a form with `category_id` and
  `source_ticket_id` prefilled; an optional **"Draft with AI"** button calls
  `/playbooks/draft`, fills the body textarea, the operator edits and saves.
- **Library page** (new route `PlaybookLibrary.vue` + nav entry): playbooks
  grouped by category, create / edit / archive. This is the "rollup + full list"
  surface, organized as playbooks rather than raw notes.

## AI drafter

Reuses the OpenRouter client and the `asyncio.Semaphore` concurrency guard. New
prompt: *resolved ticket conversation (customer-visible) + operator notes →
concise next-steps recipe.* On-demand only — one call per button click. No
caching, no fallback row written (consistent with inv #7's spirit: never persist
a fallback). On failure the operator simply writes the body by hand.

## Cross-package invariants & doc impact

Repo mandates `spec.md` / `plan.md` / `tasks.md` updates before new surface area:

- `spec.md`: **US-020** (operator captures reusable resolution playbooks and
  reuses them on sibling tickets) + **FR-038..** (storage, effective-category
  surfacing, AI draft, library management).
- `plan.md`: new section covering the table, the isolated backend module, the
  webapp store/view/flyout, the drafter prompt.
- `tasks.md`: new **Phase 14**, T-numbers chosen above the reserved Phase 9
  range (T100–T107) to avoid collision.
- `CLAUDE.md`: new invariant — *playbooks are operator-owned and survive
  re-sync; the AI drafter excludes `internal_notes[]`; a playbook is scoped to
  the effective category and never auto-busted by content signature.*

## Testing

- **backend (pytest):** CRUD + archive; `list_for_ticket` effective-category
  resolution (override beats AI); **explicit assertion that `draft_from_ticket`
  excludes `internal_notes`**; playbooks untouched across a re-sync;
  `category_id` FK + non-empty `label`/`body` validation.
- **webapp (vitest):** store CRUD + optimistic rollback; flyout section render
  for a ticket with / without playbooks; library view create/edit/archive.

## Out of scope (YAGNI — v1)

- No per-ticket manual link table (ticket↔playbook).
- No LLM auto-match on ticket open.
- No embeddings / semantic search.
- No playbook versioning or edit history.
- No playbooks on proposal-bucket / uncategorized tickets.
- No extension or popup surface.
