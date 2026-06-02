from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.env import trust_env
from opensquilla.gateway import rpc_tools
from opensquilla.gateway.auth import Principal
from opensquilla.gateway.rpc import RpcContext
from opensquilla.sandbox import integration as integration_mod
from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.integration import configure_runtime, reset_runtime, sandboxed
from opensquilla.sandbox.network_guard import NetworkDecision
from opensquilla.sandbox.run_context import DomainGrant, RunContext
from opensquilla.sandbox.run_mode import RunMode
from opensquilla.tools.builtin import web as web_mod
from opensquilla.tools.builtin import web_fetch as web_fetch_mod
from opensquilla.tools.types import CallerKind, ToolContext, current_tool_context


@pytest.fixture(autouse=True)
def sandbox_runtime(tmp_path: Path) -> Iterator[None]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    configure_runtime(
        SandboxSettings(
            run_mode="standard",
            backend="noop",
            allow_legacy_mode=True,
            network_default="proxy_allowlist",
        ),
        workspace=workspace,
    )
    try:
        yield
    finally:
        reset_runtime()


@pytest.fixture
def managed_context(tmp_path: Path) -> Iterator[ToolContext]:
    ctx = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.CLI,
        workspace_dir=str(tmp_path),
        session_key="s1",
        run_mode="standard",
        sandbox_run_context=RunContext(
            run_mode=RunMode.STANDARD,
            domains=(DomainGrant(domain="allowed.test"),),
        ),
    )
    token = current_tool_context.set(ctx)
    try:
        yield ctx
    finally:
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_url_shaped_inprocess_network_action_sets_context_proxy_without_env_mutation(
    monkeypatch: pytest.MonkeyPatch,
    managed_context: ToolContext,
) -> None:
    events: list[str] = []
    seen: dict[str, object] = {}

    class FakeProxy:
        host = "127.0.0.1"
        port = 28080

        def __init__(self, decide: object) -> None:
            self._decide = decide
            events.append("proxy.init")

        async def start(self) -> None:
            events.append("proxy.start")
            decision = self._decide("allowed.test")
            assert isinstance(decision, NetworkDecision)
            seen["decision"] = decision.status

        async def stop(self) -> None:
            events.append("proxy.stop")

    monkeypatch.setattr(integration_mod, "SandboxProxyServer", FakeProxy)
    monkeypatch.setenv("HTTP_PROXY", "http://user.invalid:1")
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.setenv("http_proxy", "http://user-lower.invalid:1")
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.setenv("ALL_PROXY", "http://all.invalid:1")
    monkeypatch.delenv("all_proxy", raising=False)
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setenv("OPENSQUILLA_TRUST_ENV", "0")

    @sandboxed(
        "network.http",
        argv_factory=lambda a: ("http_request", "GET", str(a["url"])),
        record_payload=False,
    )
    async def dummy_http_request(url: str) -> str:
        seen["url"] = url
        seen["proxy_url"] = integration_mod.current_managed_network_proxy_url()
        seen["httpx_kwargs"] = integration_mod.managed_network_httpx_kwargs()
        seen["trust_env"] = trust_env()
        return "ok"

    result = await dummy_http_request("http://allowed.test/path")

    assert result == "ok"
    assert seen["decision"] == "allow"
    assert seen["proxy_url"] == "http://127.0.0.1:28080"
    assert seen["httpx_kwargs"] == {
        "proxy": "http://127.0.0.1:28080",
        "trust_env": False,
    }
    assert seen["trust_env"] is False
    assert events == ["proxy.init", "proxy.start", "proxy.stop"]
    assert os.environ["HTTP_PROXY"] == "http://user.invalid:1"
    assert "HTTPS_PROXY" not in os.environ
    assert os.environ["http_proxy"] == "http://user-lower.invalid:1"
    assert "https_proxy" not in os.environ
    assert os.environ["ALL_PROXY"] == "http://all.invalid:1"
    assert "all_proxy" not in os.environ
    assert os.environ["NO_PROXY"] == "*"
    assert "no_proxy" not in os.environ
    assert os.environ["OPENSQUILLA_TRUST_ENV"] == "0"
    assert integration_mod.current_managed_network_proxy_url() is None


@pytest.mark.asyncio
async def test_http_request_uses_explicit_context_proxy_kwargs(
    monkeypatch: pytest.MonkeyPatch,
    managed_context: ToolContext,
) -> None:
    seen: dict[str, object] = {}

    class FakeProxy:
        host = "127.0.0.1"
        port = 28080

        def __init__(self, decide: object) -> None:
            self._decide = decide

        async def start(self) -> None:
            decision = self._decide("allowed.test")
            assert isinstance(decision, NetworkDecision)
            assert decision.status == "allow"

        async def stop(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, **kwargs: object) -> None:
            seen["client_kwargs"] = kwargs

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def request(self, **kwargs: object) -> object:
            seen["request_kwargs"] = kwargs
            return SimpleNamespace(
                status_code=200,
                url=kwargs["url"],
                headers={"content-type": "text/plain"},
                content=b"ok",
                text="ok",
            )

    monkeypatch.setattr(integration_mod, "SandboxProxyServer", FakeProxy)
    monkeypatch.setattr(web_mod.httpx, "AsyncClient", FakeAsyncClient)

    payload = json.loads(await web_mod.http_request("http://allowed.test/path"))

    assert payload["status"] == 200
    assert seen["client_kwargs"] == {
        "timeout": 30.0,
        "proxy": "http://127.0.0.1:28080",
        "trust_env": False,
    }


