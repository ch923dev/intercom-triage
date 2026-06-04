"""Phase 1 — token primitives: access-JWT mint/verify."""

from __future__ import annotations

import pytest

from app.security import tokens

SECRET = "unit-test-secret"


def test_mint_then_verify_roundtrips_claims() -> None:
    token = tokens.mint_access_token(
        SECRET,
        user_id=7,
        onlysales_id="abc123",
        email="op@example.com",
        scope="admin",
        ttl_seconds=1800,
    )
    claims = tokens.verify_access_token(SECRET, token)
    assert claims.user_id == 7
    assert claims.onlysales_id == "abc123"
    assert claims.email == "op@example.com"
    assert claims.scope == "admin"


def test_verify_rejects_wrong_secret() -> None:
    token = tokens.mint_access_token(
        SECRET, user_id=1, onlysales_id="a", email="e", scope=None, ttl_seconds=1800
    )
    with pytest.raises(tokens.TokenError):
        tokens.verify_access_token("other-secret", token)


def test_verify_rejects_expired() -> None:
    token = tokens.mint_access_token(
        SECRET, user_id=1, onlysales_id="a", email="e", scope=None, ttl_seconds=-1
    )
    with pytest.raises(tokens.TokenError):
        tokens.verify_access_token(SECRET, token)


def test_verify_rejects_garbage() -> None:
    with pytest.raises(tokens.TokenError):
        tokens.verify_access_token(SECRET, "not-a-jwt")


def test_refresh_token_is_random_and_hash_is_stable() -> None:
    raw1 = tokens.generate_refresh_token()
    raw2 = tokens.generate_refresh_token()
    assert raw1 != raw2
    assert len(raw1) >= 32
    assert tokens.hash_refresh_token(raw1) == tokens.hash_refresh_token(raw1)
    assert tokens.hash_refresh_token(raw1) != tokens.hash_refresh_token(raw2)


def test_encrypt_decrypt_upstream_roundtrips() -> None:
    key = tokens.generate_encryption_key()
    blob = tokens.encrypt_secret(key, "onlysales-refresh-xyz")
    assert blob != "onlysales-refresh-xyz"
    assert tokens.decrypt_secret(key, blob) == "onlysales-refresh-xyz"


def test_encrypt_with_empty_key_returns_none() -> None:
    assert tokens.encrypt_secret("", "anything") is None
    assert tokens.decrypt_secret("", "anything") is None
