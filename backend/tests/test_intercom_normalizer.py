"""Normalizer tests — the official-API → HydratedTicket port.

Highest-value invariant: `part_type='note'` lands in internal_notes[] and NEVER
in parts[] (cross-package invariant #4 — internal notes never reach the AI).
"""

from __future__ import annotations

from typing import Any

from app.services.intercom_normalizer import (
    attachment_fallback,
    customer_contact_id,
    normalize_conversation,
    strip_html,
)

_EPOCH = 1_717_243_200  # 2024-06-01T12:00:00Z


def _detail(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "C1",
        "title": "Need help",
        "state": "open",
        "priority": "not_priority",
        "created_at": _EPOCH,
        "updated_at": _EPOCH + 60,
        "source": {
            "author": {"type": "user", "id": "u1", "name": "Ada", "email": "ada@x.com"},
            "body": "<p>Hello&nbsp;there</p>",
            "attachments": [],
        },
        "contacts": {"contacts": [{"type": "contact", "id": "contact_1"}]},
        "conversation_parts": {"conversation_parts": []},
    }
    base.update(overrides)
    return base


def _part(part_type: str, *, author_type: str, body: str = "x", at: int = _EPOCH) -> dict[str, Any]:
    return {
        "part_type": part_type,
        "author": {"type": author_type, "id": "a1", "name": "Tess"},
        "body": body,
        "created_at": at,
        "attachments": [],
    }


def test_note_goes_to_internal_notes_not_parts() -> None:
    detail = _detail(
        conversation_parts={
            "conversation_parts": [
                _part("comment", author_type="user", body="customer question"),
                _part("note", author_type="admin", body="internal teammate note"),
            ]
        }
    )
    ticket = normalize_conversation(detail, workspace_app_id="ws", customer_contact=None)

    part_bodies = [p.body for p in ticket.parts]
    note_bodies = [n.body for n in ticket.internal_notes]
    assert "internal teammate note" in note_bodies
    assert "internal teammate note" not in part_bodies
    assert "customer question" in part_bodies
    assert all(n.is_admin for n in ticket.internal_notes)


def test_source_is_first_part() -> None:
    detail = _detail(
        conversation_parts={
            "conversation_parts": [_part("comment", author_type="admin", body="reply")]
        }
    )
    ticket = normalize_conversation(detail, workspace_app_id="ws", customer_contact=None)
    assert ticket.parts[0].body == "Hello there"  # source, HTML stripped + entity decoded
    assert ticket.parts[0].is_admin is False  # source author is a user
    assert ticket.parts[1].is_admin is True  # admin reply


def test_admin_comment_marked_admin() -> None:
    detail = _detail(
        source={"author": {"type": "user", "id": "u1"}, "body": "hi"},
        conversation_parts={
            "conversation_parts": [_part("comment", author_type="admin", body="agent reply")]
        },
    )
    ticket = normalize_conversation(detail, workspace_app_id="ws", customer_contact=None)
    admin_parts = [p for p in ticket.parts if p.is_admin]
    assert any(p.body == "agent reply" for p in admin_parts)


def test_event_parts_skipped() -> None:
    detail = _detail(
        conversation_parts={
            "conversation_parts": [
                _part("assignment", author_type="admin", body=""),
                _part("close", author_type="admin", body=""),
                _part("comment", author_type="user", body="real message"),
            ]
        }
    )
    ticket = normalize_conversation(detail, workspace_app_id="ws", customer_contact=None)
    # Only source + the one real comment survive; events carry no text.
    assert [p.body for p in ticket.parts] == ["Hello there", "real message"]


def test_unknown_part_type_skipped_without_crash() -> None:
    detail = _detail(
        conversation_parts={
            "conversation_parts": [_part("brand_new_kind", author_type="admin", body="???")]
        }
    )
    ticket = normalize_conversation(detail, workspace_app_id="ws", customer_contact=None)
    assert all(p.body != "???" for p in ticket.parts)
    assert all(n.body != "???" for n in ticket.internal_notes)


def test_priority_coercion() -> None:
    assert (
        normalize_conversation(
            _detail(priority="priority"), workspace_app_id="ws", customer_contact=None
        ).priority
        == "priority"
    )
    assert (
        normalize_conversation(
            _detail(priority="not_priority"), workspace_app_id="ws", customer_contact=None
        ).priority
        is None
    )


def test_state_coercion_unknown_to_none() -> None:
    ticket = normalize_conversation(
        _detail(state="weird_state"), workspace_app_id="ws", customer_contact=None
    )
    assert ticket.state is None


def test_deep_link_url() -> None:
    ticket = normalize_conversation(_detail(), workspace_app_id="j3dxf22l", customer_contact=None)
    assert ticket.url == "https://app.intercom.com/a/inbox/j3dxf22l/inbox/conversation/C1"


def test_contact_enrichment_populates_panel_fields() -> None:
    contact = {
        "id": "contact_1",
        "external_id": "user-42",
        "name": "Ada Lovelace",
        "email": "ada@x.com",
        "phone": "+15551234",
        "location": {"city": "London", "region": "England", "country": "UK"},
        "companies": {"data": [{"name": "Analytical Engines"}]},
    }
    ticket = normalize_conversation(_detail(), workspace_app_id="ws", customer_contact=contact)
    a = ticket.author
    assert a.id == "user-42"  # external_id preferred (Intercom "User id")
    assert a.name == "Ada Lovelace"
    assert a.phone == "+15551234"
    assert a.location == "London, England, UK"
    assert a.company == "Analytical Engines"


def test_missing_contact_degrades_to_source_author() -> None:
    ticket = normalize_conversation(_detail(), workspace_app_id="ws", customer_contact=None)
    a = ticket.author
    assert a.id == "u1"
    assert a.email == "ada@x.com"
    assert a.location is None
    assert a.phone is None


def test_customer_contact_id_resolution() -> None:
    assert customer_contact_id(_detail()) == "contact_1"
    # Falls back to source author when no contacts/customer block.
    no_contacts = _detail(contacts={"contacts": []})
    assert customer_contact_id(no_contacts) == "u1"


def test_strip_html_and_attachment_fallback() -> None:
    assert strip_html("<p>a</p><p>b</p>") == "a\nb"
    assert strip_html("<b>x</b>&amp;y") == "x&y"
    assert strip_html(None) == ""
    assert attachment_fallback([{"name": "report.pdf"}]) == "[attachment: report.pdf]"
    assert attachment_fallback([{}]) == "[attachment]"
    assert attachment_fallback(None) == ""


def test_attachment_only_part_uses_fallback_body() -> None:
    detail = _detail(
        source={"author": {"type": "user", "id": "u1"}, "body": "", "attachments": []},
        conversation_parts={
            "conversation_parts": [
                {
                    "part_type": "comment",
                    "author": {"type": "user", "id": "u1"},
                    "body": "",
                    "created_at": _EPOCH,
                    "attachments": [{"name": "screenshot.png"}],
                }
            ]
        },
    )
    ticket = normalize_conversation(detail, workspace_app_id="ws", customer_contact=None)
    assert any("[attachment: screenshot.png]" in p.body for p in ticket.parts)
