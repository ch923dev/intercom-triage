"""Token primitives — pure, no DB.

Access tokens are stateless HS256 JWTs verified offline on every request.
Refresh tokens are opaque random strings stored only as a sha256 hash; the
upstream OnlySales refresh token is encrypted at rest with Fernet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import jwt

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
        payload = jwt.decode(token, secret, algorithms=[_ALGO])
    except jwt.PyJWTError as exc:  # signature, expiry, malformed — all subclasses
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
