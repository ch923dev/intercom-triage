"""The single source of truth for the 'override beats AI' rule.

A manual category override wins over the AI categorization iff the override is
at least as new as the customer-visible thread (``ticket.content_signature_at
<= override.set_at``). When it wins, the AI proposal is cleared.

Customer-visible, not Intercom's ``updated_at`` (T205): ``updated_at`` also
moves on internal notes, assignments and snoozes, so keying on it let a
teammate's note silently revert an operator's category. The override should
yield only when there is something new for the AI to judge — which is exactly
when the AI cache key (the same signature, invariant #6) changes.

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
    True) when the override is at least as new as the customer-visible thread;
    otherwise the AI's ``category_id`` / ``proposal_id`` pass through unchanged.
    """
    if override is not None and ticket.content_signature_at <= override.set_at:
        return override.category_id, None, True
    return ticket.category_id, ticket.proposal_id, False
