from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from opensquilla.gateway.auth import Principal
from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.knowledge.backend import KnowledgeBackendError
from opensquilla.knowledge.runtime import KnowledgeRuntime


@pytest.mark.asyncio
async def test_knowledge_rpc_prepare_search_and_judgment(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "report.md").write_text(
        "# AI 玻璃材料\n\n康宁公司的 AI 基建玻璃材料需求正在提升。",
        encoding="utf-8",
    )
    ctx = RpcContext(
        conn_id="test",
        config=SimpleNamespace(state_dir=str(tmp_path / "state")),
    )

    dispatcher = get_dispatcher()
    prepare = await dispatcher.dispatch(
        "1",
        "knowledge.prepare_sample",
        {"sourceRoot": str(source_root), "limit": 5},
        ctx,
    )
    assert prepare.ok is True
    assert prepare.payload["documentsIndexed"] == 1

    search = await dispatcher.dispatch(
        "2",
        "knowledge.search",
        {"query": "康宁 AI 玻璃材料", "topK": 3},
        ctx,
    )
    assert search.ok is True
    assert search.payload["results"]
    assert search.payload["results"][0]["citation"]
    assert search.payload["results"][0]["collectionId"] == "default"

    collections = await dispatcher.dispatch("2b", "knowledge.collections", {}, ctx)
    assert collections.ok is True
    assert collections.payload["collections"][0]["collectionId"] == "default"

    questions = await dispatcher.dispatch("3", "knowledge.questions", {}, ctx)
    assert questions.ok is True
    assert questions.payload["questions"]

    judgment = await dispatcher.dispatch(
        "4",
        "knowledge.judgment",
        {
            "questionId": "q001",
            "question": "康宁公司的核心观点是什么？",
            "rating": "correct",
            "evidence": "supported",
            "hallucination": "none",
        },
        ctx,
    )
    assert judgment.ok is True
    path = tmp_path / "state" / "knowledge" / "data" / "eval" / "judgments.jsonl"
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[0])["rating"] == "correct"


@pytest.mark.asyncio
async def test_knowledge_rpc_search_merges_retrieval_and_embedding_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.gateway import rpc_knowledge as rpc_knowledge_module

    class RecordingKnowledgeBackend:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def search(
            self,
            query: str,
            *,
            top_k: int = 8,
            filters: dict[str, object] | None = None,
        ) -> dict[str, object]:
            self.calls.append(
                {
                    "query": query,
                    "top_k": top_k,
                    "filters": dict(filters or {}),
                }
            )
            return {"query": query, "results": [], "count": 0}

    backend = RecordingKnowledgeBackend()
    monkeypatch.setattr(
        rpc_knowledge_module,
        "manager_from_config",
        lambda _config: backend,
    )
    ctx = RpcContext(conn_id="test", config=SimpleNamespace())
    dispatcher = get_dispatcher()

    result = await dispatcher.dispatch(
        "search-profile",
        "knowledge.search",
        {
            "query": "苹果收入",
            "topK": 4,
            "filters": {
                "source": "goldman",
                "retrievalProfile": "sqlite_fts5_default",
                "embeddingDimensions": 768,
            },
            "collectionId": "datasets",
            "retrievalProfile": "hybrid_rrf_bge_m3_fts5",
            "embeddingModel": "baai/bge-m3",
            "embeddingDimensions": 1024,
        },
        ctx,
    )

    assert result.ok is True
    assert backend.calls == [
        {
            "query": "苹果收入",
            "top_k": 4,
            "filters": {
                "source": "goldman",
                "collectionId": "datasets",
                "retrievalProfile": "hybrid_rrf_bge_m3_fts5",
                "embeddingModel": "baai/bge-m3",
                "embeddingDimensions": 1024,
            },
        }
    ]


