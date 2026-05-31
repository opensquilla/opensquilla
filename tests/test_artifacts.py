from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.artifacts import (
    DEFAULT_ARTIFACT_DISK_BUDGET_BYTES,
    DEFAULT_ARTIFACT_MAX_BYTES,
    ArtifactBudgetError,
    ArtifactIntegrityError,
    ArtifactStore,
    artifact_payload,
)
from opensquilla.tools.builtin.artifacts import publish_artifact
from opensquilla.tools.types import CallerKind, ToolContext, ToolError, current_tool_context


def test_artifact_store_round_trips_metadata_and_bytes(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    ref = store.publish_bytes(
        b"hello\n",
        session_id="session-1",
        session_key="agent:main:webchat:session-1",
        name="report.txt",
        mime="text/plain",
        source="publish_artifact",
    )
    path = store.path_for(ref)

    assert ref.kind == "artifact_ref"
    assert ref.name == "report.txt"
    assert ref.size == 6
    assert ref.download_url == "/api/v1/artifacts/" + ref.id
    assert path.read_bytes() == b"hello\n"

    resolved_ref, resolved_path = store.resolve_for_download(ref.id, session_id="session-1")
    assert resolved_ref == ref
    assert resolved_path == path


def test_artifact_store_finds_existing_session_deliverable_by_name_and_sha(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)
    ref = store.publish_bytes(
        b"pptx bytes",
        session_id="session-1",
        session_key="agent:main:webchat:session-1",
        name="brief.pptx",
        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        source="create_pptx",
    )

    found = store.find_existing_ref(
        session_id="session-1",
        session_key="agent:main:webchat:session-1",
        sha256=ref.sha256,
        name="brief.pptx",
        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )

    assert found == ref
    assert (
        store.find_existing_ref(
            session_id="session-2",
            session_key="agent:main:webchat:session-2",
            sha256=ref.sha256,
            name="brief.pptx",
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
        is None
    )


def test_artifact_store_skips_existing_deliverable_with_bad_material(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)
    ref = store.publish_bytes(
        b"pptx bytes",
        session_id="session-1",
        session_key="agent:main:webchat:session-1",
        name="brief.pptx",
        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        source="create_pptx",
    )
    store.path_for(ref).write_bytes(b"corrupt")

    assert (
        store.find_existing_ref(
            session_id="session-1",
            session_key="agent:main:webchat:session-1",
            sha256=ref.sha256,
            name="brief.pptx",
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
        is None
    )


def test_artifact_store_uses_short_material_paths_for_uuid_sessions(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    long_root = tmp_path / ("deep-root-" + ("x" * 80))
    store = ArtifactStore(long_root)
    session_id = "532d5065-abce-499f-97b0-bbf2a067d5ab"

    ref = store.publish_bytes(
        b"pptx",
        session_id=session_id,
        session_key="agent:main:webchat:default",
        name="北京2027房价预测分析报告.pptx",
        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        source="publish_artifact",
    )

    material_path = store.path_for(ref)
    assert material_path.name == "data"
    assert session_id not in str(material_path)
    assert len(str(material_path)) < 260
    resolved_ref, resolved_path = store.resolve_for_download(ref.id, session_id=session_id)
    assert resolved_ref == ref
    assert resolved_path == material_path


def test_artifact_payload_omits_session_key_and_query_token(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    ref = store.publish_bytes(
        b"hello\n",
        session_id="session-1",
        session_key="agent:main:webchat:session-1",
        name="report.txt",
        mime="text/plain",
        source="publish_artifact",
    )

    payload = artifact_payload(ref)

    assert "session_key" not in payload
    assert "sessionKey" not in json.dumps(payload)
    assert payload["download_url"] == f"/api/v1/artifacts/{ref.id}"


def test_artifact_store_preserves_unicode_filename_and_normalizes_mime_params(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)

    ref = store.publish_bytes(
        b"hello\n",
        session_id="session-1",
        session_key="agent:main:webchat:session-1",
        name="记忆修补师.txt",
        mime="text/plain; charset=utf-8",
        source="publish_artifact",
    )

    assert ref.name == "记忆修补师.txt"
    assert ref.mime == "text/plain"


def test_artifact_store_rejects_hash_mismatch(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    ref = store.publish_bytes(
        b"hello",
        session_id="session-1",
        session_key="agent:main:webchat:session-1",
        name="report.txt",
        mime="text/plain",
        source="publish_artifact",
    )

    store.path_for(ref).write_bytes(b"tampered")

    with pytest.raises(ArtifactIntegrityError):
        store.resolve_for_download(ref.id, session_id="session-1")


def test_artifact_store_enforces_per_file_and_disk_budgets(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    with pytest.raises(ArtifactBudgetError):
        store.publish_bytes(
            b"abcdef",
            session_id="session-1",
            session_key="agent:main:webchat:session-1",
            name="too-big.txt",
            mime="text/plain",
            source="publish_artifact",
            max_bytes=5,
        )

    assert not list((tmp_path / "artifacts").rglob("too-big.txt"))

    store.publish_bytes(
        b"abc",
        session_id="session-1",
        session_key="agent:main:webchat:session-1",
        name="ok.txt",
        mime="text/plain",
        source="publish_artifact",
        disk_budget_bytes=6,
    )
    with pytest.raises(ArtifactBudgetError):
        store.publish_bytes(
            b"defg",
            session_id="session-1",
            session_key="agent:main:webchat:session-1",
            name="over-budget.txt",
            mime="text/plain",
            source="publish_artifact",
            disk_budget_bytes=6,
        )


def test_artifact_budget_defaults_are_open_source_sized() -> None:
    assert DEFAULT_ARTIFACT_MAX_BYTES == 30 * 1024 * 1024
    assert DEFAULT_ARTIFACT_DISK_BUDGET_BYTES == 512 * 1024 * 1024


@pytest.mark.asyncio
async def test_publish_artifact_tool_allows_workspace_file_only(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    output = workspace / "report.txt"
    output.write_text("ready", encoding="utf-8")
    ctx = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.WEB,
        workspace_dir=str(workspace),
        artifact_media_root=str(tmp_path / "media"),
        artifact_session_id="session-1",
        session_key="agent:main:webchat:session-1",
    )

    token = current_tool_context.set(ctx)
    try:
        result = await publish_artifact(path="report.txt", name="final.txt", mime="text/plain")
    finally:
        current_tool_context.reset(token)

    payload = json.loads(result)
    assert payload["status"] == "published"
    assert payload["artifact"]["name"] == "final.txt"
    assert payload["artifact"]["mime"] == "text/plain"
    assert payload["artifact"]["session_id"] == "session-1"
    assert "session_key" not in payload["artifact"]
    assert "sessionKey" not in json.dumps(payload["artifact"])
    # The LLM-facing artifact has no URL — models tend to fabricate a host
    # when shown a relative URL ending in /api/v1/artifacts/...
    assert "download_url" not in payload["artifact"]
    assert payload["artifact"]["workspace_path"] == "report.txt"
    assert payload["artifact"]["local_path"] == str(output.resolve())
    assert "note" in payload
    assert "local_path" in payload["note"]
    assert "final response" in payload["note"]
    assert "Do not run more tools" in payload["note"]
    # The frontend event path still gets the full payload (with download_url).
    assert len(ctx.published_artifacts) == 1
    full_artifact = ctx.published_artifacts[0]
    assert full_artifact["download_url"] == f"/api/v1/artifacts/{full_artifact['id']}"
    llm_artifact = {
        k: v
        for k, v in payload["artifact"].items()
        if k not in {"workspace_path", "local_path"}
    }
    assert {k: v for k, v in full_artifact.items() if k != "download_url"} == llm_artifact


@pytest.mark.asyncio
async def test_publish_artifact_tool_preserves_source_extension_for_display_name(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    output = workspace / "generated-chart.png"
    output.write_bytes(b"\x89PNG\r\n\x1a\nimage bytes")
    ctx = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.WEB,
        workspace_dir=str(workspace),
        artifact_media_root=str(tmp_path / "media"),
        artifact_session_id="session-1",
        session_key="agent:main:webchat:session-1",
    )

    token = current_tool_context.set(ctx)
    try:
        result = await publish_artifact(
            path="generated-chart.png",
            name="Friendly Chart",
        )
    finally:
        current_tool_context.reset(token)

    payload = json.loads(result)

    assert payload["status"] == "published"
    assert payload["artifact"]["name"] == "Friendly Chart.png"
    assert payload["artifact"]["mime"] == "image/png"
    assert ctx.published_artifacts[0]["name"] == "Friendly Chart.png"
    assert ctx.published_artifacts[0]["mime"] == "image/png"


@pytest.mark.asyncio
async def test_publish_artifact_tool_keeps_download_name_mime_when_source_is_generic(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    output = workspace / "payload.bin"
    output.write_bytes(b"image bytes")
    ctx = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.WEB,
        workspace_dir=str(workspace),
        artifact_media_root=str(tmp_path / "media"),
        artifact_session_id="session-1",
        session_key="agent:main:webchat:session-1",
    )

    token = current_tool_context.set(ctx)
    try:
        result = await publish_artifact(
            path="payload.bin",
            name="Friendly Chart.png",
        )
    finally:
        current_tool_context.reset(token)

    payload = json.loads(result)

    assert payload["artifact"]["name"] == "Friendly Chart.png"
    assert payload["artifact"]["mime"] == "image/png"


@pytest.mark.asyncio
async def test_publish_artifact_tool_hides_local_path_from_non_owner_channel(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    output = workspace / "report.txt"
    output.write_text("ready", encoding="utf-8")
    ctx = ToolContext(
        is_owner=False,
        caller_kind=CallerKind.CHANNEL,
        channel_kind="feishu",
        workspace_dir=str(workspace),
        artifact_media_root=str(tmp_path / "media"),
        artifact_session_id="session-1",
        session_key="agent:main:feishu:direct:u1",
    )

    token = current_tool_context.set(ctx)
    try:
        result = await publish_artifact(path="report.txt", name="final.txt", mime="text/plain")
    finally:
        current_tool_context.reset(token)

    payload = json.loads(result)
    assert payload["status"] == "published"
    assert "download_url" not in payload["artifact"]
    assert "local_path" not in payload["artifact"]
    assert "workspace_path" not in payload["artifact"]
    assert "local_path" not in payload["note"]
    assert "final response" in payload["note"]


@pytest.mark.asyncio
async def test_publish_artifact_tool_accepts_workspace_alias(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    output = workspace / "paper.pdf"
    output.write_bytes(b"%PDF-1.5\nready")
    ctx = ToolContext(
        workspace_dir=str(workspace),
        artifact_media_root=str(tmp_path / "media"),
        artifact_session_id="session-1",
        session_key="agent:main:webchat:session-1",
    )

    token = current_tool_context.set(ctx)
    try:
        result = await publish_artifact(
            path="/workspace/paper.pdf",
            name="paper.pdf",
            mime="application/pdf",
        )
    finally:
        current_tool_context.reset(token)

    payload = json.loads(result)
    assert payload["status"] == "published"
    assert payload["artifact"]["name"] == "paper.pdf"
    assert len(ctx.published_artifacts) == 1


@pytest.mark.asyncio
async def test_publish_artifact_tool_is_idempotent_for_existing_turn_artifact(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    output = workspace / "generated-image.png"
    output.write_bytes(b"\x89PNG\r\n\x1a\nsame image")
    ctx = ToolContext(
        workspace_dir=str(workspace),
        artifact_media_root=str(tmp_path / "media"),
        artifact_session_id="session-1",
        session_key="agent:main:feishu:direct:u1",
    )

    token = current_tool_context.set(ctx)
    try:
        first = json.loads(
            await publish_artifact(
                path="generated-image.png",
                name="generated-image.png",
                mime="image/png",
            )
        )
        second = json.loads(
            await publish_artifact(
                path="generated-image.png",
                name="OpenSquilla-Mascot.png",
                mime="image/png",
            )
        )
    finally:
        current_tool_context.reset(token)

    assert first["status"] == "published"
    assert second["status"] == "already_published"
    assert second["artifact"]["id"] == first["artifact"]["id"]
    assert second["artifact"]["name"] == "generated-image.png"
    assert "already registered" in second["note"]
    assert len(ctx.published_artifacts) == 1


@pytest.mark.asyncio
async def test_publish_artifact_tool_reuses_existing_session_deliverable_across_contexts(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    output = workspace / "brief.pptx"
    output.write_bytes(b"pptx bytes")
    media_root = tmp_path / "media"

    ctx1 = ToolContext(
        workspace_dir=str(workspace),
        artifact_media_root=str(media_root),
        artifact_session_id="session-1",
        session_key="agent:main:webchat:session-1",
    )
    token = current_tool_context.set(ctx1)
    try:
        first = json.loads(
            await publish_artifact(
                path="brief.pptx",
                name="brief.pptx",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
        )
    finally:
        current_tool_context.reset(token)

    ctx2 = ToolContext(
        workspace_dir=str(workspace),
        artifact_media_root=str(media_root),
        artifact_session_id="session-1",
        session_key="agent:main:webchat:session-1",
    )
    token = current_tool_context.set(ctx2)
    try:
        second = json.loads(
            await publish_artifact(
                path="brief.pptx",
                name="brief.pptx",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
        )
    finally:
        current_tool_context.reset(token)

    assert first["status"] == "published"
    assert second["status"] == "already_published"
    assert second["artifact"]["id"] == first["artifact"]["id"]
    assert len(ctx1.published_artifacts) == 1
    assert len(ctx2.published_artifacts) == 1
    assert ctx2.published_artifacts[0]["id"] == first["artifact"]["id"]


@pytest.mark.asyncio
async def test_publish_artifact_tool_republishes_changed_bytes_at_same_path(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    output = workspace / "report.txt"
    output.write_text("first", encoding="utf-8")
    ctx = ToolContext(
        workspace_dir=str(workspace),
        artifact_media_root=str(tmp_path / "media"),
        artifact_session_id="session-1",
        session_key="agent:main:webchat:session-1",
    )

    token = current_tool_context.set(ctx)
    try:
        first = json.loads(await publish_artifact(path="report.txt", mime="text/plain"))
        output.write_text("second", encoding="utf-8")
        second = json.loads(await publish_artifact(path="report.txt", mime="text/plain"))
    finally:
        current_tool_context.reset(token)

    assert first["status"] == "published"
    assert second["status"] == "published"
    assert second["artifact"]["id"] != first["artifact"]["id"]
    assert len(ctx.published_artifacts) == 2


@pytest.mark.asyncio
async def test_publish_artifact_tool_reports_storage_write_failure(
    monkeypatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    output = workspace / "report.txt"
    output.write_text("ready", encoding="utf-8")
    ctx = ToolContext(
        workspace_dir=str(workspace),
        artifact_media_root=str(tmp_path / "media"),
        artifact_session_id="session-1",
        session_key="agent:main:webchat:session-1",
    )

    def fail_publish_file(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("media temp path unavailable")

    monkeypatch.setattr(ArtifactStore, "publish_file", fail_publish_file)
    token = current_tool_context.set(ctx)
    try:
        with pytest.raises(ToolError, match="artifact storage path is unavailable"):
            await publish_artifact(path="report.txt", name="final.txt", mime="text/plain")
    finally:
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_publish_artifact_tool_missing_file_reports_workspace_candidates(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    reports = workspace / "reports"
    reports.mkdir(parents=True)
    candidate = reports / "AI Agent Comparison 2026.pptx"
    candidate.write_bytes(b"pptx")
    ctx = ToolContext(
        workspace_dir=str(workspace),
        artifact_media_root=str(tmp_path / "media"),
        artifact_session_id="session-1",
        session_key="agent:main:webchat:session-1",
    )

    token = current_tool_context.set(ctx)
    try:
        with pytest.raises(ToolError) as exc_info:
            await publish_artifact(path="AI_Agent_Comparison_2026.pptx")
    finally:
        current_tool_context.reset(token)

    message = str(exc_info.value)
    assert "artifact file not found" in message
    assert f"active workspace: {workspace.resolve()}" in message
    assert "resolved path:" in message
    assert "candidate files:" in message
    assert "reports/AI Agent Comparison 2026.pptx" in message.replace("\\", "/")


@pytest.mark.asyncio
async def test_publish_artifact_rejects_foreign_posix_target_with_workspace_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import opensquilla.tools.builtin.artifacts as artifacts_module

    monkeypatch.setattr(artifacts_module, "os", SimpleNamespace(name="nt"), raising=False)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    actual = workspace / "report.pptx"
    actual.write_bytes(b"pptx")
    ctx = ToolContext(
        workspace_dir=str(workspace),
        artifact_media_root=str(tmp_path / "media"),
        artifact_session_id="session-1",
        session_key="agent:main:webchat:session-1",
    )

    token = current_tool_context.set(ctx)
    try:
        with pytest.raises(ToolError) as exc_info:
            await publish_artifact(path="/Users/a1/Desktop/report.pptx")
    finally:
        current_tool_context.reset(token)

    message = str(exc_info.value)
    assert "foreign_host_path" in message
    assert "requested path is from another host/platform" in message
    assert "report.pptx" in message
    assert "D:\\Users" not in message
    assert not ctx.published_artifacts


@pytest.mark.asyncio
async def test_publish_artifact_tool_rejects_missing_workspace_and_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("no", encoding="utf-8")

    token = current_tool_context.set(
        ToolContext(
            artifact_media_root=str(tmp_path / "media"),
            artifact_session_id="session-1",
            session_key="agent:main:webchat:session-1",
        )
    )
    try:
        with pytest.raises(ToolError):
            await publish_artifact(path=str(outside))
    finally:
        current_tool_context.reset(token)

    token = current_tool_context.set(
        ToolContext(
            workspace_dir=str(workspace),
            artifact_media_root=str(tmp_path / "media"),
            artifact_session_id="session-1",
            session_key="agent:main:webchat:session-1",
        )
    )
    try:
        with pytest.raises(ToolError):
            await publish_artifact(path="../outside.txt")
    finally:
        current_tool_context.reset(token)
