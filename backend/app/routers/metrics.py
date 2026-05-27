"""`GET /metrics` — in-process counters.

Reference: plan.md §11, tasks.md T043. Counters live for the lifetime of the
process and reset on restart; they are written by the AI pipeline, the tickets
service, and proposal resolution.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.metrics import metrics
from app.schemas import LatencyHistogram, MetricsResponse, UsageBucket
from app.util import naive_utcnow

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_model=MetricsResponse)
async def read_metrics() -> MetricsResponse:
    """A snapshot of every counter + latency histogram + token-spend bucket the
    process has touched. `today_cost_usd` sums the estimate across all models
    for the current UTC day (roadmap 1.4)."""
    usage = [UsageBucket(**stat) for stat in metrics.usage_snapshot()]
    today = naive_utcnow().date().isoformat()
    today_cost = sum(u.estimated_cost_usd for u in usage if u.date == today)
    return MetricsResponse(
        counters=metrics.snapshot(),
        histograms={
            key: LatencyHistogram(**stat) for key, stat in metrics.histogram_snapshot().items()
        },
        usage=usage,
        today_cost_usd=round(today_cost, 6),
    )