@pytest.mark.asyncio
async def test_knowledge_rpc_offloads_blocking_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.gateway import rpc_knowledge as rpc_knowledge_module

    class SlowKnowledgeBackend:
        def status(self) -> dict[str, object]:
            time.sleep(0.35)
            return {"ok": True}

    monkeypatch.setattr(
        rpc_knowledge_module,
        "manager_from_config",
        lambda _config: SlowKnowledgeBackend(),
    )
    ctx = RpcContext(conn_id="test", config=SimpleNamespace())
    dispatcher = get_dispatcher()

    loop = asyncio.get_running_loop()
    started = loop.time()
    request = asyncio.create_task(dispatcher.dispatch("status-slow", "knowledge.status", {}, ctx))
    await asyncio.sleep(0.01)

    assert loop.time() - started < 0.2
    result = await request
    assert result.ok is True
    assert result.payload == {"ok": True}


@pytest.mark.asyncio
async def test_knowledge_settings_get_uses_runtime_backend() -> None:
    class Backend:
        def settings(self) -> dict[str, object]:
            return {"defaultRetrievalProfile": "lexical"}

    backend = Backend()
    runtime = SimpleNamespace(current_backend=lambda: backend)
    ctx = RpcContext(conn_id="test", config=SimpleNamespace(), knowledge_runtime=runtime)

    result = await get_dispatcher().dispatch(
        "settings-get",
        "knowledge.settings.get",
        {},
        ctx,
    )

    assert result.ok is True
    assert result.payload == {"defaultRetrievalProfile": "lexical"}


@pytest.mark.asyncio
async def test_knowledge_status_uses_runtime_status_payload() -> None:
    runtime_payload = {
        "connectionState": "DEGRADED",
        "capabilitiesStale": True,
        "capabilitiesFetchedAt": 123,
    }
    runtime = SimpleNamespace(status_payload=lambda: runtime_payload)
    ctx = RpcContext(conn_id="test", config=SimpleNamespace(), knowledge_runtime=runtime)

    result = await get_dispatcher().dispatch(
        "status-runtime",
        "knowledge.status",
        {},
        ctx,
    )

    assert result.ok is True
    assert result.payload == runtime_payload


@pytest.mark.asyncio
async def test_knowledge_settings_patch_sends_only_profile_then_refreshes() -> None:
    class Backend:
        def __init__(self) -> None:
            self.payloads: list[dict[str, object]] = []

        def update_settings(self, payload: dict[str, object]) -> dict[str, object]:
            self.payloads.append(payload)
            return {"ok": True, "persisted": True}

    class Snapshot:
        def to_status_wire(self) -> dict[str, object]:
            return {
                "connectionState": "READY",
                "configuredDefaultRetrievalProfile": "hybrid",
            }

    class Runtime:
        def __init__(self, backend: Backend) -> None:
            self.backend = backend
            self.invalidations: list[str] = []
            self.refreshes: list[dict[str, bool]] = []

        def current_backend(self) -> Backend:
            return self.backend

        def invalidate(self, reason: str) -> None:
            self.invalidations.append(reason)

        async def refresh(self, **kwargs: bool) -> Snapshot:
            self.refreshes.append(kwargs)
            return Snapshot()

    backend = Backend()
    runtime = Runtime(backend)
    ctx = RpcContext(conn_id="test", config=SimpleNamespace(), knowledge_runtime=runtime)

    result = await get_dispatcher().dispatch(
        "settings-patch",
        "knowledge.settings.patch",
        {
            "defaultRetrievalProfile": "hybrid",
            "ignored": "must-not-forward",
        },
        ctx,
    )

    assert result.ok is True
    assert backend.payloads == [{"defaultRetrievalProfile": "hybrid"}]
    assert runtime.invalidations == ["settings_updated"]
    assert runtime.refreshes == [
        {"force": True, "raise_on_error": True},
        {"force": False, "raise_on_error": True},
    ]
    assert result.payload == {
        "ok": True,
        "persisted": True,
        "connectionState": "READY",
        "configuredDefaultRetrievalProfile": "hybrid",
    }


