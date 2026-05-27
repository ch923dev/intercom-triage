"""Stats rollups for the dashboard (roadmap 1.3).

Read-only aggregations over the existing `tickets` table — no migration, no
new columns, no raw SQL (group-by via SQLAlchemy `select` / `func.count`).
Computes the four success metrics surfaced on the dashboard:

1. Category breakdown — count of tickets per *effective* category. An override
   beats the AI category (cross-package invariant #10/#13: effective category),
   so we resolve `overrides.category_id` first and fall back to
   `tickets.category_id`.
2. Volume trend — tickets created per UTC calendar day across a trailing
   window, gap-filled so every day in the window has a point.
3. Resolution mix — counts keyed by `resolved_source` (manual |
   intercom_closed | non_actionable | ai_resolved) plus an `open` bucket for
   tickets with no `resolved_at` (cross-package invariant #10).
4. Time-to-resolve distribution — for resolved tickets, the elapsed time from
   the first customer-visible message to `resolved_at`, bucketed into hour
   bands. The first-customer-message timestamp lives in the `parts` JSON blob
   (the customer-visible thread, invariant #4), so that leg is computed in
   Python; the SQL only selects the resolved rows.

All windowing is by ticket `created_at`, consistent across the volume trend,
resolution mix, and resolve-time distribution.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, Override, Ticket
from app.schemas import (
    CategoryCount,
    ResolutionMix,
    ResolveTimeBucket,
    StatsResponse,
    VolumePoint,
)
from app.util import naive_utcnow

DEFAULT_WINDOW_DAYS = 30

# Time-to-resolve histogram bands, in hours. The final band is open-ended
# (`upper` is None → "≥ 1 week").
_RESOLVE_BANDS: list[tuple[str, float, float | None]] = [
    ("< 1h", 0.0, 1.0),
    ("1–4h", 1.0, 4.0),
    ("4–24h", 4.0, 24.0),
    ("1–3d", 24.0, 72.0),
    ("3–7d", 72.0, 168.0),
    ("≥ 7d", 168.0, None),
]


def _window_start(window_days: int) -> datetime:
    """Naive-UTC lower bound (inclusive) for the trailing window."""
    return naive_utcnow() - timedelta(days=window_days)


def _first_customer_at(ticket: Ticket) -> datetime | None:
    """Timestamp of the earliest customer-visible message on a ticket.

    `parts` is the customer-visible thread (invariant #4); inbound customer
    messages carry `is_admin == False`. We take the earliest non-admin part,
    falling back to the earliest part of any kind, then to `created_at`. The
    stored parts carry naive-UTC `created_at` ISO strings (invariant #5).
    """
    parts = ticket.parts or []
    customer_times: list[datetime] = []
    any_times: list[datetime] = []
    for p in parts:
        parsed = _parse_part_dt(p)
        if parsed is None:
            continue
        any_times.append(parsed)
        if not p.get("is_admin", False):
            customer_times.append(parsed)
    if customer_times:
        return min(customer_times)
    if any_times:
        return min(any_times)
    return ticket.created_at


def _parse_part_dt(part: dict[str, object]) -> datetime | None:
    """Parse a part's `created_at` (a `Z`-suffixed or naive ISO string) to
    naive UTC. Returns None on anything unparseable."""
    raw = part.get("created_at")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


async def _category_breakdown(
    session: AsyncSession,
    window_start: datetime,
) -> list[CategoryCount]:
    """Count tickets per effective category in the window.

    Effective category = override if present, else `tickets.category_id`. We
    LEFT JOIN `overrides`, coalesce, then LEFT JOIN `categories` for the name,
    and group by the resolved id.
    """
    effective_id = func.coalesce(Override.category_id, Ticket.category_id)
    stmt = (
        select(
            effective_id.label("cat_id"),
            Category.name,
            func.count(Ticket.id),
        )
        .select_from(Ticket)
        .outerjoin(Override, Override.ticket_id == Ticket.id)
        .outerjoin(Category, Category.id == effective_id)
        .where(Ticket.created_at >= window_start)
        .group_by(effective_id, Category.name)
        .order_by(func.count(Ticket.id).desc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        CategoryCount(
            category_id=cat_id,
            category_name=name if name is not None else "Uncategorized",
            count=count,
        )
        for cat_id, name, count in rows
    ]


async def _volume_trend(
    session: AsyncSession,
    window_start: datetime,
    window_days: int,
) -> list[VolumePoint]:
    """Tickets created per UTC calendar day, gap-filled across the window.

    Group-by on the date portion of `created_at`. `func.date` is portable —
    SQLite's `date()` and Postgres' `date()`/cast both yield `YYYY-MM-DD`.
    """
    day = func.date(Ticket.created_at)
    stmt = (
        select(day.label("day"), func.count(Ticket.id))
        .where(Ticket.created_at >= window_start)
        .group_by(day)
    )
    rows = (await session.execute(stmt)).all()
    counts: dict[str, int] = {str(d): c for d, c in rows}

    # Gap-fill every day from window_start's date through today (inclusive).
    today = naive_utcnow().date()
    start_date = window_start.date()
    points: list[VolumePoint] = []
    span = (today - start_date).days
    for offset in range(span + 1):
        d = start_date + timedelta(days=offset)
        key = d.isoformat()
        points.append(VolumePoint(date=key, count=counts.get(key, 0)))
    # Defensive: keep only the most recent window_days points if the span ran long.
    return points[-(window_days + 1) :]


async def _resolution_mix(
    session: AsyncSession,
    window_start: datetime,
) -> ResolutionMix:
    """Count tickets by `resolved_source`; null → `open` (invariant #10)."""
    stmt = (
        select(Ticket.resolved_source, func.count(Ticket.id))
        .where(Ticket.created_at >= window_start)
        .group_by(Ticket.resolved_source)
    )
    rows = (await session.execute(stmt)).all()
    mix = ResolutionMix()
    for source, count in rows:
        if source is None:
            mix.open = count
        elif source == "manual":
            mix.manual = count
        elif source == "intercom_closed":
            mix.intercom_closed = count
        elif source == "non_actionable":
            mix.non_actionable = count
        elif source == "ai_resolved":
            mix.ai_resolved = count
    return mix


async def _resolve_time(
    session: AsyncSession,
    window_start: datetime,
) -> tuple[list[ResolveTimeBucket], float | None]:
    """Bucket resolved tickets by (resolved_at − first-customer-message) hours.

    The first-customer-message leg lives in the `parts` JSON blob, so we pull
    the resolved rows and compute the elapsed time in Python. Negative or zero
    deltas (clock skew / resolved before any customer part) clamp into the
    first band. Returns the buckets plus the median elapsed hours (None when no
    ticket resolved in the window).
    """
    stmt = select(Ticket).where(
        Ticket.created_at >= window_start,
        Ticket.resolved_at.is_not(None),
    )
    tickets = (await session.scalars(stmt)).all()

    band_counts: Counter[int] = Counter()
    elapsed_hours: list[float] = []
    for ticket in tickets:
        if ticket.resolved_at is None:
            continue
        first_at = _first_customer_at(ticket)
        if first_at is None:
            first_at = ticket.created_at
        delta = ticket.resolved_at - first_at
        hours = max(delta.total_seconds() / 3600.0, 0.0)
        elapsed_hours.append(hours)
        band_counts[_band_index(hours)] += 1

    buckets = [
        ResolveTimeBucket(
            label=label,
            lower_hours=lower,
            upper_hours=upper,
            count=band_counts.get(idx, 0),
        )
        for idx, (label, lower, upper) in enumerate(_RESOLVE_BANDS)
    ]
    med = median(elapsed_hours) if elapsed_hours else None
    return buckets, med


def _band_index(hours: float) -> int:
    """Index into `_RESOLVE_BANDS` for an elapsed-hours value."""
    for idx, (_label, lower, upper) in enumerate(_RESOLVE_BANDS):
        if hours >= lower and (upper is None or hours < upper):
            return idx
    return len(_RESOLVE_BANDS) - 1


async def get_stats(session: AsyncSession, window_days: int = DEFAULT_WINDOW_DAYS) -> StatsResponse:
    """Compute all four dashboard metrics over a trailing window of N days."""
    window_start = _window_start(window_days)

    category_breakdown = await _category_breakdown(session, window_start)
    volume_trend = await _volume_trend(session, window_start, window_days)
    resolution_mix = await _resolution_mix(session, window_start)
    resolve_time_buckets, median_resolve_hours = await _resolve_time(session, window_start)

    total = sum(c.count for c in category_breakdown)

    return StatsResponse(
        window_days=window_days,
        total_tickets=total,
        category_breakdown=category_breakdown,
        volume_trend=volume_trend,
        resolution_mix=resolution_mix,
        resolve_time_buckets=resolve_time_buckets,
        median_resolve_hours=median_resolve_hours,
    )
