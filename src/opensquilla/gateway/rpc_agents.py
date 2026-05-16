"""RPC handlers for the agents domain."""

from __future__ import annotations

import re
from typing import cast

from opensquilla.agents.workspace_files import (
    list_workspace_agent_files,
    read_workspace_agent_file,
    validate_workspace_file_extension,
    validate_workspace_file_name,
    workspace_file_root_for_config,
    write_workspace_agent_file,
)
from opensquilla.gateway.rpc import (
    RpcContext,
    RpcHandlerError,
    RpcUnavailableError,
    get_dispatcher,
)
from opensquilla.session.keys import normalize_agent_id

_d = get_dispatcher()


def _slugify(name: str) -> str:
    """Generate a slug-based ID from a name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "agent"


def _get_agent_registry(ctx: RpcContext):
    agent_registry = getattr(ctx, "agent_registry", None)
    if agent_registry is None:
        raise RpcUnavailableError("Agent registry not available")
    return agent_registry


def _get_identity_service(ctx: RpcContext):
    identity_service = getattr(ctx, "identity_service", None)
    if identity_service is None:
        raise RpcUnavailableError("Agent identity service not available")
    return identity_service


@_d.method("agents.list", scope="operator.read")
async def _handle_agents_list(params: dict | None, ctx: RpcContext) -> dict:
    include_builtin = (params or {}).get("includeBuiltin", True)

    agent_registry = getattr(ctx, "agent_registry", None)
    if agent_registry is not None:
        agents = await agent_registry.list_agents(include_builtin=include_builtin)
        return {"agents": agents}

    return {"agents": []}


_UPDATE_FIELD_MAP: tuple[tuple[str, ...], ...] = (
    ("name",),
    ("description",),
    ("model",),
    ("systemPrompt", "system_prompt"),
    ("tools",),
    ("workspace",),
    ("agentDir", "agent_dir"),
    ("enabled",),
)


@_d.method("agents.create", scope="operator.admin")
async def _handle_agents_create(params: dict | None, ctx: RpcContext) -> dict:
    if not isinstance(params, dict):
        raise ValueError("params.id or params.name is required")

    name = params.get("name")
    raw_agent_id = params.get("id") or params.get("agentId") or (_slugify(name) if name else None)
    if not raw_agent_id:
        raise ValueError("params.id or params.name is required")
    agent_id = normalize_agent_id(raw_agent_id)

    agent_registry = _get_agent_registry(ctx)
    try:
        result = await agent_registry.create_agent(
            agent_id=agent_id,
            name=name or agent_id,
            description=params.get("description"),
            model=params.get("model"),
            workspace=params.get("workspace"),
            agent_dir=params.get("agentDir") or params.get("agent_dir"),
            enabled=params.get("enabled", True),
            system_prompt=params.get("systemPrompt"),
            tools=params.get("tools"),
        )
    except ValueError as exc:
        msg = str(exc)
        if "already exists" in msg:
            raise RpcHandlerError(
                "agent.exists", msg, details={"agentId": agent_id}
            ) from exc
        if agent_id == "main" or "builtin" in msg.lower():
            raise RpcHandlerError(
                "agent.builtin_immutable", msg, details={"agentId": agent_id}
            ) from exc
        raise
    return cast(dict, result)


@_d.method("agents.update", scope="operator.admin")
async def _handle_agents_update(params: dict | None, ctx: RpcContext) -> dict:
    if not isinstance(params, dict) or "id" not in params:
        raise ValueError("params.id is required")

    agent_id = normalize_agent_id(params["id"])
    updated_fields: list[str] = []
    for aliases in _UPDATE_FIELD_MAP:
        if any(alias in params for alias in aliases):
            updated_fields.append(aliases[0])

    if not updated_fields:
        raise ValueError("No fields to update")

    agent_registry = _get_agent_registry(ctx)
    try:
        result = await agent_registry.update_agent(agent_id, **{**params, "id": agent_id})
    except ValueError as exc:
        msg = str(exc)
        if "builtin" in msg.lower() or agent_id == "main":
            raise RpcHandlerError(
                "agent.builtin_immutable", msg, details={"agentId": agent_id}
            ) from exc
        raise
    except KeyError as exc:
        raise RpcHandlerError(
            "agent.not_found",
            f"Agent '{agent_id}' does not exist",
            details={"agentId": agent_id},
        ) from exc
    return cast(dict, result)


@_d.method("agents.delete", scope="operator.admin")
async def _handle_agents_delete(params: dict | None, ctx: RpcContext) -> None:
    if not isinstance(params, dict) or "id" not in params:
        raise ValueError("params.id is required")

    agent_id = normalize_agent_id(params["id"])

    # Refuse to delete builtin agents
    if agent_id == "main":
        raise RpcHandlerError(
            "agent.builtin_immutable",
            "Cannot delete builtin agent: main",
            details={"agentId": agent_id},
        )

    agent_registry = _get_agent_registry(ctx)
    try:
        await agent_registry.delete_agent(agent_id)
    except KeyError as exc:
        raise RpcHandlerError(
            "agent.not_found",
            f"Agent '{agent_id}' does not exist",
            details={"agentId": agent_id},
        ) from exc
    return None


@_d.method("agents.files.list", scope="operator.read")
async def _handle_agents_files_list(params: dict | None, ctx: RpcContext) -> dict:
    if not isinstance(params, dict) or "agentId" not in params:
        raise ValueError("params.agentId is required")

    agent_id = normalize_agent_id(params["agentId"])

    agent_registry = getattr(ctx, "agent_registry", None)
    if agent_registry is None:
        root = workspace_file_root_for_config(getattr(ctx, "config", None), agent_id)
        if root is None:
            raise RpcUnavailableError("Agent registry not available")
        return {"files": list_workspace_agent_files(root)}
    files = await agent_registry.list_agent_files(agent_id)
    return {"files": files}


@_d.method("agents.files.get", scope="operator.read")
async def _handle_agents_files_get(params: dict | None, ctx: RpcContext) -> dict:
    if not isinstance(params, dict):
        raise ValueError("params required: agentId, name")
    if "agentId" not in params:
        raise ValueError("params.agentId is required")
    if "name" not in params:
        raise ValueError("params.name is required")

    agent_id = normalize_agent_id(params["agentId"])
    name = validate_workspace_file_name(params["name"])

    agent_registry = getattr(ctx, "agent_registry", None)
    if agent_registry is None:
        root = workspace_file_root_for_config(getattr(ctx, "config", None), agent_id)
        if root is None:
            raise RpcUnavailableError("Agent registry not available")
        safe_name, content = read_workspace_agent_file(root, name)
        return {"name": safe_name, "content": content}
    content = await agent_registry.get_agent_file(agent_id, name)
    return cast(dict, content)


@_d.method("agents.files.set", scope="operator.admin")
async def _handle_agents_files_set(params: dict | None, ctx: RpcContext) -> dict:
    if not isinstance(params, dict):
        raise ValueError("params required: agentId, name, content")
    if "agentId" not in params:
        raise ValueError("params.agentId is required")
    if "name" not in params:
        raise ValueError("params.name is required")
    if "content" not in params:
        raise ValueError("params.content is required")

    name = validate_workspace_file_name(params["name"])
    validate_workspace_file_extension(name)

    content = params["content"]

    agent_registry = getattr(ctx, "agent_registry", None)
    if agent_registry is None:
        agent_id = normalize_agent_id(params["agentId"])
        root = workspace_file_root_for_config(getattr(ctx, "config", None), agent_id)
        if root is None:
            raise RpcUnavailableError("Agent registry not available")
        return write_workspace_agent_file(root, name, content)
    result = await agent_registry.set_agent_file(
        normalize_agent_id(params["agentId"]),
        name,
        content,
    )
    return cast(dict, result)


@_d.method("agent.identity.get", scope="operator.read")
async def _handle_agent_identity_get(params: dict | None, ctx: RpcContext) -> dict:
    agent_id = normalize_agent_id((params or {}).get("agentId", "main"))

    identity_service = _get_identity_service(ctx)
    identity = await identity_service.get_identity(agent_id)
    return cast(dict, identity)
