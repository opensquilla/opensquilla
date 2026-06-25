"""The gateway service builder wires the media root into the session manager.

Fork material copy depends on ``SessionManager`` knowing where attachment/artifact
material lives. The kwarg defaults to ``None`` (a silent no-op), so a regression that
drops it from ``build_services`` would disable forked-conversation previews with no
other test failure. This pins the production wiring.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.gateway.boot import build_services
from opensquilla.gateway.config import GatewayConfig
from opensquilla.paths import media_root_from_config


@pytest.mark.asyncio
async def test_build_services_wires_media_root_into_session_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Keep the build hermetic: redirect all state off the real user home.
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "state"))
    media = tmp_path / "media"
    config = GatewayConfig(
        memory={"flush_enabled": False},
        attachments={"media_root": str(media)},
    )

    services = await build_services(
        config=config, session_db_path=":memory:", seed_agent_workspaces=False
    )
    try:
        assert services.session_manager is not None
        media_root = services.session_manager._media_root
        assert media_root is not None
        assert media_root == media_root_from_config(config)
    finally:
        await services.close()
