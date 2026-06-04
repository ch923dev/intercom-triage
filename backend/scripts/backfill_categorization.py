"""One-shot backfill: re-run AI categorization over every stored ticket.

Why this exists
---------------
Until the `prompt.py` fix, the categorization call sent a strict `json_schema`
`response_format` whose root `oneOf` (and numeric `minimum`/`maximum`) is
rejected by the default Anthropic model on OpenRouter. Every categorization
call 400'd, so every ticket took the per-ticket fallback path: fallback
category, no subject, no summary, and (invariant #7) no `ai_cache` row. A normal
re-sync does not heal them — the skip-known optimization never
re-sends an unchanged conversation.

This replays the real ingest service (`services.tickets.ingest_tickets`) over
the rows already in the DB, reconstructing each `HydratedTicket` from its stored
columns. Because it goes through the unchanged ingest path it is idempotent,
cache-aware, and preserves operator state by construction:
  * sticky `title_user_edited` / `summary_user_edited` are not overwritten,
  * manual category overrides still win at read time (they live in `overrides`),
  * parked and resolved state are untouched (no closure transition fires when a
    ticket is replayed with its stored state; auto-resolve is gated by the
    operator's toggle, off by default).

Run from `backend/` with the venv active:
    python scripts/backfill_categorization.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make the backend package root importable whether invoked as
# `python scripts/backfill_categorization.py` or `python -m scripts...`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.clients.openrouter import OpenRouterClient  # noqa: E402
from app.config import AppConfig  # noqa: E402
from app.db import make_engine, make_session_factory  # noqa: E402
from app.models import Category, Ticket  # noqa: E402
from app.schemas import HydratedTicket  # noqa: E402
from app.services.tickets import ingest_tickets  # noqa: E402


async def main() -> None:
    cfg = AppConfig()
    if not cfg.openrouter_api_key.strip():
        raise SystemExit("OPENROUTER_API_KEY is not set — nothing to backfill against.")

    engine = make_engine(cfg.database_url)
    session_factory = make_session_factory(engine)
    client = OpenRouterClient(cfg.openrouter_api_key)

    try:
        async with session_factory() as session:
            fallback_id = await session.scalar(
                select(Category.id).where(Category.is_fallback.is_(True))
            )
            rows = list((await session.scalars(select(Ticket))).all())
            before = sum(1 for r in rows if r.category_id == fallback_id)
            hydrated = [HydratedTicket.model_validate(r, from_attributes=True) for r in rows]

            print(f"Re-ingesting {len(hydrated)} stored tickets (was {before} in fallback)...")
            resp = await ingest_tickets(
                session=session, openrouter=client, config=cfg, hydrated=hydrated
            )

            # Re-read to report the delta.
            after_rows = list((await session.scalars(select(Ticket))).all())
            after = sum(1 for r in after_rows if r.category_id == fallback_id)
            with_summary = sum(1 for r in after_rows if (r.summary or "").strip())
            print(
                f"Done. received={resp.received} categorized={resp.categorized} | "
                f"fallback {before} -> {after} | tickets with a summary: {with_summary}/{len(after_rows)}"
            )
    finally:
        await client.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
