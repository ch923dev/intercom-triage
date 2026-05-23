"""Settings — read/write the singleton row. Reference: tasks.md T027."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Settings
from app.schemas import FilterSettings
from app.util import naive_utcnow


async def get_settings(session: AsyncSession) -> FilterSettings:
    """Read the singleton settings row (seeded by `init_db`)."""
    row = await session.get(Settings, 1)
    if row is None:  # pragma: no cover - seed guarantees the row exists
        raise RuntimeError("settings row missing — DB was not seeded")
    return FilterSettings(
        lookback_unit=row.lookback_unit,  # type: ignore[arg-type]
        lookback_value=row.lookback_value,
        states=list(row.states),  # type: ignore[arg-type]
        include_category_ids=(
            list(row.include_category_ids) if row.include_category_ids is not None else None
        ),
        mute_alarms=row.mute_alarms,
        use_ai=row.use_ai,
        ai_resolve_default=row.ai_resolve_default,
        ai_resolve_confidence_threshold=row.ai_resolve_confidence_threshold,
    )


async def update_settings(
    session: AsyncSession,
    data: FilterSettings,
) -> FilterSettings:
    """Write the singleton row and return the stored shape."""
    row = await session.get(Settings, 1)
    if row is None:  # pragma: no cover
        row = Settings(id=1)
        session.add(row)
    row.lookback_unit = data.lookback_unit
    row.lookback_value = data.lookback_value
    row.states = list(data.states)
    row.include_category_ids = (
        list(data.include_category_ids) if data.include_category_ids is not None else None
    )
    row.mute_alarms = data.mute_alarms
    row.use_ai = data.use_ai
    row.ai_resolve_default = data.ai_resolve_default
    row.ai_resolve_confidence_threshold = data.ai_resolve_confidence_threshold
    row.updated_at = naive_utcnow()
    await session.commit()
    return await get_settings(session)
