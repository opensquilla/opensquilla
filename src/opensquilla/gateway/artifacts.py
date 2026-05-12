"""HTTP download route for generated artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from opensquilla.artifacts import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactStore,
)
from opensquilla.gateway.config import GatewayConfig
from opensquilla.paths import media_root_from_config


async def _session_id_for_download(session_manager: Any, session_key: str) -> str | None:
    if not session_key:
        return None
    if session_manager is None:
        return session_key
    get_session = getattr(session_manager, "get_session", None)
    if not callable(get_session):
        return session_key
    try:
        session = await get_session(session_key)
    except Exception:
        return None
    session_id = getattr(session, "session_id", None)
    return session_id if isinstance(session_id, str) and session_id else None


def _media_root_from_config(config: GatewayConfig) -> Path:
    return media_root_from_config(config)


def register_artifact_routes(
    app: Starlette,
    *,
    config: GatewayConfig,
    session_manager: Any = None,
) -> None:
    """Register GET /api/v1/artifacts/{artifact_id} on the given Starlette app."""

    async def download_handler(request: Request) -> FileResponse | JSONResponse:
        artifact_id = request.path_params.get("artifact_id", "")
        session_key = (
            request.query_params.get("sessionKey")
            or request.query_params.get("session_key")
            or request.headers.get("x-opensquilla-session-key")
            or ""
        )
        session_id = await _session_id_for_download(session_manager, session_key)
        if not session_id:
            return JSONResponse(
                {"error": "Artifact not found", "code": "NOT_FOUND"},
                status_code=404,
            )

        store = ArtifactStore(_media_root_from_config(config))
        try:
            ref, path = store.resolve_for_download(str(artifact_id), session_id=session_id)
        except ArtifactIntegrityError as exc:
            return JSONResponse({"error": str(exc), "code": "INTEGRITY_ERROR"}, status_code=409)
        except (ArtifactNotFoundError, ValueError):
            return JSONResponse(
                {"error": "Artifact not found", "code": "NOT_FOUND"},
                status_code=404,
            )

        return FileResponse(path, media_type=ref.mime, filename=ref.name)

    app.router.routes.append(
        Route("/api/v1/artifacts/{artifact_id}", download_handler, methods=["GET", "HEAD"])
    )