@pytest.mark.asyncio
async def test_web_fetch_cache_hit_requires_current_run_context_grant(
    monkeypatch: pytest.MonkeyPatch,
    managed_context: ToolContext,
) -> None:
    url = "http://blocked.test/page"
    web_fetch_mod._cache.clear()
    web_fetch_mod._cache[(url, "markdown")] = {
        "url": url,
        "final_url": url,
        "status": 200,
        "content_type": "text/html",
        "title": "",
        "extract_mode": "markdown",
        "extractor": "cache",
        "truncated": False,
        "length": 13,
        "text": "cached secret",
    }
    monkeypatch.setattr(web_fetch_mod, "_check_ssrf", lambda value: None)
    monkeypatch.setattr(
        integration_mod,
        "SandboxProxyServer",
        lambda *args, **kwargs: pytest.fail("proxy should not start for denied target"),
    )

    result = await web_fetch_mod.web_fetch(url)

    payload = json.loads(result)
    assert payload["status"] == "denied"
    assert payload["reason"] == "policy_denied"
    assert "blocked.test" in payload["message"]
    assert "cached secret" not in result


@pytest.mark.asyncio
async def test_rpc_search_query_fails_closed_under_managed_network(
    monkeypatch: pytest.MonkeyPatch,
    managed_context: ToolContext,
) -> None:
    async def fail_search(*args: object, **kwargs: object) -> dict[str, object]:
        raise AssertionError("search provider should not run")

    monkeypatch.setattr(rpc_tools, "run_web_search_payload", fail_search)
    ctx = RpcContext(
        conn_id="c",
        principal=Principal(
            role="operator",
            scopes=frozenset(["operator.write", "operator.read"]),
            is_owner=True,
            authenticated=True,
        ),
    )

    result = await rpc_tools._handle_search_query({"query": "python packages"}, ctx)

    assert result["ok"] is False
    assert result["results"] == []
    assert result["error"]["kind"] == "policy_denied"
    assert "explicit URL" in result["error"]["message"]


@pytest.mark.asyncio
async def test_rpc_search_query_without_runtime_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_runtime()

    async def fail_search(*args: object, **kwargs: object) -> dict[str, object]:
        raise AssertionError("search provider should not run without sandbox runtime")

    monkeypatch.setattr(rpc_tools, "run_web_search_payload", fail_search)
    ctx = RpcContext(
        conn_id="c",
        principal=Principal(
            role="operator",
            scopes=frozenset(["operator.write", "operator.read"]),
            is_owner=True,
            authenticated=True,
        ),
    )

    result = await rpc_tools._handle_search_query({"query": "python packages"}, ctx)

    assert result["ok"] is False
    assert result["results"] == []
    assert result["error"]["kind"] == "runtime_unconfigured"


@pytest.mark.asyncio
async def test_inprocess_network_action_without_run_context_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.CLI,
        workspace_dir=str(tmp_path),
        session_key="s1",
        run_mode="standard",
    )
    token = current_tool_context.set(ctx)
    monkeypatch.setattr(
        integration_mod,
        "SandboxProxyServer",
        lambda *args, **kwargs: pytest.fail("proxy should not start without context"),
    )
    called = False

    @sandboxed(
        "network.http",
        argv_factory=lambda a: ("http_request", "GET", str(a["url"])),
        record_payload=False,
    )
    async def dummy_http_request(url: str) -> str:
        nonlocal called
        called = True
        return url

    try:
        result = await dummy_http_request("http://allowed.test/path")
    finally:
        current_tool_context.reset(token)

    payload = json.loads(result)
    assert payload["status"] == "denied"
    assert payload["reason"] == "policy_denied"
    assert "Run Context" in payload["message"]
    assert called is False


@pytest.mark.asyncio
async def test_web_search_shaped_inprocess_action_fails_closed_without_url(
    monkeypatch: pytest.MonkeyPatch,
    managed_context: ToolContext,
) -> None:
    monkeypatch.setattr(
        integration_mod,
        "SandboxProxyServer",
        lambda *args, **kwargs: pytest.fail("proxy should not start without URL target"),
    )
    called = False

    @sandboxed(
        "web.fetch",
        argv_factory=lambda a: (
            "web_search",
            str(a.get("query", "")),
            str(a.get("max_results", "")),
        ),
        record_payload=False,
    )
    async def dummy_web_search(query: str, max_results: int | None = None) -> str:
        nonlocal called
        called = True
        return query

    result = await dummy_web_search("python packages", 5)

    payload = json.loads(result)
    assert payload["status"] == "denied"
    assert payload["reason"] == "policy_denied"
    assert "explicit URL" in payload["message"]
    assert called is False
