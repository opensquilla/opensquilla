"""Thin gateway RPC bridge for the configured external RAG Provider."""

from __future__ import annotations

from typing import Any

from opensquilla.gateway.rpc import RpcContext, RpcHandlerError, get_dispatcher
from opensquilla.rag_provider.protocol import (
    ProviderAuthenticationError,
    ProviderBudgetViolation,
    ProviderNotFound,
    ProviderProtocolViolation,
)

_d = get_dispatcher()


def _runtime(ctx: RpcContext) -> Any:
    runtime = ctx.rag_provider_runtime
    if runtime is None:
        raise RpcHandlerError(
            "KNOWLEDGE_PROVIDER_UNAVAILABLE",
            "knowledge provider is not enabled",
            retryable=True,
        )
    return runtime


def _require_only(params: dict[str, Any], allowed: set[str]) -> None:
    unexpected = sorted(set(params) - allowed)
    if unexpected:
        raise ValueError(f"unexpected params: {', '.join(unexpected)}")


def _map_provider_error(error: Exception) -> RpcHandlerError:
    if isinstance(error, ProviderAuthenticationError):
        return RpcHandlerError(
            "KNOWLEDGE_PROVIDER_AUTHENTICATION_ERROR",
            "knowledge provider authentication failed",
        )
    if isinstance(error, ProviderNotFound):
        return RpcHandlerError("KNOWLEDGE_NOT_FOUND", "knowledge evidence was not found")
    if isinstance(error, ProviderBudgetViolation):
        return RpcHandlerError(
            "KNOWLEDGE_PROVIDER_BUDGET_VIOLATION",
            "knowledge provider response exceeded the allowed budget",
        )
    if isinstance(error, ProviderProtocolViolation):
        return RpcHandlerError(
            "KNOWLEDGE_PROVIDER_PROTOCOL_VIOLATION",
            "knowledge provider returned an invalid response",
        )
    return RpcHandlerError(
        "KNOWLEDGE_PROVIDER_UNAVAILABLE",
        "knowledge provider is temporarily unavailable",
        retryable=True,
    )


@_d.method("knowledge.status", scope="operator.read")
async def _handle_knowledge_status(
    params: dict | None,
    ctx: RpcContext,
) -> dict[str, Any]:
    if params is not None and not isinstance(params, dict):
        raise ValueError("params must be an object")
    if isinstance(params, dict):
        _require_only(params, set())
    settings = ctx.config.knowledge
    runtime = ctx.rag_provider_runtime
    capabilities = None
    if runtime is not None:
        snapshot = runtime.snapshot()
        capabilities = snapshot.capabilities
        result = snapshot.to_wire()
    else:
        result = {
            "connectionState": "DISABLED",
            "provider": None,
            "protocolVersion": None,
            "capabilities": None,
            "effectiveLimits": None,
            "searchOptions": None,
            "links": {},
            "lastSuccessAt": None,
            "lastErrorCode": None,
            "consecutiveFailures": 0,
            "warning": None,
        }
    effective_profile = None
    if capabilities is not None:
        advertised_profiles = {
            profile_id for profile_id, _label in capabilities.retrieval_profiles
        }
        configured_profile = settings.retrieval_profile_override
        effective_profile = (
            configured_profile
            if configured_profile in advertised_profiles
            else capabilities.default_retrieval_profile
        )
    return {
        **result,
        "enabled": bool(settings.enabled),
        "retrievalProfileOverride": settings.retrieval_profile_override,
        "effectiveRetrievalProfile": effective_profile,
        "collectionScope": list(settings.collection_scope),
        "legacyConfigPresent": bool(settings.legacy_config_present),
        "legacyAdapterEnabled": bool(settings.legacy_knowledge_adapter),
    }


@_d.method("knowledge.search", scope="operator.read")
async def _handle_knowledge_search(
    params: dict | None,
    ctx: RpcContext,
) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    _require_only(params, {"query", "limit"})
    query = params.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("params.query is required")
    limit = params.get("limit", 8)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise ValueError("params.limit must be an integer between 1 and 20")
    try:
        validated = await _runtime(ctx).search(query=query.strip(), limit=limit)
    except Exception as error:
        raise _map_provider_error(error) from error
    payload = dict(validated.payload)
    payload["providerBudgetViolation"] = validated.provider_budget_violation
    return payload


async def _persist_profile_override(
    profile: str | None,
    ctx: RpcContext,
) -> dict[str, Any]:
    from opensquilla.gateway.rpc_config import _handle_config_patch

    return await _handle_config_patch(
        {
            "patches": {
                "knowledge.retrieval_profile_override": profile,
            }
        },
        ctx,
    )


@_d.method("knowledge.profile.set", scope="operator.write")
async def _handle_knowledge_profile_set(
    params: dict | None,
    ctx: RpcContext,
) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    _require_only(params, {"retrievalProfileOverride"})
    if "retrievalProfileOverride" not in params:
        raise ValueError("params.retrievalProfileOverride is required")

    raw_profile = params["retrievalProfileOverride"]
    if raw_profile is None:
        profile = None
    elif isinstance(raw_profile, str) and raw_profile.strip():
        profile = raw_profile.strip()
    else:
        raise ValueError(
            "params.retrievalProfileOverride must be a non-empty string or null"
        )

    runtime = _runtime(ctx)
    snapshot = runtime.snapshot()
    capabilities = snapshot.capabilities

    if profile is not None:
        if snapshot.state.value not in {"READY", "LEGACY"} or capabilities is None:
            raise RpcHandlerError(
                "KNOWLEDGE_PROVIDER_UNAVAILABLE",
                "knowledge provider capabilities are not currently available",
                retryable=True,
            )
        available = {item[0] for item in capabilities.retrieval_profiles}
        if profile not in available:
            raise RpcHandlerError(
                "KNOWLEDGE_RETRIEVAL_PROFILE_UNAVAILABLE",
                "the selected retrieval profile is not advertised by the provider",
            )

    await _persist_profile_override(profile, ctx)
    runtime.apply_retrieval_profile_override(profile)

    provider_default = (
        capabilities.default_retrieval_profile if capabilities is not None else None
    )
    return {
        "retrievalProfileOverride": profile,
        "providerDefaultRetrievalProfile": provider_default,
        "effectiveRetrievalProfile": profile or provider_default,
        "restartRequired": False,
    }


@_d.method("knowledge.get", scope="operator.read")
async def _handle_knowledge_get(
    params: dict | None,
    ctx: RpcContext,
) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    _require_only(params, {"evidenceId", "cursor"})
    evidence_id = params.get("evidenceId")
    if not isinstance(evidence_id, str) or not evidence_id.strip():
        raise ValueError("params.evidenceId is required")
    cursor = params.get("cursor")
    if cursor is not None and (not isinstance(cursor, str) or not cursor.strip()):
        raise ValueError("params.cursor must be a non-empty string")
    try:
        return await _runtime(ctx).get(
            evidence_id=evidence_id.strip(),
            cursor=cursor.strip() if isinstance(cursor, str) else None,
        )
    except Exception as error:
        raise _map_provider_error(error) from error
