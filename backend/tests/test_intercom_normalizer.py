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
    # Only source + the one real comment survive; bodyless events carry no text.
    assert [p.body for p in ticket.parts] == ["Hello there", "real message"]


def test_assignment_with_body_surfaces_as_admin_reply() -> None:
    # Intercom's "reply and assign" attaches the admin's reply text to an
    # `assignment` event (observed live). A bodyless assignment is still skipped;
    # a bodied one is a real customer-visible reply and must reach parts[].
    detail = _detail(
        conversation_parts={
            "conversation_parts": [
                _part("default_assignment", author_type="bot", body=""),  # routing, dropped
                _part("assignment", author_type="admin", body="Good morning, here is the fix"),
                _part("comment", author_type="user", body="thanks"),
            ]
        }
    )
    ticket = normalize_conversation(detail, workspace_app_id="ws", customer_contact=None)
    bodies = [p.body for p in ticket.parts]
    assert "Good morning, here is the fix" in bodies
    reply = next(p for p in ticket.parts if p.body == "Good morning, here is the fix")
    assert reply.is_admin is True
    assert ticket.internal_notes == []  # never an internal note (invariant #4)


def test_reply_time_notice_skipped_not_logged_unknown() -> None:
    # The auto "you'll get replies here · reply time 1 day" channel notice
    # (part_type=channel_and_reply_time_expectation, bot author) is boilerplate —
    # kept out of parts[] AND out of the unknown-part_type log.
    detail = _detail(
        conversation_parts={
            "conversation_parts": [
                _part(
                    "channel_and_reply_time_expectation",
                    author_type="bot",
                    body="You'll get replies here and in your email",
                ),
            ]
        }
    )
    ticket = normalize_conversation(detail, workspace_app_id="ws", customer_contact=None)
    assert all("replies here" not in p.body for p in ticket.parts)


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


def test_entity_encoded_display_fields_decoded() -> None:
    # Intercom HTML-entity-encodes free-text fields (name/company/title) the same
    # way it encodes bodies; these short fields bypass strip_html, so the
    # normalizer must decode them or the webapp renders `O&#39;Neill` literally.
    contact = {
        "id": "contact_1",
        "name": "Vincent O&#39;Neill",
        "companies": {"data": [{"name": "Jones &amp; Co"}]},
        "location": {"city": "Côte d&#39;Or", "region": None, "country": "FR"},
    }
    ticket = normalize_conversation(
        _detail(title="Can&#39;t log in &amp; reset"),
        workspace_app_id="ws",
        customer_contact=contact,
    )
    assert ticket.author.name == "Vincent O'Neill"
    assert ticket.author.company == "Jones & Co"
    assert ticket.author.location == "Côte d'Or, FR"
    assert ticket.title == "Can't log in & reset"


def test_entity_encoded_part_author_name_decoded() -> None:
    detail = _detail(
        conversation_parts={
            "conversation_parts": [
                {
                    "part_type": "comment",
                    "author": {"type": "admin", "id": "a1", "name": "O&#39;Brien"},
                    "body": "reply",
                    "created_at": _EPOCH,
                    "attachments": [],
                }
            ]
        }
    )
    ticket = normalize_conversation(detail, workspace_app_id="ws", customer_contact=None)
    admin = [p for p in ticket.parts if p.is_admin]
    assert any(p.author.name == "O'Brien" for p in admin)


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


def test_inline_image_extracted_from_body() -> None:
    # Intercom embeds pasted screenshots as inline <img> in the body HTML (not in
    # attachments[]); strip_html drops the tag, so the URL must be surfaced
    # separately or the operator never sees the screenshot. The signed CDN URL
    # carries &amp;-escaped query params that must be decoded to stay valid.
    img = (
        '<div class="intercom-container">'
        '<img src="https://cdn.example.com/s.png?a=1&amp;b=2"></div>'
        "<p>see screenshot</p>"
    )
    detail = _detail(
        source={
            "author": {"type": "user", "id": "u1", "name": "Ada"},
            "body": img,
            "attachments": [],
        }
    )
    ticket = normalize_conversation(detail, workspace_app_id="ws", customer_contact=None)
    assert ticket.parts[0].body == "see screenshot"
    assert ticket.parts[0].images == ["https://cdn.example.com/s.png?a=1&b=2"]


def test_image_only_part_emitted_with_empty_body() -> None:
    # A message/note that is *only* an image (no text) must still surface — the
    # old `if not body: continue` guard would have dropped it entirely.
    detail = _detail(
        source={"author": {"type": "user", "id": "u1"}, "body": "", "attachments": []},
        conversation_parts={
            "conversation_parts": [
                {
                    "part_type": "comment",
                    "author": {"type": "user", "id": "u1"},
                    "body": '<img src="https://cdn.example.com/only.png">',
                    "created_at": _EPOCH,
                    "attachments": [],
                }
            ]
        },
    )
    ticket = normalize_conversation(detail, workspace_app_id="ws", customer_contact=None)
    assert any(
        p.images == ["https://cdn.example.com/only.png"] and p.body == "" for p in ticket.parts
    )


def test_inline_image_in_note_extracted() -> None:
    detail = _detail(
        conversation_parts={
            "conversation_parts": [
                {
                    "part_type": "note",
                    "author": {"type": "admin", "id": "a1", "name": "Tess"},
                    "body": '<p>fyi</p><img src="https://cdn.example.com/n.png">',
                    "created_at": _EPOCH,
                    "attachments": [],
                }
            ]
        }
    )
    ticket = normalize_conversation(detail, workspace_app_id="ws", customer_contact=None)
    assert ticket.internal_notes[0].images == ["https://cdn.example.com/n.png"]
    assert ticket.internal_notes[0].body == "fyi"


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
