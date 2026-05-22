"""Structured logging for external calls. Reference: NFR-006, tasks.md T028.

Every Intercom / OpenRouter call is wrapped by `logged_call`, which emits one
structured log line carrying `op`, `duration_ms`, `outcome`, and (where it
applies) `ticket_id`. Ticket bodies are never passed in — callers hand over
identifiers only, so no conversation text can leak into logs.

Stdlib `logging` is used (not structlog) so the lines are visible to standard
log capture and to the harness.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

log = logging.getLogger("triage")


def configure_logging(level: str = "INFO") -> None:
    """Wire root logging once at startup."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def log_event(event: str, *, level: int = logging.INFO, **fields: object) -> None:
    """Emit one structured line: `event key=value key=value`."""
    rendered = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
    log.log(level, "%s %s", event, rendered)


@asynccontextmanager
async def logged_call(op: str, ticket_id: str | None = None) -> AsyncIterator[None]:
    """Time an external call and emit one structured log line on exit.

    Re-raises any exception after logging `outcome=error`.
    """
    start = time.perf_counter()
    outcome = "ok"
    try:
        yield
    except Exception:
        outcome = "error"
        raise
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        log_event(
            "external_call",
            op=op,
            outcome=outcome,
            duration_ms=duration_ms,
            ticket_id=ticket_id,
        )
