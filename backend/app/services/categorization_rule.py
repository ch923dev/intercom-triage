"""The single source of truth for the 'override beats AI' rule (invariant #11).

A manual category override wins over the AI categorization iff the override is
at least as new as the ticket's last update (``ticket.updated_at <=
override.set_at``). When it wins, the AI proposal is cleared.

This was duplicated inline in the board read, playbooks, and clustering — and
had already drifted in stats (which counted overrides regardless of timestamp).
One helper keeps the row-based call sites honest; the stats aggregation mirrors
it in SQL.
"""

from __future__ import annotations

from app.models import Override, Ticket


def effective_category(
    ticket: Ticket, override: Override | None
) -> tuple[int | None, int | None, bool]:
    """Resolve a ticket's effective ``(category_id, proposal_id, user_override)``.

    Returns the manual override's category (proposal cleared, ``user_override``
    True) when the override is at least as new as the ticket; otherwise the AI's
    ``category_id`` / ``proposal_id`` pass through unchanged.
    """
    if override is not None and ticket.updated_at <= override.set_at:
        return override.category_id, None, True
    return ticket.category_id, ticket.proposal_id, False
