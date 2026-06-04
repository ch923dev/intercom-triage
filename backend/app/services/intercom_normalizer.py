"""Official-API → `HydratedTicket` normalizer. Reference: plan.md §6.

The Python port of the former extension `normalizeConversation`. Pure functions,
no HTTP — the sync service feeds raw conversation + contact dicts in, validated
`HydratedTicket` objects come out.

Routing replaces the reverse-engineered numeric `renderable_type` codes
(1/12/2/24/3) with Intercom's official `part_type` string + `author.type`
(cross-package invariant #3):

  - `source` (opening message)            → parts[]   (is_admin per author type)
  - part_type=comment, customer author    → parts[]   (is_admin=False)
  - part_type=comment, admin/bot author   → parts[]   (is_admin=True)
  - part_type=note                        → internal_notes[]  (invariant #4)
  - assignment / open / close / snoozed / … → skipped
  - unknown part_type                     → skipped + logged (code + id, no body)
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from typing import Any, cast

from app.observability import log_event
from app.schemas import ConversationPartSchema, HydratedTicket, TicketAuthorSchema, TicketState
from app.util import naive_utcnow

_MAX_BODY_CHARS = 8000

# author.type values that mean the message is from the support side, not the
# customer. Drives `is_admin` on a part + whether `source` counts as admin.
_ADMIN_AUTHOR_TYPES = frozenset({"admin", "bot", "team"})

# Customer-visible message parts go to parts[]; team notes to internal_notes[].
# Everything else (routing / state events) is skipped — they carry no thread text.
_SKIP_PART_TYPES = frozenset(
    {
        "assignment",
        "default_assignment",
        "away_mode_assignment",
        "message_strategy_assignment",
        "open",
        "close",
        "snoozed",
        "unsnoozed",
        "participant",
        "language_detection_details",
        "conversation_attribute_updated_by_admin",
    }
)

_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_BLOCK_CLOSE_RE = re.compile(r"</(p|div|li|h[1-6]|tr|blockquote)>", re.IGNORECASE)
_LI_OPEN_RE = re.compile(r"<li[^>]*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(value: str | None) -> str:
    """HTML → plain text, capped at 8000 chars. Port of the extension `stripHtml`
    + `blocksToPlainText`: <br> and block boundaries become newlines, <li> a
    bullet, remaining tags are dropped, entities decoded, blank lines collapsed.
    """
    if not value:
        return ""
    text = _BR_RE.sub("\n", value)
    text = _BLOCK_CLOSE_RE.sub("\n", text)
    text = _LI_OPEN_RE.sub("• ", text)
    text = _TAG_RE.sub("", text)
    # `&nbsp;` decodes to U+00A0; normalize to a plain space (matches the former
    # extension `stripHtml` and keeps the AI prompt free of stray nbsp chars).
    text = html.unescape(text).replace(" ", " ")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)[:_MAX_BODY_CHARS]


def attachment_fallback(attachments: Any) -> str:
    """`[attachment: name]` lines for a part that has uploads but no text."""
    if not isinstance(attachments, list):
        return ""
    out: list[str] = []
    for att in attachments:
        name = att.get("name") if isinstance(att, dict) else None
        out.append(
            f"[attachment: {name.strip()}]"
            if isinstance(name, str) and name.strip()
            else "[attachment]"
        )
    return "\n".join(out)[:_MAX_BODY_CHARS]


def _epoch_to_naive_utc(seconds: Any, fallback: datetime) -> datetime:
    """Unix seconds → naive UTC datetime (the DB/schema clock). Bad input →
    `fallback`."""
    if isinstance(seconds, int | float) and not isinstance(seconds, bool):
        return datetime.fromtimestamp(seconds, tz=UTC).replace(tzinfo=None)
    return fallback


def _coerce_state(raw: Any) -> TicketState | None:
    return cast("TicketState", raw) if raw in ("open", "snoozed", "closed") else None


def normalize_part_author(raw: Any) -> TicketAuthorSchema:
    """Author for a thread part / internal note — no User-data-panel fields
    (those are customer-only, hydrated separately)."""
    if not isinstance(raw, dict):
        return TicketAuthorSchema()
    rid = raw.get("id")
    return TicketAuthorSchema(
        id=str(rid) if rid is not None else None,
        name=raw.get("name"),
        email=raw.get("email"),
        type=raw.get("type"),
    )


def _compose_location(contact: dict[str, Any]) -> str | None:
    """City, region, country from the contact's `location` (newer) or
    `location_data` (legacy) — whichever is present."""
    loc = contact.get("location")
    if isinstance(loc, dict):
        parts = [loc.get("city"), loc.get("region"), loc.get("country")]
    else:
        legacy = contact.get("location_data")
        legacy = legacy if isinstance(legacy, dict) else {}
        parts = [legacy.get("city_name"), legacy.get("region_name"), legacy.get("country_name")]
    composed = [p for p in parts if isinstance(p, str) and p.strip()]
    return ", ".join(composed) or None


def _contact_company(contact: dict[str, Any]) -> str | None:
    """First company name when embedded inline; else None (avoids a third call
    per conversation just to resolve a company name)."""
    companies = contact.get("companies")
    data = companies.get("data") if isinstance(companies, dict) else None
    if isinstance(data, list) and data and isinstance(data[0], dict):
        name = data[0].get("name")
        return name if isinstance(name, str) and name.strip() else None
    return None


def _contact_timezone(contact: dict[str, Any]) -> str | None:
    tz = contact.get("timezone")
    if isinstance(tz, str) and tz.strip():
        return tz
    legacy = contact.get("location_data")
    if isinstance(legacy, dict):
        tz = legacy.get("timezone")
        return tz if isinstance(tz, str) and tz.strip() else None
    return None


def normalize_customer_author(
    source_author: dict[str, Any] | None, contact: dict[str, Any] | None
) -> TicketAuthorSchema:
    """Merge the conversation-level customer author (id/name/email) with the
    enriched contact payload (location/timezone/phone/company). A missing
    contact degrades to id/name/email only — never an error (invariant #4 keeps
    these fields customer-only)."""
    src = source_author if isinstance(source_author, dict) else {}
    contact = contact if isinstance(contact, dict) else None

    # Prefer the contact's external_id (Intercom's user-facing "User id") so
    # triage identity matches the Intercom panel; fall back to the source id.
    external_id = contact.get("external_id") if contact else None
    src_id = src.get("id")
    chosen_id = external_id if external_id is not None else src_id

    return TicketAuthorSchema(
        id=str(chosen_id) if chosen_id is not None else None,
        name=(contact.get("name") if contact else None) or src.get("name"),
        email=(contact.get("email") if contact else None) or src.get("email"),
        type=src.get("type") or "user",
        location=_compose_location(contact) if contact else None,
        timezone=_contact_timezone(contact) if contact else None,
        phone=(contact.get("phone") if contact else None),
        company=_contact_company(contact) if contact else None,
    )


def customer_contact_id(detail: dict[str, Any]) -> str | None:
    """The contact id to enrich for the customer author — for the sync service
    to fetch via `GET /contacts/{id}` before normalizing."""
    contacts = detail.get("contacts")
    lst = contacts.get("contacts") if isinstance(contacts, dict) else None
    if isinstance(lst, list) and lst and isinstance(lst[0], dict) and lst[0].get("id") is not None:
        return str(lst[0]["id"])
    customer = detail.get("customer")
    if isinstance(customer, dict) and customer.get("id") is not None:
        return str(customer["id"])
    author = (detail.get("source") or {}).get("author")
    if isinstance(author, dict) and author.get("type") in ("contact", "user", "lead"):
        if author.get("id") is not None:
            return str(author["id"])
    return None


def _iter_parts(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """The thread parts. Intercom nests them under `conversation_parts.
    conversation_parts[]`; tolerate the `parts.conversation_parts` alias."""
    for key in ("conversation_parts", "parts"):
        container = detail.get(key)
        inner = container.get("conversation_parts") if isinstance(container, dict) else None
        if isinstance(inner, list):
            return [p for p in inner if isinstance(p, dict)]
    return []


def normalize_conversation(
    detail: dict[str, Any],
    *,
    workspace_app_id: str,
    customer_contact: dict[str, Any] | None,
) -> HydratedTicket:
    """Official conversation payload → `HydratedTicket` (invariant #2 shape)."""
    convo_id = str(detail["id"])
    fallback_dt = naive_utcnow()
    created_at = _epoch_to_naive_utc(detail.get("created_at"), fallback_dt)
    updated_at = _epoch_to_naive_utc(detail.get("updated_at"), created_at)

    raw_source = detail.get("source")
    source: dict[str, Any] = raw_source if isinstance(raw_source, dict) else {}
    raw_source_author = source.get("author")
    source_author: dict[str, Any] = raw_source_author if isinstance(raw_source_author, dict) else {}
    author = normalize_customer_author(source_author, customer_contact)

    parts: list[ConversationPartSchema] = []
    internal_notes: list[ConversationPartSchema] = []

    # The opening message lives only on `source`, never in conversation_parts.
    source_body = strip_html(source.get("body")) or attachment_fallback(source.get("attachments"))
    if source_body:
        parts.append(
            ConversationPartSchema(
                author=normalize_part_author(source_author) if source_author else author,
                body=source_body,
                created_at=created_at,
                is_admin=source_author.get("type") in _ADMIN_AUTHOR_TYPES,
            )
        )

    for part in _iter_parts(detail):
        part_type = part.get("part_type")
        raw_part_author = part.get("author")
        part_author: dict[str, Any] = raw_part_author if isinstance(raw_part_author, dict) else {}
        part_created = _epoch_to_naive_utc(part.get("created_at"), created_at)
        body = strip_html(part.get("body")) or attachment_fallback(part.get("attachments"))

        if part_type == "comment":
            if not body:
                continue
            parts.append(
                ConversationPartSchema(
                    author=normalize_part_author(part_author),
                    body=body,
                    created_at=part_created,
                    is_admin=part_author.get("type") in _ADMIN_AUTHOR_TYPES,
                )
            )
        elif part_type == "note":
            if not body:
                continue
            internal_notes.append(
                ConversationPartSchema(
                    author=normalize_part_author(part_author),
                    body=body,
                    created_at=part_created,
                    is_admin=True,
                )
            )
        elif part_type not in _SKIP_PART_TYPES:
            # Unknown code — Intercom may have introduced a part kind we'd drop.
            # Surface it (type + id only, never the body) so it can be mapped.
            log_event(
                "intercom.unknown_part_type", part_type=str(part_type), conversation_id=convo_id
            )

    priority = "priority" if detail.get("priority") == "priority" else None

    return HydratedTicket(
        id=convo_id,
        title=detail.get("title"),
        state=_coerce_state(detail.get("state")),
        priority=priority,
        created_at=created_at,
        updated_at=updated_at,
        author=author,
        url=f"https://app.intercom.com/a/inbox/{workspace_app_id}/inbox/conversation/{convo_id}",
        parts=parts,
        internal_notes=internal_notes,
    )
