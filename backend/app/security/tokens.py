"""Token primitives — pure, no DB.

Access tokens are stateless HS256 JWTs verified offline on every request.
Refresh tokens are opaque random strings stored only as a sha256 hash; the
upstream OnlySales refresh token is encrypted at rest with Fernet.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

import jwt
from cryptography.fernet import Fernet, InvalidToken

_ALGO = "HS256"


class TokenError(Exception):
    """Raised when an access token is missing, malformed, or expired."""


@dataclass(frozen=True)
class AccessClaims:
    user_id: int
    onlysales_id: str
    email: str
    scope: str | None


def mint_access_token(
    secret: str,
    *,
    user_id: int,
    onlysales_id: str,
    email: str,
    scope: str | None,
    ttl_seconds: int,
) -> str:
    """Encode a short-lived access JWT. `ttl_seconds` may be negative (tests)."""
    now = int(datetime.now(UTC).timestamp())
    payload = {
        "sub": str(user_id),
        "oid": onlysales_id,
        "email": email,
        "scope": scope,
        "type": "access",
        "iat": now,
        "exp": now + ttl_seconds,
    }
    return jwt.encode(payload, secret, algorithm=_ALGO)


def verify_access_token(secret: str, token: str) -> AccessClaims:
    """Decode + validate signature/exp/type. Raises TokenError on any failure."""
    try:
        payload = jwt.decode(token, secret, algorithms=[_ALGO], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError as exc:  # signature, expiry, malformed, missing-claim — all subclasses
        raise TokenError(str(exc)) from exc
    if payload.get("type") != "access":
        raise TokenError("not an access token")
    try:
        return AccessClaims(
            user_id=int(payload["sub"]),
            onlysales_id=str(payload["oid"]),
            email=str(payload["email"]),
            scope=payload.get("scope"),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise TokenError(f"malformed claims: {exc}") from exc


def generate_refresh_token() -> str:
    """Opaque, URL-safe random refresh token (~48 bytes of entropy)."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw: str) -> str:
    """Stable sha256 hex of a refresh token — only the hash is ever stored."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_encryption_key() -> str:
    """A fresh Fernet key (urlsafe base64). Used to seed config in tests/setup."""
    return Fernet.generate_key().decode("ascii")


def encrypt_secret(key: str, plaintext: str) -> str | None:
    """Encrypt the upstream refresh token. Empty key → None (storage disabled)."""
    if not key:
        return None
    return Fernet(key.encode("ascii")).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(key: str, blob: str | None) -> str | None:
    """Decrypt; returns None on empty key/blob or any tampering."""
    if not key or not blob:
        return None
    try:
        return Fernet(key.encode("ascii")).decrypt(blob.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
