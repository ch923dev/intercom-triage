"""OnlySales auth proxy — login + refresh against pyapi.onlysales.io.

Mirrors chrome-extension/api.js: normalizes `user.id → onlysales_id`, joins
firstName+lastName, surfaces a human error. We never store OnlySales passwords;
this is the only path that sees them, in-flight, to forward upstream.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


class OnlySalesAuthError(Exception):
    """Raised on any login/refresh failure (bad creds, unverified, upstream down)."""


@dataclass(frozen=True)
class OnlySalesIdentity:
    access_token: str
    refresh_token: str | None
    onlysales_id: str
    email: str
    name: str | None
    scope: str | None


def _extract_error(body: object, fallback: str) -> str:
    if isinstance(body, dict):
        for key in ("message", "detail", "name"):
            val = body.get(key)
            if isinstance(val, str) and val:
                return val
    return fallback


def _parse_identity(data: dict[str, object]) -> OnlySalesIdentity:
    if data.get("name") == "AccountNotVerified":
        raise OnlySalesAuthError("Account not verified")
    access = data.get("accessToken")
    if not isinstance(access, str) or not access:
        raise OnlySalesAuthError(_extract_error(data, "Login failed"))
    user = data.get("user")
    if not isinstance(user, dict):
        raise OnlySalesAuthError("Unexpected auth response")
    oid = user.get("_id") or user.get("id")
    email = user.get("email")
    if not isinstance(oid, str) or not isinstance(email, str):
        raise OnlySalesAuthError("Auth response missing user id/email")
    first = user.get("firstName") or ""
    last = user.get("lastName") or ""
    name = f"{first} {last}".strip() or None
    scope = user.get("scope") if isinstance(user.get("scope"), str) else None
    refresh = data.get("refreshToken")
    return OnlySalesIdentity(
        access_token=access,
        refresh_token=refresh if isinstance(refresh, str) else None,
        onlysales_id=oid,
        email=email.strip().lower(),
        name=name,
        scope=scope,
    )


class OnlySalesClient:
    def __init__(
        self,
        *,
        base: str = "https://pyapi.onlysales.io",
        version: str = "0.1.0",
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            base_url=base,
            headers={"X-Version": version, "Content-Type": "application/json"},
            timeout=httpx.Timeout(20.0),
        )

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def login(self, *, email: str, password: str) -> OnlySalesIdentity:
        try:
            resp = await self._http.post(
                "/auth/login", json={"email": email.strip().lower(), "password": password}
            )
        except httpx.HTTPError as exc:
            raise OnlySalesAuthError(f"OnlySales unreachable: {exc}") from exc
        body = resp.json() if resp.content else {}
        if resp.status_code != 200:
            raise OnlySalesAuthError(_extract_error(body, f"Login failed ({resp.status_code})"))
        if not isinstance(body, dict):
            raise OnlySalesAuthError("Unexpected auth response")
        return _parse_identity(body)

    async def refresh(self, refresh_token: str) -> OnlySalesIdentity:
        try:
            resp = await self._http.post(
                "/auth/refresh-token", json={"refreshToken": refresh_token}
            )
        except httpx.HTTPError as exc:
            raise OnlySalesAuthError(f"OnlySales unreachable: {exc}") from exc
        body = resp.json() if resp.content else {}
        if resp.status_code != 200 or not isinstance(body, dict):
            raise OnlySalesAuthError(_extract_error(body, "Token refresh failed"))
        return _parse_identity(body)
