from __future__ import annotations

import asyncio
import inspect
import json
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import structlog.testing

from opensquilla.engine.types import ToolCall
from opensquilla.knowledge.backend import KnowledgeBackendError
from opensquilla.knowledge.manager import KnowledgeManager
from opensquilla.knowledge.runtime import (
    KnowledgeCapabilitySnapshot,
    KnowledgeConnectionState,
    KnowledgeRuntime,
    RetrievalProfileCapability,
)
from opensquilla.tools.builtin.knowledge_tools import create_knowledge_tools
from opensquilla.tools.dispatch import build_tool_handler
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import ToolContext, ToolError, current_tool_context


def _snapshot(
    state: KnowledgeConnectionState,
    *profile_ids: str,
) -> KnowledgeCapabilitySnapshot:
    ids = profile_ids or ("lexical",)
    return KnowledgeCapabilitySnapshot(
        state=state,
        capabilities_version="0123456789abcdef",
        profiles=tuple(
            RetrievalProfileCapability(
                id=profile_id,
                label=profile_id.title(),
                kind="lexical",
                available=True,
            )
            for profile_id in ids
        ),
        configured_default=ids[0],
        effective_default=ids[0],
        fallback_reason=None,
        fetched_at_ms=1,
        service_status={},
        stale=state is KnowledgeConnectionState.DEGRADED,
        legacy=state is KnowledgeConnectionState.LEGACY,
    )


async def _call_with_snapshot(
    handler: Any,
    snapshot: KnowledgeCapabilitySnapshot | None,
    **kwargs: Any,
) -> str:
    token = current_tool_context.set(
        ToolContext(knowledge_capability_snapshot=snapshot)
    )
    try:
        return await handler(**kwargs)
    finally:
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_knowledge_tools_register_and_search(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "report.md").write_text(
        "# AI 光通信\n\n光模块需求受 AI 算力建设带动，资本开支是关键变量。",
        encoding="utf-8",
    )
    manager = KnowledgeManager(tmp_path / "knowledge")
    manager.prepare_sample(source_root=source_root, limit=5)

    registry = ToolRegistry()
    create_knowledge_tools(manager=manager, registry=registry)

    assert {"knowledge_status", "knowledge_search", "knowledge_get"}.issubset(
        set(registry.list_names())
    )

    search_tool = registry.get("knowledge_search")
    assert search_tool is not None
    payload = json.loads(
        await _call_with_snapshot(
            search_tool.handler,
            _snapshot(KnowledgeConnectionState.LEGACY),
            query="AI 光通信",
            top_k=3,
        )
    )

    assert payload["results"]
    assert payload["results"][0]["chunkId"]

    get_tool = registry.get("knowledge_get")
    assert get_tool is not None
    chunk_id = payload["results"][0]["chunkId"]
    detail = json.loads(await get_tool.handler(chunk_id=chunk_id))
    assert detail["chunkId"] == chunk_id

