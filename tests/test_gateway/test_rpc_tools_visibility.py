from __future__ import annotations

from typing import Any

import pytest

from opensquilla.gateway.auth import Principal
from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.gateway.scopes import READ_SCOPE
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import ToolSpec


async def _handler() -> str:
    return "ok"


def _ctx(*, tool_registry: Any, is_owner: bool) -> RpcContext:
    return RpcContext(
        conn_id="test",
        config=GatewayConfig(),
        principal=Principal(
            role="operator",
            scopes=frozenset({READ_SCOPE}),
            is_owner=is_owner,
            authenticated=True,
        ),
        tool_registry=tool_registry,
        session_manager=object(),
        task_runtime=object(),
    )


def _tool_names(payload: dict[str, Any]) -> set[str]:
    return {tool["name"] for tool in payload["tools"]}


def _registry_with_owner_only_probe() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="ordinary_probe",
            description="ordinary probe",
            parameters={},
        ),
        _handler,
    )
    registry.register(
        ToolSpec(
            name="owner_probe",
            description="owner probe",
            parameters={},
            owner_only=True,
        ),
        _handler,
    )
    return registry


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["tools.catalog", "tools.effective"])
async def test_tools_rpc_visibility_respects_principal_ownership(method: str) -> None:
    registry = _registry_with_owner_only_probe()

    non_owner = await get_dispatcher().dispatch(
        "r1",
        method,
        {"callerKind": "agent"},
        _ctx(tool_registry=registry, is_owner=False),
    )
    owner = await get_dispatcher().dispatch(
        "r2",
        method,
        {"callerKind": "agent"},
        _ctx(tool_registry=registry, is_owner=True),
    )

    assert non_owner.error is None, non_owner.error
    assert owner.error is None, owner.error
    assert _tool_names(non_owner.payload) == {"ordinary_probe"}
    assert _tool_names(owner.payload) == {"ordinary_probe", "owner_probe"}


@pytest.mark.asyncio
async def test_tools_catalog_without_runtime_params_respects_principal_ownership() -> None:
    registry = _registry_with_owner_only_probe()

    non_owner = await get_dispatcher().dispatch(
        "r1",
        "tools.catalog",
        {},
        _ctx(tool_registry=registry, is_owner=False),
    )

    assert non_owner.error is None, non_owner.error
    assert _tool_names(non_owner.payload) == {"ordinary_probe"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"callerKind": "subagent"},
        {"sessionKey": "subagent:test"},
    ],
)
@pytest.mark.parametrize("method", ["tools.catalog", "tools.effective"])
async def test_tools_rpc_subagent_visibility_respects_principal_ownership(
    method: str,
    params: dict[str, str],
) -> None:
    registry = _registry_with_owner_only_probe()

    non_owner = await get_dispatcher().dispatch(
        "r1",
        method,
        params,
        _ctx(tool_registry=registry, is_owner=False),
    )

    assert non_owner.error is None, non_owner.error
    assert _tool_names(non_owner.payload) == {"ordinary_probe"}


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["tools.catalog", "tools.effective"])
async def test_default_tools_rpc_hides_owner_only_tools_from_non_owner(method: str) -> None:
    import opensquilla.tools.builtin  # noqa: F401
    from opensquilla.gateway.config import LlmProviderConfig
    from opensquilla.provider.image_generation_config import ImageGenerationConfig
    from opensquilla.tools.builtin.media import configure_image_generation
    from opensquilla.tools.registry import get_default_registry

    configure_image_generation(
        ImageGenerationConfig(enabled=True),
        llm_config=LlmProviderConfig(provider="openrouter", api_key="sk-or-configured"),
    )
    try:
        non_owner = await get_dispatcher().dispatch(
            "r1",
            method,
            {"callerKind": "agent"},
            _ctx(tool_registry=get_default_registry(), is_owner=False),
        )
        owner = await get_dispatcher().dispatch(
            "r2",
            method,
            {"callerKind": "agent"},
            _ctx(tool_registry=get_default_registry(), is_owner=True),
        )
    finally:
        configure_image_generation(ImageGenerationConfig())

    assert non_owner.error is None, non_owner.error
    assert owner.error is None, owner.error

    non_owner_names = _tool_names(non_owner.payload)
    owner_names = _tool_names(owner.payload)

    assert "http_request" not in non_owner_names
    assert "git_commit" not in non_owner_names
    assert {"http_request", "git_commit"} <= owner_names
    assert {"image_generate", "sessions_spawn", "sessions_send"} <= owner_names
    assert "spawn_subagent" not in owner_names
    assert "send_message" not in owner_names
    assert "generate_image" not in owner_names
