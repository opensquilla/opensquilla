"""Starlette ASGI application factory with routes and middleware."""

from __future__ import annotations

import time
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

from opensquilla import __version__
from opensquilla.gateway.approval_queue import get_approval_queue
from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.control_ui import create_control_ui_routes
from opensquilla.gateway.middleware import (
    AuthMiddleware,
    ErrorHandlingMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.gateway.websocket import handle_ws_connection

_start_time = time.time()


def create_gateway_app(
    config: GatewayConfig,
    session_manager: Any = None,
    provider_selector: Any = None,
    tool_registry: Any = None,
    subscription_manager: Any = None,
    channel_manager: Any = None,
    usage_tracker: Any = None,
    meta_run_writer: Any = None,
    skill_loader: Any = None,
    cron_scheduler: Any = None,
    turn_runner: Any = None,
    task_runtime: Any = None,
    flush_service: Any = None,
    heartbeat_service: Any = None,
    heartbeat_loop: Any = None,
    agent_registry: Any = None,
    diagnostics_state: Any = None,
    memory_managers: dict[str, Any] | None = None,
    memory_stores: dict[str, Any] | None = None,
    memory_retrievers: dict[str, Any] | None = None,
    extra_routes: list[Route] | None = None,
) -> Starlette:
    """Build and return the Starlette ASGI application."""
    if diagnostics_state is None:
        from opensquilla.gateway.diagnostics import DiagnosticsState

        diagnostics_state = DiagnosticsState.from_config(config)

    dispatcher = get_dispatcher()

    def _rpc_status_code(result: Any, default: int = 500) -> int:
        if result.error is None:
            return default
        code = result.error.code
        if code == "INVALID_REQUEST":
            return 400
        if code == "UNAUTHORIZED":
            return 403
        if code in {"NOT_FOUND", "METHOD_NOT_FOUND"}:
            return 404
        if code == "UNAVAILABLE":
            return 503
        return default

    # ── HTTP endpoint handlers ───────────────────────────────────────────────

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "status": "live"})

    async def root(request: Request) -> RedirectResponse:
        return RedirectResponse(url=f"{config.control_ui.base_path}/")

    async def ready(request: Request) -> JSONResponse:
        uptime = int((time.time() - _start_time) * 1000)
        is_ready = bool(getattr(request.app.state, "gateway_ready", True))
        payload = {
            "ready": is_ready,
            "status": "ready" if is_ready else "starting",
            "uptime_ms": uptime,
        }
        return JSONResponse(payload, status_code=200 if is_ready else 503)

    async def api_config(request: Request) -> JSONResponse:
        ctx = _make_ctx(request)
        result = await dispatcher.dispatch("_http", "config.get", None, ctx)
        if result.ok:
            return JSONResponse(result.payload or {})
        msg = result.error.message if result.error else "error"
        return JSONResponse({"error": msg}, status_code=_rpc_status_code(result))

    async def api_sessions(request: Request) -> JSONResponse:
        ctx = _make_ctx(request)
        params: dict[str, object] = {}
        raw_limit = request.query_params.get("limit")
        if raw_limit:
            try:
                params["limit"] = int(raw_limit)
            except ValueError:
                return JSONResponse({"error": "limit must be an integer"}, status_code=400)
        view = request.query_params.get("view")
        if view:
            params["view"] = view
        result = await dispatcher.dispatch("_http", "sessions.list", params or None, ctx)
        if result.ok:
            return JSONResponse(result.payload or {"sessions": []})
        msg = result.error.message if result.error else "error"
        return JSONResponse({"error": msg}, status_code=_rpc_status_code(result))

    async def api_chat(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        ctx = _make_ctx(request)
        result = await dispatcher.dispatch("_http", "chat.send", body, ctx)
        if result.ok:
            return JSONResponse({"ok": True, **(result.payload or {})})
        return JSONResponse(
            {"error": result.error.message if result.error else "error"},
            status_code=_rpc_status_code(result, default=400),
        )

    async def api_system_status(request: Request) -> JSONResponse:
        uptime = int((time.time() - _start_time) * 1000)
        provider_name = None
        if provider_selector is not None:
            # Report the *configured* provider id (e.g. "openrouter"), not the
            # wire-protocol backend class. OpenAI-compatible providers
            # (openrouter / deepseek / gemini) are all served by OpenAIProvider,
            # so introspecting the instance would mislabel them as "openai".
            provider_name = getattr(provider_selector, "active_provider_id", None)
            if not provider_name:
                try:
                    p = provider_selector.resolve()
                    provider_name = getattr(p, "name", None) or type(p).__name__
                except Exception:
                    pass
        return JSONResponse(
            {
                "version": __version__,
                "uptime_ms": uptime,
                "status": "running",
                "provider": provider_name,
                "auth_mode": config.auth.mode,
            }
        )

    async def api_system_shutdown(request: Request) -> JSONResponse:
        """Owner-only graceful shutdown trigger.

        Signals the run loop to run the full ``GatewayServer.close()`` drain
        (in-flight agent turns + background completions, then scheduler/channel
        teardown) and exit. This is the cross-platform shutdown path the CLI and
        desktop use where POSIX signals are unavailable or unreliable — notably
        Windows, which has no real ``SIGTERM`` (``os.kill`` / ``child.kill`` map
        to an immediate ``TerminateProcess`` that skips the drain).

        Gated on loopback-proven ownership so a remote peer can never stop the
        gateway. Returns 202 once the drain is requested (the response flushes
        before the server stops, since ``close()`` drains before unbinding), and
        503 when no run loop is attached (app built without a server — e.g. in
        tests or embedded ``run=False`` use).
        """
        ctx = _make_ctx(request)
        if not ctx.principal.is_owner:
            return JSONResponse({"error": "owner privileges required"}, status_code=403)
        request_shutdown = getattr(request.app.state, "request_shutdown", None)
        if request_shutdown is None:
            return JSONResponse(
                {"error": "graceful shutdown is not available in this mode"},
                status_code=503,
            )
        request_shutdown("api_shutdown")
        return JSONResponse({"status": "accepted"}, status_code=202)

    async def api_usage(request: Request) -> JSONResponse:
        ctx = _make_ctx(request)
        result = await dispatcher.dispatch("_http", "usage.status", None, ctx)
        if result.ok:
            # Merge breakdown from usage.cost into the status response
            cost_result = await dispatcher.dispatch("_http", "usage.cost", None, ctx)
            payload = result.payload or {}
            if cost_result.ok and cost_result.payload:
                payload["breakdown"] = cost_result.payload.get("breakdown", [])
                payload["totalSessions"] = payload.get("totalSessions", 0)
            return JSONResponse(payload)
        msg = result.error.message if result.error else "error"
        return JSONResponse({"error": msg}, status_code=_rpc_status_code(result))

    def _extract_http_token(request: Request | None) -> str | None:
        if request is None:
            return None
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
        token_header = request.headers.get("x-opensquilla-token")
        if token_header:
            return token_header
        return request.query_params.get("token")

    def _make_ctx(request: Request | None = None, role_claim: str = "operator") -> RpcContext:
        from opensquilla.gateway.auth import Principal, resolve_auth

        auth_params: dict[str, str] = {}
        token = _extract_http_token(request)
        if token:
            auth_params["token"] = token
        peer_ip = request.client.host if request is not None and request.client else None
        principal = resolve_auth(
            config,
            auth_params=auth_params,
            role_claim=role_claim,
            peer_ip=peer_ip,
        )
        if principal is None:
            principal = Principal(
                role=role_claim,
                scopes=frozenset(),
                is_owner=False,
                authenticated=False,
            )
        return RpcContext(
            conn_id="http",
            principal=principal,
            session_manager=session_manager,
            config=config,
            provider_selector=provider_selector,
            tool_registry=tool_registry,
            subscription_manager=subscription_manager,
            channel_manager=channel_manager,
            usage_tracker=usage_tracker,
            meta_run_writer=meta_run_writer,
            skill_loader=skill_loader,
            cron_scheduler=cron_scheduler,
            turn_runner=turn_runner,
            task_runtime=task_runtime,
            flush_service=flush_service,
            heartbeat_service=heartbeat_service,
            heartbeat_loop=heartbeat_loop,
            agent_registry=agent_registry,
            diagnostics_state=diagnostics_state,
            memory_managers=memory_managers or {},
            memory_stores=memory_stores or {},
            memory_retrievers=memory_retrievers or {},
        )

    async def api_channels_status(request: Request) -> JSONResponse:
        ctx = _make_ctx(request)
        result = await dispatcher.dispatch("_http", "channels.status", None, ctx)
        if result.ok:
            return JSONResponse(result.payload or {"channels": []})
        msg = result.error.message if result.error else "error"
        return JSONResponse({"error": msg}, status_code=_rpc_status_code(result))

    async def api_channels_logout(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        ctx = _make_ctx(request)
        result = await dispatcher.dispatch("_http", "channels.logout", body, ctx)
        if result.ok:
            return JSONResponse(result.payload or {"ok": True})
        msg = result.error.message if result.error else "error"
        return JSONResponse({"error": msg}, status_code=_rpc_status_code(result, default=400))

    async def api_approvals(request: Request) -> JSONResponse:
        ctx = _make_ctx(request)
        result = await dispatcher.dispatch("_http", "exec.approvals.get", None, ctx)
        if not result.ok:
            return JSONResponse(
                {"error": result.error.message if result.error else "error"},
                status_code=_rpc_status_code(result),
            )
        settings = result.payload or {}
        mode = settings.get("mode", "prompt")
        queue = get_approval_queue()
        pending = queue.list_pending()
        # Enrich pending items with params fields for UI display
        items = []
        for p in pending:
            item = {
                "id": p["id"],
                "namespace": p["namespace"],
                "created_at": p.get("created_at"),
                "deadline": p.get("deadline"),
            }
            params = p.get("params", {})
            argv = params.get("argv")
            command = params.get("command")
            if not command and isinstance(argv, list):
                command = " ".join(str(part) for part in argv)
            item["toolName"] = params.get(
                "toolName",
                params.get("pluginId", params.get("action_kind", "Unknown")),
            )
            item["sessionKey"] = params.get("sessionKey", params.get("session_id", ""))
            item["agent"] = params.get("agent", "")
            item["args"] = params.get("args", params.get("permissions"))
            item["command"] = command or ""
            item["warning"] = params.get("warning", params.get("reason", ""))
            item["actionKind"] = params.get("action_kind", "")
            item["argv"] = argv if isinstance(argv, list) else []
            item["mode"] = params.get("mode", mode)
            item["params"] = params
            items.append(item)
        return JSONResponse(
            {
                "pending": items,
                "mode": mode,
                "allowPatterns": settings.get("allowPatterns", []),
                "denyPatterns": settings.get("denyPatterns", []),
            }
        )

    async def api_approvals_settings(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        mode = body.get("mode")
        if mode not in {"prompt", "auto-approve", "auto-deny"}:
            return JSONResponse(
                {"error": "mode must be prompt, auto-approve, or auto-deny"},
                status_code=400,
            )
        ctx = _make_ctx(request)
        result = await dispatcher.dispatch(
            "_http",
            "exec.approvals.set",
            {
                "mode": mode,
                "allowPatterns": body.get("allowPatterns"),
                "denyPatterns": body.get("denyPatterns"),
            },
            ctx,
        )
        if not result.ok:
            return JSONResponse(
                {"error": result.error.message if result.error else "error"},
                status_code=_rpc_status_code(result),
            )
        queue = get_approval_queue()
        settings = queue.get_settings()
        return JSONResponse(
            {
                "mode": settings.mode,
                "allowPatterns": settings.allow_patterns,
                "denyPatterns": settings.deny_patterns,
            }
        )

    async def api_approvals_resolve(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        approval_id = body.get("id")
        approved = body.get("approved", False)
        namespace = body.get("namespace", "exec")
        if not approval_id:
            return JSONResponse({"error": "id is required"}, status_code=400)
        ctx = _make_ctx(request)
        method = "plugin.approval.resolve" if namespace == "plugin" else "exec.approval.resolve"
        resolve_params = {
            "id": approval_id,
            "approved": approved,
            "allowAlways": bool(body.get("allowAlways", False)),
            "rememberIntent": bool(body.get("rememberIntent", False)),
        }
        choice = body.get("choice") or body.get("decision")
        if isinstance(choice, str) and choice.strip():
            resolve_params["choice"] = choice.strip()
        result = await dispatcher.dispatch(
            "_http",
            method,
            resolve_params,
            ctx,
        )
        if result.ok:
            return JSONResponse(result.payload or {"ok": True})
        return JSONResponse(
            {"error": result.error.message if result.error else "error"},
            status_code=_rpc_status_code(result),
        )

    async def api_elevated_mode(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        ctx = _make_ctx(request)
        if not ctx.principal.is_owner:
            return JSONResponse({"error": "owner privileges required"}, status_code=403)
        session_key = str(body.get("sessionKey") or body.get("session_key") or "").strip()
        if not session_key:
            return JSONResponse({"error": "sessionKey is required"}, status_code=400)
        raw_mode = body.get("mode")
        mode = None if raw_mode in (None, "", "off") else str(raw_mode)
        if mode not in (None, "on", "bypass", "full"):
            return JSONResponse(
                {"error": "mode must be off, on, bypass, or full"},
                status_code=400,
            )
        queue = get_approval_queue()
        try:
            queue.set_elevated_mode(session_key, mode)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        resolved_pending = 0
        if mode in ("bypass", "full"):
            resolved_pending = queue.resolve_pending_for_session(
                session_key,
                approved=True,
                elevated_mode=mode,
            )
        return JSONResponse(
            {
                "sessionKey": session_key,
                "mode": mode or "off",
                "resolvedPending": resolved_pending,
            }
        )

    # ── Agents / Cron HTTP endpoints ────────────────────────────────────────

    async def api_agents(request: Request) -> JSONResponse:
        ctx = _make_ctx(request)
        result = await dispatcher.dispatch("_http", "agents.list", None, ctx)
        if result.ok:
            return JSONResponse(result.payload or {"agents": []})
        return JSONResponse(
            {"error": result.error.message if result.error else "error"},
            status_code=_rpc_status_code(result),
        )

    async def api_cron(request: Request) -> JSONResponse:
        ctx = _make_ctx(request)
        result = await dispatcher.dispatch("_http", "cron.list", None, ctx)
        if result.ok:
            return JSONResponse(
                result.payload
                if isinstance(result.payload, list)
                else {"jobs": result.payload or []}
            )
        return JSONResponse({"jobs": []})

    # ── WebSocket handler ────────────────────────────────────────────────────

    async def api_chat_history(request: Request) -> JSONResponse:
        """GET /api/chat/history?sessionKey=xxx — return chat transcript."""
        session_key = request.query_params.get("sessionKey", "agent:main:webchat:default")
        ctx = _make_ctx(request)
        result = await dispatcher.dispatch(
            "_http", "chat.history", {"sessionKey": session_key}, ctx
        )
        if result.ok:
            return JSONResponse(result.payload or {"messages": []})
        return JSONResponse(
            {"error": result.error.message if result.error else "error"},
            status_code=_rpc_status_code(result),
        )

    async def ws_endpoint(ws: WebSocket) -> None:
        await handle_ws_connection(
            ws,
            config,
            dispatcher,
            session_manager,
            provider_selector=provider_selector,
            tool_registry=tool_registry,
            subscription_manager=subscription_manager,
            channel_manager=channel_manager,
            usage_tracker=usage_tracker,
            meta_run_writer=meta_run_writer,
            skill_loader=skill_loader,
            cron_scheduler=cron_scheduler,
            turn_runner=turn_runner,
            task_runtime=task_runtime,
            flush_service=flush_service,
            heartbeat_service=heartbeat_service,
            heartbeat_loop=heartbeat_loop,
            agent_registry=agent_registry,
            diagnostics_state=diagnostics_state,
            memory_managers=memory_managers,
            memory_stores=memory_stores,
            memory_retrievers=memory_retrievers,
        )

    # ── Routes ───────────────────────────────────────────────────────────────

    routes = [
        Route("/", root, methods=["GET"]),
        Route("/health", health, methods=["GET"]),
        Route("/healthz", health, methods=["GET"]),
        Route("/ready", ready, methods=["GET"]),
        Route("/readyz", ready, methods=["GET"]),
        Route("/api/config", api_config, methods=["GET"]),
        Route("/api/sessions", api_sessions, methods=["GET"]),
        Route("/api/chat", api_chat, methods=["POST"]),
        Route("/api/chat/history", api_chat_history, methods=["GET"]),
        Route("/api/agents", api_agents, methods=["GET"]),
        Route("/api/cron", api_cron, methods=["GET"]),
        Route("/api/system/status", api_system_status, methods=["GET"]),
        Route("/api/system/shutdown", api_system_shutdown, methods=["POST"]),
        Route("/api/usage", api_usage, methods=["GET"]),
        Route("/api/channels/status", api_channels_status, methods=["GET"]),
        Route("/api/channels/logout", api_channels_logout, methods=["POST"]),
        Route("/api/approvals", api_approvals, methods=["GET"]),
        Route("/api/approvals/settings", api_approvals_settings, methods=["POST"]),
        Route("/api/approvals/resolve", api_approvals_resolve, methods=["POST"]),
        Route("/api/elevated-mode", api_elevated_mode, methods=["POST"]),
        WebSocketRoute("/ws", ws_endpoint),
    ]

    # ── Channel webhook routes (Slack, Feishu) ────────────────────────────
    if extra_routes:
        routes.extend(extra_routes)

    # ── Control UI routes ────────────────────────────────────────────────
    routes.extend(create_control_ui_routes(config))

    # ── Middleware ───────────────────────────────────────────────────────────

    middleware = [
        Middleware(ErrorHandlingMiddleware),
        Middleware(
            CORSMiddleware,
            allow_origins=config.cors.allowed_origins,
            allow_credentials=config.cors.allow_credentials,
            allow_methods=config.cors.allowed_methods,
            allow_headers=config.cors.allowed_headers,
        ),
        Middleware(RateLimitMiddleware, config=config),
        Middleware(SecurityHeadersMiddleware, path_prefix=config.control_ui.base_path),
        Middleware(AuthMiddleware, config=config),
    ]

    app = Starlette(routes=routes, middleware=middleware, debug=config.debug)
    app.state.diagnostics_state = diagnostics_state

    # Bridge upload endpoint: self-hosted multipart sink that
    # returns an opaque file_uuid the chat.send validator can resolve.
    from opensquilla.gateway.uploads import (  # noqa: PLC0415 — local import keeps app.py boot light
        get_upload_store,
        register_upload_routes,
    )

    register_upload_routes(app, config=config, store=get_upload_store())
    from opensquilla.gateway.artifacts import register_artifact_routes  # noqa: PLC0415
    from opensquilla.gateway.attachments import register_attachment_routes  # noqa: PLC0415
    from opensquilla.gateway.audio_transcription import (  # noqa: PLC0415
        register_audio_transcription_routes,
    )

    register_attachment_routes(
        app,
        config=config,
        session_manager=session_manager,
    )
    register_artifact_routes(
        app,
        config=config,
        session_manager=session_manager,
    )
    register_audio_transcription_routes(app, config=config)

    return app
