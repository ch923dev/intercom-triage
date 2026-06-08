"""Phase 1 — boot guard: the app must refuse to start without SESSION_JWT_SECRET.

A missing signing secret would let every access JWT be forged, so the lifespan
hard-fails rather than booting with an empty/insecure default (no degraded-boot
path for this secret, unlike the optional AI / Intercom tokens).
"""

from __future__ import annotations

import pytest

import app.main as main_mod
from app.config import AppConfig
from app.main import create_app, lifespan


@pytest.mark.asyncio
async def test_boot_refuses_without_session_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_mod, "get_config", lambda: AppConfig(session_jwt_secret=""))
    application = create_app()
    with pytest.raises(RuntimeError, match="SESSION_JWT_SECRET"):
        async with lifespan(application):
            pass  # pragma: no cover — the guard raises before yield