@pytest.mark.asyncio
async def test_knowledge_settings_patch_failure_does_not_refresh() -> None:
    class Backend:
        def update_settings(self, payload: dict[str, object]) -> dict[str, object]:
            raise KnowledgeBackendError(
                status_code=500,
                code="settings_persist_failed",
                message="failed to persist retrieval settings",
            )

    class Runtime:
        def __init__(self) -> None:
            self.invalidations: list[str] = []
            self.refresh_count = 0

        def current_backend(self) -> Backend:
            return Backend()

        def invalidate(self, reason: str) -> None:
            self.invalidations.append(reason)

        async def refresh(self, **kwargs: bool) -> None:
            self.refresh_count += 1

    runtime = Runtime()
    ctx = RpcContext(conn_id="test", config=SimpleNamespace(), knowledge_runtime=runtime)

    result = await get_dispatcher().dispatch(
        "settings-patch-failed",
        "knowledge.settings.patch",
        {"defaultRetrievalProfile": "hybrid"},
        ctx,
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "settings_persist_failed"
    assert result.error.message == "failed to persist retrieval settings"
    assert result.error.retryable is True
    assert runtime.invalidations == []
    assert runtime.refresh_count == 0


@pytest.mark.asyncio
async def test_knowledge_settings_refresh_failure_degrades_confirmed_snapshot() -> None:
    class Backend:
        fail_status = False

        def update_settings(self, payload: dict[str, object]) -> dict[str, object]:
            return {"ok": True}

        def status(self) -> dict[str, object]:
            if self.fail_status:
                raise KnowledgeBackendError(
                    status_code=503,
                    code="untrusted_upstream_error",
                    message="raw upstream response body must stay secret",
                )
            return {
                "capabilitiesVersion": "aaaaaaaaaaaaaaaa",
                "configuredDefaultRetrievalProfile": "lexical",
                "effectiveDefaultRetrievalProfile": "lexical",
                "defaultFallbackReason": None,
                "retrievalProfiles": [
                    {
                        "id": "lexical",
                        "label": "Lexical",
                        "kind": "lexical",
                        "available": True,
                    }
                ],
            }

    backend = Backend()
    runtime = KnowledgeRuntime(
        lambda: backend,
        enabled_provider=lambda: True,
        ttl_seconds_provider=lambda: 60.0,
    )
    initial = await runtime.refresh(force=True, raise_on_error=True)
    assert initial is not None
    assert initial.to_status_wire()["connectionState"] == "READY"
    backend.fail_status = True
    ctx = RpcContext(conn_id="test", config=SimpleNamespace(), knowledge_runtime=runtime)

    result = await get_dispatcher().dispatch(
        "settings-refresh-failed",
        "knowledge.settings.patch",
        {"defaultRetrievalProfile": "hybrid"},
        ctx,
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "KNOWLEDGE_BACKEND_ERROR"
    assert result.error.message == "knowledge service request failed"
    assert result.error.retryable is True
    assert "raw upstream" not in result.error.message
    status = runtime.status_payload()
    assert status["connectionState"] == "DEGRADED"
    assert status["capabilitiesStale"] is True


@pytest.mark.asyncio
async def test_knowledge_ingest_success_invalidates_and_requests_refresh() -> None:
    class Backend:
        def ingest_collection(self, **kwargs: object) -> dict[str, object]:
            return {"ok": True, "documentsIndexed": 2}

    class Runtime:
        def __init__(self) -> None:
            self.invalidations: list[str] = []
            self.refresh_count = 0

        def current_backend(self) -> Backend:
            return Backend()

        def invalidate(self, reason: str) -> None:
            self.invalidations.append(reason)

        def request_refresh(self) -> None:
            self.refresh_count += 1

    runtime = Runtime()
    ctx = RpcContext(conn_id="test", config=SimpleNamespace(), knowledge_runtime=runtime)

    result = await get_dispatcher().dispatch(
        "ingest-refresh",
        "knowledge.ingest",
        {
            "sourceRoot": "/tmp/source",
            "collectionName": "reports",
            "collectionId": "reports-1",
            "indexProfiles": ["lexical"],
            "limit": 2,
        },
        ctx,
    )

    assert result.ok is True
    assert result.payload == {"ok": True, "documentsIndexed": 2}
    assert runtime.invalidations == ["ingest_completed"]
    assert runtime.refresh_count == 1


@pytest.mark.asyncio
async def test_knowledge_search_retries_capability_error_with_current_backend() -> None:
    holder: dict[str, object] = {}

    class FirstBackend:
        def __init__(self) -> None:
            self.search_count = 0

        def search(
            self,
            query: str,
            *,
            top_k: int,
            filters: dict[str, object] | None,
        ) -> dict[str, object]:
            self.search_count += 1
            holder["backend"] = second
            raise KnowledgeBackendError(
                status_code=409,
                code="retrieval_profile_unavailable",
                message="retrieval profile unavailable",
            )

    class SecondBackend:
        def __init__(self) -> None:
            self.status_count = 0
            self.search_count = 0

        def status(self) -> dict[str, object]:
            self.status_count += 1
            return {
                "capabilitiesVersion": "bbbbbbbbbbbbbbbb",
                "configuredDefaultRetrievalProfile": "lexical",
                "effectiveDefaultRetrievalProfile": "lexical",
                "defaultFallbackReason": None,
                "retrievalProfiles": [
                    {
                        "id": "lexical",
                        "label": "Lexical",
                        "kind": "lexical",
                        "available": True,
                    }
                ],
            }

        def search(
            self,
            query: str,
            *,
            top_k: int,
            filters: dict[str, object] | None,
        ) -> dict[str, object]:
            self.search_count += 1
            return {"query": query, "results": [{"id": "fresh"}], "count": 1}

    first = FirstBackend()
    second = SecondBackend()
    holder["backend"] = first
    runtime = KnowledgeRuntime(
        lambda: holder["backend"],
        enabled_provider=lambda: True,
        ttl_seconds_provider=lambda: 60.0,
    )
    ctx = RpcContext(conn_id="test", config=SimpleNamespace(), knowledge_runtime=runtime)

    result = await get_dispatcher().dispatch(
        "search-retry",
        "knowledge.search",
        {
            "query": "revenue",
            "retrievalProfile": "vector",
            "topK": 3,
        },
        ctx,
    )

    assert result.ok is True
    assert result.payload == {
        "query": "revenue",
        "results": [{"id": "fresh"}],
        "count": 1,
    }
    assert first.search_count == 1
    assert second.status_count == 1
    assert second.search_count == 1


@pytest.mark.asyncio
async def test_knowledge_search_does_not_retry_non_capability_error() -> None:
    class Backend:
        def __init__(self) -> None:
            self.search_count = 0
            self.status_count = 0

        def search(
            self,
            query: str,
            *,
            top_k: int,
            filters: dict[str, object] | None,
        ) -> dict[str, object]:
            self.search_count += 1
            raise KnowledgeBackendError(
                status_code=500,
                code="settings_persist_failed",
                message="failed to persist retrieval settings",
            )

        def status(self) -> dict[str, object]:
            self.status_count += 1
            raise AssertionError("non-capability errors must not refresh")

    backend = Backend()
    runtime = KnowledgeRuntime(
        lambda: backend,
        enabled_provider=lambda: True,
        ttl_seconds_provider=lambda: 60.0,
    )
    ctx = RpcContext(conn_id="test", config=SimpleNamespace(), knowledge_runtime=runtime)

    result = await get_dispatcher().dispatch(
        "search-no-retry",
        "knowledge.search",
        {"query": "revenue"},
        ctx,
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "settings_persist_failed"
    assert result.error.retryable is True
    assert backend.search_count == 1
    assert backend.status_count == 0


@pytest.mark.asyncio
async def test_knowledge_settings_permissions_are_read_and_admin() -> None:
    class Backend:
        def __init__(self) -> None:
            self.update_count = 0

        def settings(self) -> dict[str, object]:
            return {"defaultRetrievalProfile": "lexical"}

        def update_settings(self, payload: dict[str, object]) -> dict[str, object]:
            self.update_count += 1
            return {"ok": True}

    backend = Backend()
    runtime = SimpleNamespace(current_backend=lambda: backend)
    read_principal = Principal(
        role="operator",
        scopes=frozenset({"operator.read"}),
        is_owner=False,
        authenticated=True,
    )
    ctx = RpcContext(
        conn_id="read-only",
        principal=read_principal,
        config=SimpleNamespace(),
        knowledge_runtime=runtime,
    )
    dispatcher = get_dispatcher()

    get_result = await dispatcher.dispatch(
        "settings-read",
        "knowledge.settings.get",
        {},
        ctx,
    )
    patch_result = await dispatcher.dispatch(
        "settings-admin",
        "knowledge.settings.patch",
        {"defaultRetrievalProfile": "hybrid"},
        ctx,
    )

    assert get_result.ok is True
    assert patch_result.ok is False
    assert patch_result.error is not None
    assert patch_result.error.code == "UNAUTHORIZED"
    assert backend.update_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", [None, "", "   ", 42])
async def test_knowledge_settings_patch_rejects_invalid_profile(profile: object) -> None:
    ctx = RpcContext(conn_id="test", config=SimpleNamespace())

    result = await get_dispatcher().dispatch(
        "settings-invalid",
        "knowledge.settings.patch",
        {"defaultRetrievalProfile": profile},
        ctx,
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "INVALID_REQUEST"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("invalid_retrieval_profile", "invalid retrieval profile"),
        ("retrieval_profile_unavailable", "retrieval profile unavailable"),
        ("no_retrieval_profile_available", "no retrieval profile available"),
        ("settings_persist_failed", "failed to persist retrieval settings"),
    ],
)
async def test_knowledge_rpc_preserves_allowed_backend_error_codes(
    code: str,
    message: str,
) -> None:
    class Backend:
        def collections(self) -> dict[str, object]:
            raise KnowledgeBackendError(
                status_code=409,
                code=code,
                message=message,
            )

    runtime = SimpleNamespace(current_backend=lambda: Backend())
    ctx = RpcContext(conn_id="test", config=SimpleNamespace(), knowledge_runtime=runtime)

    result = await get_dispatcher().dispatch("allowed-error", "knowledge.collections", {}, ctx)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == code
    assert result.error.message == message
    assert result.error.retryable is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"patches": {"knowledge.endpoint": "http://127.0.0.1:18766"}},
        {"patch": {"knowledge": {"capability_ttl_seconds": 30.0}}},
    ],
)
async def test_config_patch_knowledge_path_invalidates_runtime(
    params: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.gateway import rpc_config as rpc_config_module
    from opensquilla.gateway.config import GatewayConfig

    class Runtime:
        def __init__(self) -> None:
            self.invalidations: list[str] = []
            self.refresh_count = 0

        def invalidate(self, reason: str) -> None:
            self.invalidations.append(reason)

        def request_refresh(self) -> None:
            self.refresh_count += 1

    runtime = Runtime()
    config = GatewayConfig()
    ctx = RpcContext(
        conn_id="config-patch",
        config=config,
        knowledge_runtime=runtime,
    )
    monkeypatch.setattr(
        rpc_config_module,
        "_persist_config",
        lambda new_config: None,
    )

    result = await rpc_config_module._handle_config_patch(params, ctx)

    assert result["patched"]
    assert runtime.invalidations == ["config_changed"]
    assert runtime.refresh_count == 1


@pytest.mark.asyncio
async def test_config_patch_unrelated_path_does_not_invalidate_knowledge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.gateway import rpc_config as rpc_config_module
    from opensquilla.gateway.config import GatewayConfig

    class Runtime:
        def __init__(self) -> None:
            self.invalidations: list[str] = []
            self.refresh_count = 0

        def invalidate(self, reason: str) -> None:
            self.invalidations.append(reason)

        def request_refresh(self) -> None:
            self.refresh_count += 1

    runtime = Runtime()
    ctx = RpcContext(
        conn_id="config-patch",
        config=GatewayConfig(),
        knowledge_runtime=runtime,
    )
    monkeypatch.setattr(rpc_config_module, "_persist_config", lambda new_config: None)

    await rpc_config_module._handle_config_patch(
        {"patches": {"diagnostics_enabled": True}},
        ctx,
    )

    assert runtime.invalidations == []
    assert runtime.refresh_count == 0


@pytest.mark.asyncio
async def test_knowledge_settings_patch_rejects_missing_confirmed_snapshot() -> None:
    class Backend:
        def update_settings(self, payload: dict[str, object]) -> dict[str, object]:
            return {"ok": True}

    class Runtime:
        def __init__(self) -> None:
            self.refreshes: list[dict[str, bool]] = []

        def current_backend(self) -> Backend:
            return Backend()

        def invalidate(self, reason: str) -> None:
            return None

        async def refresh(self, **kwargs: bool) -> None:
            self.refreshes.append(kwargs)
            return None

        def status_payload(self) -> dict[str, object]:
            return {
                "connectionState": "READY",
                "configuredDefaultRetrievalProfile": "old-profile",
            }

    runtime = Runtime()
    ctx = RpcContext(conn_id="test", config=SimpleNamespace(), knowledge_runtime=runtime)

    result = await get_dispatcher().dispatch(
        "settings-missing-confirmation",
        "knowledge.settings.patch",
        {"defaultRetrievalProfile": "hybrid"},
        ctx,
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "KNOWLEDGE_BACKEND_ERROR"
    assert result.error.message == "knowledge service request failed"
    assert "old-profile" not in result.error.message


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_kind", ["invalid_snapshot", "runtime_error"])
async def test_knowledge_settings_patch_redacts_unexpected_refresh_failure(
    failure_kind: str,
) -> None:
    class Backend:
        fail_status = False

        def update_settings(self, payload: dict[str, object]) -> dict[str, object]:
            self.fail_status = True
            return {"ok": True}

        def status(self) -> dict[str, object]:
            if not self.fail_status:
                return {
                    "capabilitiesVersion": "aaaaaaaaaaaaaaaa",
                    "configuredDefaultRetrievalProfile": "lexical",
                    "effectiveDefaultRetrievalProfile": "lexical",
                    "defaultFallbackReason": None,
                    "retrievalProfiles": [
                        {
                            "id": "lexical",
                            "label": "Lexical",
                            "kind": "lexical",
                            "available": True,
                        }
                    ],
                }
            if failure_kind == "runtime_error":
                raise RuntimeError("secret backend response body")
            return {
                "capabilitiesVersion": "malformed response containing secret",
                "configuredDefaultRetrievalProfile": "hybrid",
            }

    backend = Backend()
    runtime = KnowledgeRuntime(
        lambda: backend,
        enabled_provider=lambda: True,
        ttl_seconds_provider=lambda: 60.0,
    )
    initial = await runtime.refresh(force=True, raise_on_error=True)
    assert initial is not None
    ctx = RpcContext(conn_id="test", config=SimpleNamespace(), knowledge_runtime=runtime)

    result = await get_dispatcher().dispatch(
        f"settings-{failure_kind}",
        "knowledge.settings.patch",
        {"defaultRetrievalProfile": "hybrid"},
        ctx,
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "KNOWLEDGE_BACKEND_ERROR"
    assert result.error.message == "knowledge service request failed"
    assert "secret" not in result.error.message
    assert runtime.status_payload()["connectionState"] == "DEGRADED"
    assert runtime.status_payload()["capabilitiesStale"] is True


@pytest.mark.asyncio
async def test_knowledge_settings_patch_propagates_refresh_cancellation() -> None:
    class Backend:
        def update_settings(self, payload: dict[str, object]) -> dict[str, object]:
            return {"ok": True}

    class Runtime:
        def current_backend(self) -> Backend:
            return Backend()

        def invalidate(self, reason: str) -> None:
            return None

        async def refresh(self, **kwargs: bool) -> None:
            raise asyncio.CancelledError

    ctx = RpcContext(
        conn_id="test",
        config=SimpleNamespace(),
        knowledge_runtime=Runtime(),
    )

    with pytest.raises(asyncio.CancelledError):
        await get_dispatcher().dispatch(
            "settings-cancelled",
            "knowledge.settings.patch",
            {"defaultRetrievalProfile": "hybrid"},
            ctx,
        )


def _capability_payload(profile: str) -> dict[str, object]:
    return {
        "capabilitiesVersion": "aaaaaaaaaaaaaaaa",
        "configuredDefaultRetrievalProfile": profile,
        "effectiveDefaultRetrievalProfile": profile,
        "defaultFallbackReason": None,
        "retrievalProfiles": [
            {
                "id": profile,
                "label": profile.title(),
                "kind": "lexical",
                "available": True,
            }
        ],
    }


@pytest.mark.asyncio
async def test_knowledge_settings_patch_revalidates_after_joining_prewrite_refresh() -> None:
    class Backend:
        def __init__(self) -> None:
            self.profile = "lexical"
            self.status_count = 0
            self.first_status_started = Event()
            self.release_first_status = Event()
            self.write_completed = Event()

        def update_settings(self, payload: dict[str, object]) -> dict[str, object]:
            self.profile = str(payload["defaultRetrievalProfile"])
            self.write_completed.set()
            return {"ok": True}

        def status(self) -> dict[str, object]:
            self.status_count += 1
            requested_profile = self.profile
            if self.status_count == 1:
                self.first_status_started.set()
                assert self.release_first_status.wait(timeout=2.0)
            return _capability_payload(requested_profile)

    backend = Backend()
    runtime = KnowledgeRuntime(
        lambda: backend,
        enabled_provider=lambda: True,
        ttl_seconds_provider=lambda: 60.0,
    )
    prewrite_refresh = asyncio.create_task(
        runtime.refresh(force=True, raise_on_error=True)
    )
    assert await asyncio.to_thread(backend.first_status_started.wait, 2.0)
    ctx = RpcContext(conn_id="test", config=SimpleNamespace(), knowledge_runtime=runtime)
    patch_task = asyncio.create_task(
        get_dispatcher().dispatch(
            "settings-after-inflight",
            "knowledge.settings.patch",
            {"defaultRetrievalProfile": "hybrid"},
            ctx,
        )
    )
    assert await asyncio.to_thread(backend.write_completed.wait, 2.0)
    backend.release_first_status.set()

    result = await patch_task
    await prewrite_refresh

    assert result.ok is True
    assert result.payload is not None
    assert result.payload["configuredDefaultRetrievalProfile"] == "hybrid"
    assert backend.status_count == 2


@pytest.mark.asyncio
async def test_knowledge_settings_patch_second_refresh_uses_postwrite_cache() -> None:
    class Backend:
        def __init__(self) -> None:
            self.profile = "lexical"
            self.status_count = 0

        def update_settings(self, payload: dict[str, object]) -> dict[str, object]:
            self.profile = str(payload["defaultRetrievalProfile"])
            return {"ok": True}

        def status(self) -> dict[str, object]:
            self.status_count += 1
            return _capability_payload(self.profile)

    backend = Backend()
    runtime = KnowledgeRuntime(
        lambda: backend,
        enabled_provider=lambda: True,
        ttl_seconds_provider=lambda: 60.0,
    )
    ctx = RpcContext(conn_id="test", config=SimpleNamespace(), knowledge_runtime=runtime)

    result = await get_dispatcher().dispatch(
        "settings-postwrite",
        "knowledge.settings.patch",
        {"defaultRetrievalProfile": "hybrid"},
        ctx,
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload["configuredDefaultRetrievalProfile"] == "hybrid"
    assert backend.status_count == 1
