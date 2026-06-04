"""WebSocket client for connecting to OpenSquilla gateway daemon."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any, cast
from urllib.parse import urlparse

from opensquilla.session.terminal_reply import build_terminal_reply, sanitize_agent_error


class GatewayRPCError(Exception):
    """Operator-facing RPC failure raised by GatewayClient."""

    def __init__(
        self,
        method: str,
        *,
        code: str | None = None,
        message: str = "RPC failed",
        data: dict | None = None,
    ) -> None:
        self.method = method
        self.code = code
        self.message = message
        self.data = data
        super().__init__(self.__str__())

    def __str__(self) -> str:
        code = f"{self.code}: " if self.code else ""
        return f"{self.method} failed: {code}{self.message}"


def gateway_base_is_local(base_url: str | None) -> bool:
    """Return True for loopback/same-machine gateway origins.

    Unknown, unparsable, or non-loopback hosts fail closed so CLI `/path`
    cannot confuse a remote gateway with files on the operator's machine.
    """

    if not base_url:
        return False
    parsed = urlparse(base_url)
    host = parsed.hostname
    if not host:
        return False
    normalized = host.strip("[]").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


class GatewayClient:
    """WebSocket client for connecting to OpenSquilla gateway daemon."""

    def __init__(self) -> None:
        self._ws: Any = None
        self._recv_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._pending: dict[str, asyncio.Future[dict]] = {}
        self._listener_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._heartbeat_interval: float = 48.0
        self._connection_error: ConnectionError | None = None
        self._closing = False
        self._http_base: str | None = None
        self._auth_token: str | None = None

    async def connect(
        self,
        url: str = "ws://localhost:18791/ws",
        *,
        token: str | None = None,
    ) -> None:
        """Connect to gateway. Raises SystemExit with friendly message on failure."""
        has_existing_connection = (
            self._ws is not None
            or self._listener_task is not None
            or self._heartbeat_task is not None
        )
        if has_existing_connection:
            await self.close()
        self._closing = False
        self._connection_error = None
        try:
            import websockets
        except ImportError:
            raise SystemExit("websockets package is required: uv pip install websockets")

        try:
            self._ws = await websockets.connect(url)
        except Exception as exc:
            raise SystemExit(
                f"Cannot connect to OpenSquilla gateway at {url}\n"
                f"Is the gateway running? Start it with: opensquilla gateway run\n"
                f"Error: {exc}"
            )

        # Cache an HTTP base derived from the WS URL for the bridge upload
        # endpoint. ws://host:port/ws -> http://host:port; same scheme swap
        # for wss:// -> https://.
        if url.startswith("ws://"):
            base = "http://" + url[len("ws://") :]
        elif url.startswith("wss://"):
            base = "https://" + url[len("wss://") :]
        else:
            base = url
        if base.endswith("/ws"):
            base = base[: -len("/ws")]
        self._http_base = base.rstrip("/")
        self._auth_token = token

        # Wait for connect.challenge
        raw = await self._ws.recv()
        challenge = json.loads(raw)
        if challenge.get("type") != "event" or challenge.get("event") != "connect.challenge":
            raise SystemExit(f"Unexpected handshake frame: {challenge}")

        # Send connect request
        req_id = str(uuid.uuid4())
        params: dict[str, Any] = {
            "minProtocol": 1,
            "maxProtocol": 3,
            "role": "operator",
            "scopes": ["operator.admin"],
        }
        if token:
            params["auth"] = {"token": token}
        await self._ws.send(
            json.dumps(
                {
                    "type": "req",
                    "id": req_id,
                    "method": "connect",
                    "params": params,
                }
            )
        )

        # Wait for hello-ok
        raw = await self._ws.recv()
        hello = json.loads(raw)
        if hello.get("type") != "hello-ok":
            raise SystemExit(f"Handshake failed: {hello}")
        policy = hello.get("policy") if isinstance(hello.get("policy"), dict) else {}
        self._heartbeat_interval = _heartbeat_interval_from_policy(policy)

        # Start background listener and application-level keepalive.
        self._listener_task = asyncio.create_task(self._listen())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(self._ws))

    def set_auth_token(self, token: str | None) -> None:
        """Cache a bearer token used for HTTP-side requests (e.g. uploads)."""

        self._auth_token = token

    @property
    def is_local_gateway(self) -> bool:
        """True when the connected gateway URL is loopback/same-machine."""

        return gateway_base_is_local(self._http_base)

    async def upload_file(
        self,
        path: Any,
        mime: str,
        name: str,
    ) -> str:
        """POST a file to /api/v1/files/upload and return the file_uuid.

        The CLI keeps its WebSocket connection for RPC; the bridge upload
        is a sibling HTTP request to the same gateway origin (the
        ``/api/v1/files/upload`` endpoint). Multipart only — query-token
        auth is rejected by the
        endpoint, so we always send the Authorization header when a token
        is configured. When the upload fails (network, 4xx, 5xx) the
        error is raised so the caller can surface a clear message.
        """

        if self._http_base is None:
            raise ConnectionError(
                "GatewayClient has no HTTP base URL — call connect() first"
            )
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise SystemExit("httpx package is required: uv pip install httpx") from exc

        from pathlib import Path as _Path

        local = _Path(path)
        url = f"{self._http_base}/api/v1/files/upload"
        headers: dict[str, str] = {}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"

        with local.open("rb") as fh:
            files = {"file": (name, fh, mime)}
            data = {"mime": mime}
            async with httpx.AsyncClient(timeout=60.0) as http:
                response = await http.post(url, headers=headers, files=files, data=data)

        if response.status_code != 200:
            raise ConnectionError(
                f"upload {url} failed: HTTP {response.status_code} "
                f"{response.text[:200]}"
            )
        body = response.json()
        if not isinstance(body, dict) or "file_uuid" not in body:
            raise ConnectionError(f"upload returned malformed body: {body!r}")
        return str(body["file_uuid"])

    async def _listen(self) -> None:
        """Read frames and route to pending futures or the event queue."""
        try:
            async for raw in self._ws:
                frame = json.loads(raw)
                frame_type = frame.get("type")
                if frame_type == "res":
                    fut = self._pending.pop(frame["id"], None)
                    if fut and not fut.done():
                        fut.set_result(frame)
                elif frame_type == "event":
                    await self._recv_queue.put(frame)
                elif frame_type == "pong":
                    continue
            if not self._closing:
                self._mark_connection_failed(ConnectionError("WebSocket connection closed"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Fail all pending requests so callers don't hang forever
            self._mark_connection_failed(exc)

    async def _heartbeat_loop(self, ws: Any | None = None) -> None:
        """Send application-level text pings so server receive_text() stays active."""
        heartbeat_ws = self._ws if ws is None else ws
        try:
            while True:
                await asyncio.sleep(self._heartbeat_interval)
                if self._closing or heartbeat_ws is not self._ws:
                    return
                await self._send_ping(heartbeat_ws)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._mark_connection_failed(exc)

    async def _send_ping(self, ws: Any | None = None) -> None:
        target = self._ws if ws is None else ws
        if target is None:
            raise ConnectionError("WebSocket is not connected")
        await target.send('{"type":"ping"}')

    async def _call(self, method: str, params: dict | None = None) -> Any:
        """Send a JSON-RPC request and await its response."""
        if self._connection_error is not None:
            raise self._connection_error
        if self._ws is None:
            raise ConnectionError(
                "Gateway connection lost; restart chat or reconnect before sending another command."
            )
        req_id = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[dict] = loop.create_future()
        self._pending[req_id] = fut
        try:
            await self._ws.send(
                json.dumps({"type": "req", "id": req_id, "method": method, "params": params})
            )
        except asyncio.CancelledError:
            self._pending.pop(req_id, None)
            raise
        except Exception as exc:
            self._pending.pop(req_id, None)
            err = self._mark_connection_failed(exc)
            raise err from exc
        res = await fut
        if not res.get("ok"):
            err = res.get("error", {})
            raise GatewayRPCError(
                method,
                code=err.get("code"),
                message=err.get("message") or "RPC failed",
                data=err.get("data") if isinstance(err.get("data"), dict) else None,
            )
        payload = res.get("payload")
        return {} if payload is None else payload

    async def call(self, method: str, params: dict | None = None) -> Any:
        """Public thin wrapper for CLI commands that intentionally use RPC names."""

        return await self._call(method, params)

    async def create_session(
        self,
        agent_id: str = "main",
        model: str | None = None,
        display_name: str | None = None,
    ) -> str:
        """Create a new session, return session key."""
        params: dict[str, Any] = {"agentId": agent_id, "kind": "cli"}
        if model is not None:
            params["model"] = model
        if display_name:
            params["displayName"] = display_name
        result = await self._call("sessions.create", params)
        return cast(str, result["key"])

    async def list_sessions(self, limit: int = 50) -> dict[str, Any]:
        return cast(dict[str, Any], await self._call("sessions.list", {"limit": limit}))

    async def preview_sessions(
        self,
        keys: list[str] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if keys is not None:
            params["keys"] = keys
        return cast(dict[str, Any], await self._call("sessions.preview", params))

    async def resolve_session(self, key: str) -> dict[str, Any]:
        return cast(dict[str, Any], await self._call("sessions.resolve", {"key": key}))

    async def reset_session(self, key: str) -> dict[str, Any]:
        return cast(dict[str, Any], await self._call("sessions.reset", {"key": key}))

    async def compact_session(self, key: str) -> dict[str, Any]:
        return cast(dict[str, Any], await self._call("sessions.contextCompact", {"key": key}))

    async def delete_sessions(self, keys: list[str]) -> dict[str, Any]:
        return cast(dict[str, Any], await self._call("sessions.delete", {"keys": keys}))

    async def session_history(self, session_key: str, limit: int = 1000) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self._call("chat.history", {"sessionKey": session_key, "limit": limit}),
        )

    async def abort_session(self, key: str) -> dict[str, Any]:
        return cast(dict[str, Any], await self._call("sessions.abort", {"key": key}))

    async def patch_session(self, key: str, **fields: Any) -> dict[str, Any]:
        params: dict[str, Any] = {"key": key, **fields}
        return cast(dict[str, Any], await self._call("sessions.patch", params))

    async def list_models(
        self, provider: str | None = None, capabilities: list[str] | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if provider:
            params["provider"] = provider
        if capabilities:
            params["capabilities"] = capabilities
        result = await self._call("models.list", params)
        if isinstance(result, list):
            return cast(list[dict[str, Any]], result)
        return cast(list[dict[str, Any]], list(result.get("models", [])))

    async def usage_status(self) -> dict[str, Any]:
        return cast(dict[str, Any], await self._call("usage.status", {}))

    async def usage_cost(self) -> dict[str, Any]:
        return cast(dict[str, Any], await self._call("usage.cost", {}))

    async def diagnostics_status(self) -> dict[str, Any]:
        return cast(dict[str, Any], await self._call("diagnostics.status", {}))

    async def diagnostics_set(self, *, enabled: bool, raw: bool = False) -> dict[str, Any]:
        params: dict[str, Any] = {"enabled": enabled}
        if enabled:
            params["raw"] = raw
        return cast(dict[str, Any], await self._call("diagnostics.set", params))

    async def get_config(self, path: str | None = None) -> Any:
        params = {"path": path} if path else None
        return await self._call("config.get", params)

    async def patch_config_safe(self, patches: dict[str, Any]) -> dict[str, Any]:
        result = await self._call("config.patch.safe", {"patches": patches})
        return result if isinstance(result, dict) else {}

    async def forget_approvals(self, target: str | None = None) -> dict[str, Any]:
        """Wipe cached intent approvals on the server.

        ``target`` selects a specific path/command; omit to clear all.
        Returns the scope reported by the server.
        """
        params: dict[str, Any] = {}
        if target:
            params["target"] = target
        return cast(dict[str, Any], await self._call("exec.approval.forget", params))

    async def approvals_snapshot(self) -> dict[str, Any]:
        """Return current approval mode + cache contents (diagnostic)."""
        return cast(dict[str, Any], await self._call("exec.approval.snapshot", {}))

    async def set_approval_mode(self, mode: str) -> dict[str, Any]:
        """Set the global approval queue mode (prompt / auto-approve / auto-deny)."""
        return cast(dict[str, Any], await self._call("exec.approvals.set", {"mode": mode}))

    async def resolve_approval(
        self,
        approval_id: str,
        approved: bool,
        *,
        allow_always: bool = False,
        choice: str | None = None,
    ) -> dict[str, Any]:
        """Approve or deny a pending approval by id.

        ``allow_always`` populates the session-lifetime intent cache so the
        same destructive intent doesn't prompt again.
        """
        params: dict[str, Any] = {
            "id": approval_id,
            "approved": approved,
            "allowAlways": allow_always,
        }
        if choice:
            params["choice"] = choice
        return cast(
            dict[str, Any],
            await self._call(
                "exec.approval.resolve",
                params,
            ),
        )

    async def send_message(
        self,
        session_key: str,
        message: str,
        attachments: list[dict] | None = None,
        elevated: str | None = None,
    ) -> AsyncIterator[dict]:
        """Send message and yield session events until done.

        ``elevated`` is a legacy surface kept for older clients. ``off``
        clears the override, ``on``/``bypass`` map to Trusted-Sandbox, and
        ``full`` maps to Full Host Access.
        """
        # Subscribe to message events for this session
        await self._call("sessions.messages.subscribe", {"key": session_key})

        params: dict[str, Any] = {
            "key": session_key,
            "message": message,
            "attachments": attachments or [],
            "_source": {
                "caller_kind": "cli",
                "channel_kind": "cli",
                "channel_id": "cli:chat",
                "source_kind": "cli",
                "source_name": "chat",
            },
        }
        if elevated in ("on", "bypass", "full"):
            params["_source"]["elevated"] = elevated

        # Send the message (accepted immediately; agent runs async)
        await self._call("sessions.send", params)

        active_task_groups: set[str] = set()

        # Yield events until session completion, extending the stream while a
        # background subagent group is still waiting for parent synthesis.
        while True:
            frame = await self._recv_queue.get()
            event_name: str = frame.get("event", "")
            payload: dict = frame.get("payload") or {}
            if event_name == "session.event.error":
                payload = _normalize_session_error_payload(payload)
            if task_terminal := _task_terminal_as_session_event(event_name, payload):
                yield task_terminal
                if active_task_groups:
                    continue
                break
            group_id = payload.get("group_id")
            if event_name in (
                "session.event.task_group.waiting",
                "session.event.task_group.synthesizing",
            ) and isinstance(group_id, str) and group_id:
                active_task_groups.add(group_id)
            elif event_name in (
                "session.event.task_group.done",
                "session.event.task_group.failed",
            ) and isinstance(group_id, str) and group_id:
                was_active_group = group_id in active_task_groups
                active_task_groups.discard(group_id)
            else:
                was_active_group = False
            yield {"event": event_name, **payload}
            if event_name in (
                "session.event.task_group.done",
                "session.event.task_group.failed",
            ) and was_active_group and not active_task_groups:
                break
            if event_name in ("session.event.done", "session.event.error"):
                if active_task_groups:
                    continue
                break

    async def close(self) -> None:
        """Close the WebSocket connection."""
        self._closing = True
        for task in (self._heartbeat_task, self._listener_task):
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
        self._ws = None
        self._heartbeat_task = None
        self._listener_task = None

    def _mark_connection_failed(self, exc: BaseException) -> ConnectionError:
        if isinstance(exc, ConnectionError) and str(exc).startswith("Gateway connection lost"):
            err = exc
        else:
            err = ConnectionError(
                "Gateway connection lost; restart chat or reconnect before sending "
                "another command. "
                f"Original error: {exc}"
            )
        if self._connection_error is None:
            self._connection_error = err
        else:
            err = self._connection_error
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(err)
        self._pending.clear()
        current_task = asyncio.current_task()
        for task in (self._heartbeat_task, self._listener_task):
            if task is not None and task is not current_task and not task.done():
                task.cancel()
        return err


def _task_terminal_as_session_event(event_name: str, payload: dict) -> dict[str, Any] | None:
    """Map task-runtime terminal events to chat stream terminal events.

    Gateway chat normally terminates with ``session.event.done`` or
    ``session.event.error``. If the task runtime fails before the agent stream
    starts, older servers may only emit a task terminal event; without this
    fallback the CLI waits forever.
    """
    if event_name == "task.cancelled":
        return {"event": "session.event.done", "reason": "aborted"}

    if event_name not in {"task.failed", "task.timeout", "task.abandoned"}:
        return None

    reason = payload.get("terminal_reason")
    status = event_name.removeprefix("task.")
    message = build_terminal_reply(
        {
            "status": status,
            "terminal_reason": reason,
            **payload,
        }
    )
    return {
        "event": "session.event.error",
        "message": message,
        "code": status,
        **payload,
    }


def _normalize_session_error_payload(payload: dict) -> dict[str, Any]:
    message = payload.get("message")
    error_message = payload.get("error_message")
    raw_message = error_message if isinstance(error_message, str) and error_message else message
    code = payload.get("code")
    code_text = str(code or "").lower()
    raw_text = raw_message if isinstance(raw_message, str) and raw_message else "Agent error"
    is_timeout = "timeout" in code_text or "stream idle" in raw_text.lower()
    terminal_payload = {
        "status": "timeout" if is_timeout else "failed",
        "terminal_reason": payload.get("terminal_reason")
        or ("timeout" if is_timeout else "error"),
        "error_class": code,
        "error_message": raw_text,
        **payload,
    }
    _, safe_error_message = sanitize_agent_error(
        terminal_payload,
        fallback_error_class=str(code) if code else None,
        fallback_error_message=raw_text,
    )
    terminal_message = build_terminal_reply(terminal_payload)
    return {
        **payload,
        "message": terminal_message,
        "terminal_message": terminal_message,
        "terminal_reason": terminal_payload["terminal_reason"],
        "error_message": safe_error_message,
    }


def _heartbeat_interval_from_policy(policy: dict[str, Any]) -> float:
    raw = policy.get("client_ws_keepalive_timeout_ms", 120_000)
    try:
        keepalive_ms = int(raw)
    except (TypeError, ValueError):
        keepalive_ms = 120_000
    keepalive_s = max(0, keepalive_ms) / 1000.0
    if keepalive_s <= 0.0:
        keepalive_s = 120.0
    minimum = 15.0 if keepalive_s > 15.0 else 0.05
    return max(minimum, keepalive_s * 0.4)