@pytest.mark.asyncio
async def test_knowledge_search_tool_merges_collection_and_retrieval_filters() -> None:
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

        def status(self) -> dict[str, object]:
            return {"ok": True, "retrievalProfiles": []}

        def get(self, *, chunk_id=None, document_id=None):
            return None

    backend = RecordingKnowledgeBackend()
    registry = ToolRegistry()
    create_knowledge_tools(manager=backend, registry=registry)
    search_tool = registry.get("knowledge_search")
    assert search_tool is not None

    payload = json.loads(
        await _call_with_snapshot(
            search_tool.handler,
            _snapshot(KnowledgeConnectionState.READY, "hybrid_rrf_bge_m3_fts5"),
            query="苹果收入",
            top_k=5,
            collection="legacy",
            collection_id="datasets",
            retrieval_profile="hybrid_rrf_bge_m3_fts5",
            embedding_model="baai/bge-m3",
            embedding_dimensions=1024,
            filters={
                "source": "goldman",
                "collectionId": "old",
                "retrievalProfile": "sqlite_fts5_default",
                "embeddingModel": "old-model",
                "embeddingDimensions": 768,
            },
        )
    )

    assert payload["count"] == 0
    assert backend.calls == [
        {
            "query": "苹果收入",
            "top_k": 5,
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
async def test_knowledge_tools_use_live_config_and_offload_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.tools.builtin import knowledge_tools as knowledge_tools_module

    class StatusBackend:
        def __init__(self, endpoint: str) -> None:
            self.endpoint = endpoint

        def status(self) -> dict[str, object]:
            if self.endpoint == "first":
                time.sleep(0.35)
            return {"ok": True, "endpoint": self.endpoint}

    config = SimpleNamespace(endpoint="first")
    monkeypatch.setattr(
        knowledge_tools_module,
        "manager_from_config",
        lambda live_config: StatusBackend(live_config.endpoint),
    )
    registry = ToolRegistry()
    create_knowledge_tools(config=config, registry=registry)
    status_tool = registry.get("knowledge_status")
    assert status_tool is not None

    loop = asyncio.get_running_loop()
    started = loop.time()
    request = asyncio.create_task(status_tool.handler())
    await asyncio.sleep(0.01)

    assert loop.time() - started < 0.2
    assert json.loads(await request)["endpoint"] == "first"

    config.endpoint = "second"
    assert json.loads(await status_tool.handler())["endpoint"] == "second"


class _RecordingSearchBackend:
    def __init__(self, marker: str = "runtime") -> None:
        self.marker = marker
        self.search_calls: list[dict[str, Any]] = []

    def search(
        self,
        query: str,
        *,
        top_k: int = 8,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.search_calls.append(
            {"query": query, "top_k": top_k, "filters": dict(filters or {})}
        )
        return {"marker": self.marker, "query": query, "results": [], "count": 0}

    def get(
        self,
        *,
        chunk_id: str | None = None,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        return {"marker": self.marker, "chunkId": chunk_id, "documentId": document_id}


class _RecordingRuntime:
    def __init__(self, backend: _RecordingSearchBackend) -> None:
        self.backend = backend
        self.backend_calls = 0
        self.status_calls = 0
        self.search_calls = 0

    def current_backend(self) -> _RecordingSearchBackend:
        self.backend_calls += 1
        return self.backend

    def status_payload(self) -> dict[str, Any]:
        self.status_calls += 1
        return {"source": "runtime-status"}

    async def call_with_capability_retry(self, operation: Any) -> dict[str, Any]:
        self.search_calls += 1
        return operation(self.current_backend())


def test_knowledge_tool_definitions_are_runtime_side_effect_free() -> None:
    class NoTouchRuntime:
        def current_backend(self) -> Any:
            raise AssertionError("definition generation touched the backend")

        def status_payload(self) -> dict[str, Any]:
            raise AssertionError("definition generation fetched status")

        async def call_with_capability_retry(self, operation: Any) -> Any:
            raise AssertionError("definition generation invoked a search")

    registry = ToolRegistry()
    create_knowledge_tools(runtime=NoTouchRuntime(), registry=registry)

    definitions = registry.to_tool_definitions(
        ToolContext(
            knowledge_capability_snapshot=_snapshot(KnowledgeConnectionState.READY)
        )
    )
    search_definition = next(
        definition for definition in definitions if definition.name == "knowledge_search"
    )
    properties = search_definition.input_schema.properties
    registered = registry.get("knowledge_search")
    assert registered is not None

    assert "retrieval_profile" in properties
    assert properties.keys().isdisjoint(
        {"embedding_model", "embedding_dimensions"}
    )
    assert properties["retrieval_profile"]["description"] == (
        "Optional one-request override. Omit to use the Knowledge service default."
    )
    signature = inspect.signature(registered.handler)
    assert {"embedding_model", "embedding_dimensions"} <= set(signature.parameters)


@pytest.mark.asyncio
async def test_knowledge_status_and_get_use_live_runtime_state() -> None:
    first = _RecordingSearchBackend("first")
    runtime = _RecordingRuntime(first)
    registry = ToolRegistry()
    create_knowledge_tools(
        manager=object(),  # type: ignore[arg-type]
        runtime=runtime,
        registry=registry,
    )
    status_tool = registry.get("knowledge_status")
    get_tool = registry.get("knowledge_get")
    assert status_tool is not None
    assert get_tool is not None

    assert json.loads(await status_tool.handler()) == {"source": "runtime-status"}
    assert runtime.status_calls == 1
    assert runtime.backend_calls == 0

    assert json.loads(await get_tool.handler(chunk_id="one"))["marker"] == "first"
    runtime.backend = _RecordingSearchBackend("second")
    assert json.loads(await get_tool.handler(chunk_id="two"))["marker"] == "second"
    assert runtime.backend_calls == 2


@pytest.mark.parametrize(
    "state",
    [
        KnowledgeConnectionState.READY,
        KnowledgeConnectionState.DEGRADED,
        KnowledgeConnectionState.LEGACY,
    ],
)
@pytest.mark.asyncio
async def test_knowledge_search_default_uses_runtime_in_available_states(
    state: KnowledgeConnectionState,
) -> None:
    backend = _RecordingSearchBackend()
    runtime = _RecordingRuntime(backend)
    registry = ToolRegistry()
    create_knowledge_tools(runtime=runtime, registry=registry)
    search_tool = registry.get("knowledge_search")
    assert search_tool is not None

    result = json.loads(
        await _call_with_snapshot(
            search_tool.handler,
            _snapshot(state),
            query="revenue",
        )
    )

    assert result["marker"] == "runtime"
    assert runtime.search_calls == 1


@pytest.mark.parametrize(
    "state",
    [
        KnowledgeConnectionState.DISCOVERING,
        KnowledgeConnectionState.UNAVAILABLE,
        None,
    ],
)
@pytest.mark.asyncio
async def test_knowledge_search_rejects_forced_calls_when_unavailable(
    state: KnowledgeConnectionState | None,
) -> None:
    runtime = _RecordingRuntime(_RecordingSearchBackend())
    registry = ToolRegistry()
    create_knowledge_tools(runtime=runtime, registry=registry)
    search_tool = registry.get("knowledge_search")
    assert search_tool is not None
    snapshot = _snapshot(state) if state is not None else None

    with pytest.raises(ToolError, match="knowledge_search_unavailable"):
        await _call_with_snapshot(search_tool.handler, snapshot, query="revenue")

    assert runtime.search_calls == 0


@pytest.mark.parametrize(
    ("state", "available_profiles", "requested_profile"),
    [
        (KnowledgeConnectionState.DEGRADED, ("lexical",), "lexical"),
        (KnowledgeConnectionState.LEGACY, ("lexical",), "lexical"),
        (KnowledgeConnectionState.READY, ("new-profile",), "old-profile"),
    ],
)
@pytest.mark.asyncio
async def test_knowledge_search_validates_explicit_profile_at_call_time(
    state: KnowledgeConnectionState,
    available_profiles: tuple[str, ...],
    requested_profile: str,
) -> None:
    runtime = _RecordingRuntime(_RecordingSearchBackend())
    registry = ToolRegistry()
    create_knowledge_tools(runtime=runtime, registry=registry)
    search_tool = registry.get("knowledge_search")
    assert search_tool is not None

    with pytest.raises(ToolError, match="retrieval_profile_unavailable"):
        await _call_with_snapshot(
            search_tool.handler,
            _snapshot(state, *available_profiles),
            query="revenue",
            retrieval_profile=requested_profile,
        )

    assert runtime.search_calls == 0


@pytest.mark.asyncio
async def test_knowledge_search_filters_cannot_bypass_profile_validation() -> None:
    runtime = _RecordingRuntime(_RecordingSearchBackend())
    registry = ToolRegistry()
    create_knowledge_tools(runtime=runtime, registry=registry)
    search_tool = registry.get("knowledge_search")
    assert search_tool is not None

    with pytest.raises(ToolError, match="retrieval_profile_unavailable"):
        await _call_with_snapshot(
            search_tool.handler,
            _snapshot(KnowledgeConnectionState.READY, "new-profile"),
            query="revenue",
            filters={"retrievalProfile": "old-profile"},
        )

    assert runtime.search_calls == 0


@pytest.mark.asyncio
async def test_knowledge_search_sanitizes_final_backend_error() -> None:
    class FailingRuntime(_RecordingRuntime):
        async def call_with_capability_retry(self, operation: Any) -> dict[str, Any]:
            raise KnowledgeBackendError(
                status_code=502,
                code="knowledge_backend_unavailable",
                message="SECRET upstream response body token=abc123",
            )

    registry = ToolRegistry()
    create_knowledge_tools(
        runtime=FailingRuntime(_RecordingSearchBackend()),
        registry=registry,
    )
    search_tool = registry.get("knowledge_search")
    assert search_tool is not None

    with pytest.raises(ToolError) as raised:
        await _call_with_snapshot(
            search_tool.handler,
            _snapshot(KnowledgeConnectionState.READY),
            query="revenue",
        )

    assert str(raised.value) == (
        "knowledge_search_failed (backend_code=knowledge_backend_unavailable)"
    )
    assert "SECRET" not in str(raised.value)
    assert "abc123" not in str(raised.value)


@pytest.mark.asyncio
async def test_knowledge_search_rejects_malicious_backend_error_details() -> None:
    class FailingRuntime(_RecordingRuntime):
        async def call_with_capability_retry(self, operation: Any) -> dict[str, Any]:
            raise KnowledgeBackendError(
                status_code=502,
                code="SECRET_code_token=abc123",
                message="SECRET response body bearer=def456",
            )

    registry = ToolRegistry()
    create_knowledge_tools(
        runtime=FailingRuntime(_RecordingSearchBackend()),
        registry=registry,
    )
    search_tool = registry.get("knowledge_search")
    assert search_tool is not None

    with pytest.raises(ToolError) as raised:
        await _call_with_snapshot(
            search_tool.handler,
            _snapshot(KnowledgeConnectionState.READY),
            query="revenue",
        )

    error = raised.value
    assert str(error) == "knowledge_search_failed (backend_code=knowledge_error)"
    assert error.__cause__ is None
    assert error.__context__ is None
    rendered = " ".join(
        (
            str(error),
            repr(error),
            repr(error.__cause__),
            repr(error.__context__),
        )
    )
    assert "SECRET" not in rendered
    assert "abc123" not in rendered
    assert "def456" not in rendered


@pytest.mark.asyncio
async def test_knowledge_search_rejects_unhashable_backend_error_code() -> None:
    malicious_code: Any = ["SECRET_list_code_token=ghi789"]

    class FailingRuntime(_RecordingRuntime):
        async def call_with_capability_retry(self, operation: Any) -> dict[str, Any]:
            raise KnowledgeBackendError(
                status_code=502,
                code=malicious_code,
                message="SECRET unhashable response bearer=jkl012",
            )

    registry = ToolRegistry()
    create_knowledge_tools(
        runtime=FailingRuntime(_RecordingSearchBackend()),
        registry=registry,
    )
    search_tool = registry.get("knowledge_search")
    assert search_tool is not None

    with pytest.raises(ToolError) as raised:
        await _call_with_snapshot(
            search_tool.handler,
            _snapshot(KnowledgeConnectionState.READY),
            query="revenue",
        )

    error = raised.value
    assert str(error) == "knowledge_search_failed (backend_code=knowledge_error)"
    assert error.__cause__ is None
    assert error.__context__ is None
    rendered = " ".join((str(error), repr(error), repr(error.__context__)))
    assert "SECRET" not in rendered
    assert "ghi789" not in rendered
    assert "jkl012" not in rendered


@pytest.mark.asyncio
async def test_knowledge_search_does_not_touch_non_string_backend_error_code() -> None:
    touched: list[str] = []

    class HostileCode:
        def __hash__(self) -> int:
            touched.append("hash")
            raise AssertionError("SECRET hash side effect")

        def __eq__(self, other: object) -> bool:
            touched.append("eq")
            raise AssertionError("SECRET equality side effect")

        def __str__(self) -> str:
            touched.append("str")
            raise AssertionError("SECRET string side effect")

        def __repr__(self) -> str:
            touched.append("repr")
            raise AssertionError("SECRET repr side effect")

    hostile_code: Any = HostileCode()

    class FailingRuntime(_RecordingRuntime):
        async def call_with_capability_retry(self, operation: Any) -> dict[str, Any]:
            raise KnowledgeBackendError(
                status_code=502,
                code=hostile_code,
                message="SECRET hostile response token=mno345",
            )

    registry = ToolRegistry()
    create_knowledge_tools(
        runtime=FailingRuntime(_RecordingSearchBackend()),
        registry=registry,
    )
    search_tool = registry.get("knowledge_search")
    assert search_tool is not None

    with pytest.raises(ToolError) as raised:
        await _call_with_snapshot(
            search_tool.handler,
            _snapshot(KnowledgeConnectionState.READY),
            query="revenue",
        )

    error = raised.value
    assert str(error) == "knowledge_search_failed (backend_code=knowledge_error)"
    assert error.__cause__ is None
    assert error.__context__ is None
    assert touched == []


@pytest.mark.asyncio
async def test_knowledge_search_dispatch_sanitizes_unhashable_code_and_logs() -> None:
    malicious_code: Any = ["SECRET_dispatch_code_token=pqr678"]

    class FailingRuntime(_RecordingRuntime):
        async def call_with_capability_retry(self, operation: Any) -> dict[str, Any]:
            raise KnowledgeBackendError(
                status_code=502,
                code=malicious_code,
                message="SECRET dispatch response bearer=stu901",
            )

    registry = ToolRegistry()
    create_knowledge_tools(
        runtime=FailingRuntime(_RecordingSearchBackend()),
        registry=registry,
    )
    handler = build_tool_handler(
        registry,
        ToolContext(
            is_owner=True,
            knowledge_capability_snapshot=_snapshot(KnowledgeConnectionState.READY),
        ),
    )

    with structlog.testing.capture_logs() as captured:
        result = await handler(
            ToolCall(
                tool_use_id="knowledge-malicious-error",
                tool_name="knowledge_search",
                arguments={"query": "revenue"},
            )
        )

    envelope = json.loads(result.content)
    assert result.is_error is True
    assert envelope["status"] == "error"
    assert envelope["tool"] == "knowledge_search"
    assert envelope["error_class"] == "ToolError"
    assert envelope["retry_allowed"] is False
    failed_log = next(
        event for event in captured if event["event"] == "dispatch.tool_failed"
    )
    logged_exception = failed_log["exc_info"]
    rendered = " ".join(
        (
            result.content,
            repr(failed_log),
            repr(captured),
            repr(logged_exception.__context__),
            "".join(traceback.format_exception(logged_exception)),
        )
    )
    assert "knowledge_error" in rendered
    assert logged_exception.__cause__ is None
    assert logged_exception.__context__ is None
    assert "SECRET_dispatch_code_token=pqr678" not in rendered
    assert "SECRET dispatch response bearer=stu901" not in rendered
    assert "SECRET" not in rendered
    assert "pqr678" not in rendered
    assert "stu901" not in rendered


@pytest.mark.asyncio
async def test_knowledge_search_runtime_retries_one_stale_capability_failure() -> None:
    class RetryBackend:
        def __init__(self) -> None:
            self.status_calls = 0
            self.search_calls = 0

        def status(self) -> dict[str, Any]:
            self.status_calls += 1
            return {
                "ok": True,
                "capabilitiesVersion": "fedcba9876543210",
                "configuredDefaultRetrievalProfile": "lexical",
                "effectiveDefaultRetrievalProfile": "lexical",
                "defaultFallbackReason": None,
                "retrievalProfiles": [
                    {
                        "id": "lexical",
                        "label": "Lexical",
                        "kind": "lexical",
                        "available": True,
                        "reason": None,
                        "model": None,
                        "dimensions": None,
                    }
                ],
            }

        def search(
            self,
            query: str,
            *,
            top_k: int = 8,
            filters: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            self.search_calls += 1
            if self.search_calls == 1:
                raise KnowledgeBackendError(
                    status_code=409,
                    code="invalid_retrieval_profile",
                    message="stale capability",
                )
            return {"query": query, "results": [], "count": 0}

    backend = RetryBackend()
    runtime = KnowledgeRuntime(
        lambda: backend,  # type: ignore[arg-type]
        enabled_provider=lambda: True,
        ttl_seconds_provider=lambda: 60.0,
    )
    registry = ToolRegistry()
    create_knowledge_tools(runtime=runtime, registry=registry)
    search_tool = registry.get("knowledge_search")
    assert search_tool is not None

    payload = json.loads(
        await _call_with_snapshot(
            search_tool.handler,
            _snapshot(KnowledgeConnectionState.READY, "lexical"),
            query="revenue",
            retrieval_profile="lexical",
        )
    )

    assert payload["count"] == 0
    assert backend.search_calls == 2
    assert backend.status_calls == 1


@pytest.mark.asyncio
async def test_blank_top_level_profile_does_not_hide_invalid_filter_profile() -> None:
    backend = _RecordingSearchBackend()
    runtime = _RecordingRuntime(backend)
    registry = ToolRegistry()
    create_knowledge_tools(runtime=runtime, registry=registry)
    search_tool = registry.get("knowledge_search")
    assert search_tool is not None

    with pytest.raises(ToolError, match="retrieval_profile_unavailable"):
        await _call_with_snapshot(
            search_tool.handler,
            _snapshot(KnowledgeConnectionState.READY, "new-profile"),
            query="revenue",
            retrieval_profile="   ",
            filters={"retrievalProfile": "old-profile"},
        )

    assert runtime.search_calls == 0
    assert backend.search_calls == []


@pytest.mark.asyncio
async def test_valid_top_level_profile_overrides_filter_with_normalized_value() -> None:
    backend = _RecordingSearchBackend()
    runtime = _RecordingRuntime(backend)
    registry = ToolRegistry()
    create_knowledge_tools(runtime=runtime, registry=registry)
    search_tool = registry.get("knowledge_search")
    assert search_tool is not None

    await _call_with_snapshot(
        search_tool.handler,
        _snapshot(KnowledgeConnectionState.READY, "lexical"),
        query="revenue",
        retrieval_profile="  lexical  ",
        filters={"retrievalProfile": "old-profile", "source": "report"},
    )

    assert backend.search_calls == [
        {
            "query": "revenue",
            "top_k": 8,
            "filters": {
                "retrievalProfile": "lexical",
                "source": "report",
            },
        }
    ]


@pytest.mark.asyncio
async def test_blank_filter_profile_is_not_sent_to_backend() -> None:
    backend = _RecordingSearchBackend()
    runtime = _RecordingRuntime(backend)
    registry = ToolRegistry()
    create_knowledge_tools(runtime=runtime, registry=registry)
    search_tool = registry.get("knowledge_search")
    assert search_tool is not None

    await _call_with_snapshot(
        search_tool.handler,
        _snapshot(KnowledgeConnectionState.READY, "lexical"),
        query="revenue",
        filters={"retrievalProfile": "   ", "source": "report"},
    )

    assert backend.search_calls == [
        {
            "query": "revenue",
            "top_k": 8,
            "filters": {"source": "report"},
        }
    ]


@pytest.mark.asyncio
async def test_knowledge_search_without_tool_context_fails_closed() -> None:
    backend = _RecordingSearchBackend()
    runtime = _RecordingRuntime(backend)
    registry = ToolRegistry()
    create_knowledge_tools(runtime=runtime, registry=registry)
    search_tool = registry.get("knowledge_search")
    assert search_tool is not None
    token = current_tool_context.set(None)

    try:
        with pytest.raises(ToolError, match="knowledge_search_unavailable"):
            await search_tool.handler(query="revenue")
    finally:
        current_tool_context.reset(token)

    assert runtime.search_calls == 0
    assert backend.search_calls == []
