"""`GET /metrics` — in-process counters.

Reference: plan.md §11, tasks.md T043. Counters live for the lifetime of the
process and reset on restart; they are written by the AI pipeline, the tickets
service, and proposal resolution.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.metrics import metrics
from app.schemas import LatencyHistogram, MetricsResponse

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_model=MetricsResponse)
async def read_metrics() -> MetricsResponse:
    """A snapshot of every counter + latency histogram the process has touched."""
    return MetricsResponse(
        counters=metrics.snapshot(),
        histograms={
            key: LatencyHistogram(**stat) for key, stat in metrics.histogram_snapshot().items()
        },
    )
