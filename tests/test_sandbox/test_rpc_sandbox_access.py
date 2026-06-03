from __future__ import annotations

from types import SimpleNamespace

import pytest


class _SessionManager:
    def __init__(self):
        self.node = SimpleNamespace(
            session_key="agent:main:webchat:abc",
            agent_id="main",
            origin=None,
        )
        self.sessions = {self.node.session_key: self.node}
        self.created: list[str] = []

    async def get_session(self, session_key: str):
        return self.sessions.get(session_key)

    async def get_or_create(self, session_key: str, agent_id: str = "main", **kwargs):
        existing = self.sessions.get(session_key)
        if existing is not None:
            return existing, False
        node = SimpleNamespace(
            session_key=session_key,
            agent_id=agent_id,
            origin=None,
            **kwargs,
        )
        self.sessions[session_key] = node
        self.created.append(session_key)
        return node, True

    async def update(self, session_key: str, **fields):
        node = self.sessions[session_key]
        for key, value in fields.items():
            setattr(node, key, value)
        return node


def _ctx(
    manager: _SessionManager,
    *,
    is_owner: bool = True,
    run_mode: str = "standard",
    sandbox: bool = True,
    security_grading: bool = True,
    permissions_default_mode: str = "off",
):
    from opensquilla.gateway.auth import Principal
    from opensquilla.gateway.rpc import RpcContext

    config = SimpleNamespace(
        workspace_dir="/tmp/ws",
        agents=[],
        sandbox=SimpleNamespace(
            run_mode=run_mode,
            sandbox=sandbox,
            security_grading=security_grading,
            backend="noop",
            network_default="proxy_allowlist",
        ),
        permissions=SimpleNamespace(default_mode=permissions_default_mode),
    )
    return RpcContext(
        conn_id="c",
        principal=Principal(
            role="operator",
            scopes=frozenset(["operator.read", "operator.write"]),
            is_owner=is_owner,
            authenticated=True,
        ),
        session_manager=manager,
        config=config,
    )


@pytest.fixture(autouse=True)
def _reset_resolved_overlays() -> None:
    from opensquilla.sandbox.escalation import reset_resolved_run_context_overlays

    reset_resolved_run_context_overlays()
    yield
    reset_resolved_run_context_overlays()


@pytest.mark.asyncio
async def test_rpc_add_domain_returns_updated_context() -> None:
    from opensquilla.gateway.rpc_sandbox import _handle_sandbox_domain_add

    manager = _SessionManager()

    result = await _handle_sandbox_domain_add(
        {
            "sessionKey": manager.node.session_key,
            "domain": "https://pypi.org/simple",
            "scope": "workspace",
        },
        _ctx(manager),
    )

    assert result["domains"] == [
        {"domain": "pypi.org", "scope": "workspace", "source": "manual"}
    ]


@pytest.mark.asyncio
async def test_rpc_add_mount_rejects_non_owner() -> None:
    from opensquilla.gateway.rpc import RpcHandlerError
    from opensquilla.gateway.rpc_sandbox import _handle_sandbox_mount_add

    manager = _SessionManager()

    with pytest.raises(RpcHandlerError, match="requires owner principal"):
        await _handle_sandbox_mount_add(
            {"sessionKey": manager.node.session_key, "path": "/tmp/ws/extras"},
            _ctx(manager, is_owner=False),
        )

    assert manager.node.origin is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "params"),
    [
        ("_handle_sandbox_mount_add", {}),
        ("_handle_sandbox_mount_add", {"path": ""}),
        ("_handle_sandbox_mount_add", {"path": "   "}),
        ("_handle_sandbox_mount_remove", {}),
        ("_handle_sandbox_mount_remove", {"path": ""}),
        ("_handle_sandbox_mount_remove", {"path": "   "}),
    ],
)
async def test_rpc_mount_mutations_require_path_without_mutating_origin(
    handler_name: str,
    params: dict[str, str],
) -> None:
    import opensquilla.gateway.rpc_sandbox as rpc_sandbox

    manager = _SessionManager()
    handler = getattr(rpc_sandbox, handler_name)

    with pytest.raises(ValueError, match="params.path is required"):
        await handler(
            {"sessionKey": manager.node.session_key, **params},
            _ctx(manager),
        )

    assert manager.node.origin is None
    assert manager.created == []


@pytest.mark.asyncio
async def test_rpc_mutation_rejects_whitespace_session_key_without_creating_session() -> None:
    from opensquilla.gateway.rpc_sandbox import _handle_sandbox_mount_add

    manager = _SessionManager()

    with pytest.raises(ValueError, match="params.sessionKey is required"):
        await _handle_sandbox_mount_add(
            {"sessionKey": "   ", "path": "/tmp/ws/extras"},
            _ctx(manager),
        )

    assert "   " not in manager.sessions
    assert manager.created == []


@pytest.mark.asyncio
async def test_rpc_run_context_get_includes_bundles_and_temporary_grants() -> None:
    from opensquilla.gateway.rpc_sandbox import _handle_sandbox_run_context_get
    from opensquilla.sandbox.run_context import (
        PackageBundleGrant,
        RunContext,
        TemporaryGrant,
        persist_run_context,
    )
    from opensquilla.sandbox.run_mode import RunMode

    manager = _SessionManager()
    await persist_run_context(
        manager,
        manager.node.session_key,
        RunContext(
            run_mode=RunMode.STANDARD,
            workspace="/tmp/ws",
            bundles=(PackageBundleGrant(bundle_id="python-package-install"),),
            temporary_grants=(
                TemporaryGrant(
                    kind="domain",
                    value="pypi.org",
                    fingerprint="abc123",
                ),
            ),
            source="saved",
        ),
    )

    result = await _handle_sandbox_run_context_get(
        {"sessionKey": manager.node.session_key},
        _ctx(manager),
    )

    assert result["bundles"] == [
        {
            "bundle_id": "python-package-install",
            "scope": "workspace",
            "source": "manual",
        }
    ]
    assert result["temporaryGrants"] == [
        {
            "kind": "domain",
            "value": "pypi.org",
            "fingerprint": "abc123",
            "expires_after": "once",
        }
    ]


@pytest.mark.asyncio
async def test_rpc_mount_remove_updates_resolved_overlay_for_current_tool_mounts() -> None:
    from opensquilla.gateway.rpc_sandbox import _handle_sandbox_mount_remove
    from opensquilla.sandbox.escalation import current_tool_mounts, remember_resolved_run_context
    from opensquilla.sandbox.run_context import MountGrant, RunContext
    from opensquilla.sandbox.run_mode import RunMode
    from opensquilla.tools.types import CallerKind, ToolContext, current_tool_context

    manager = _SessionManager()
    ctx = _ctx(manager)

    remembered = RunContext(
        run_mode=RunMode.STANDARD,
        workspace="/tmp/ws",
        mounts=(MountGrant(path="/tmp/ws/extras", access="ro", scope="chat"),),
        source="saved",
    )
    remember_resolved_run_context(
        manager.node.session_key,
        "/tmp/ws",
        remembered,
        session_manager=manager,
        config=ctx.config,
    )
    manager.node.origin = remembered.to_origin_payload() and {
        "sandbox_run_context": remembered.to_origin_payload()
    }
    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir="/tmp/ws",
            session_key=manager.node.session_key,
            sandbox_mounts=[{"path": "/tmp/ws/extras", "access": "ro"}],
            sandbox_run_context=remembered,
        )
    )
    try:
        assert current_tool_mounts() == [{"path": "/tmp/ws/extras", "access": "ro"}]

        result = await _handle_sandbox_mount_remove(
            {"sessionKey": manager.node.session_key, "path": "/tmp/ws/extras"},
            ctx,
        )
    finally:
        current_tool_context.reset(token)

    assert result["mounts"] == []

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir="/tmp/ws",
            session_key=manager.node.session_key,
            sandbox_mounts=[{"path": "/tmp/ws/extras", "access": "ro"}],
            sandbox_run_context=remembered,
        )
    )
    try:
        assert current_tool_mounts() == []
    finally:
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_rpc_domain_remove_updates_resolved_overlay_for_current_tool_context() -> None:
    from opensquilla.gateway.rpc_sandbox import _handle_sandbox_domain_remove
    from opensquilla.sandbox.escalation import current_tool_run_context, remember_resolved_run_context
    from opensquilla.sandbox.network_guard import decide_network_access
    from opensquilla.sandbox.run_context import DomainGrant, RunContext
    from opensquilla.sandbox.run_mode import RunMode
    from opensquilla.tools.types import CallerKind, ToolContext, current_tool_context

    manager = _SessionManager()
    ctx = _ctx(manager)
    remembered = RunContext(
        run_mode=RunMode.STANDARD,
        workspace="/tmp/ws",
        domains=(DomainGrant(domain="example.com", scope="chat"),),
        source="saved",
    )
    remember_resolved_run_context(
        manager.node.session_key,
        "/tmp/ws",
        remembered,
        session_manager=manager,
        config=ctx.config,
    )
    manager.node.origin = {"sandbox_run_context": remembered.to_origin_payload()}
    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir="/tmp/ws",
            session_key=manager.node.session_key,
            sandbox_run_context=remembered,
        )
    )
    try:
        merged = current_tool_run_context()
        assert merged is not None
        assert decide_network_access("example.com", merged).status == "allow"

        result = await _handle_sandbox_domain_remove(
            {"sessionKey": manager.node.session_key, "domain": "example.com"},
            ctx,
        )
    finally:
        current_tool_context.reset(token)

    assert result["domains"] == []

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir="/tmp/ws",
            session_key=manager.node.session_key,
            sandbox_run_context=remembered,
        )
    )
    try:
        merged = current_tool_run_context()
        assert merged is not None
        assert decide_network_access("example.com", merged).status == "ask"
    finally:
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_rpc_sandbox_status_reports_backend_managed_network_and_run_mode() -> None:
    from opensquilla.gateway.rpc_sandbox import _handle_sandbox_status

    manager = _SessionManager()

    result = await _handle_sandbox_status({}, _ctx(manager))

    assert result["run_mode"] == "standard"
    assert result["run_mode_label"] == "Standard-Sandbox"
    assert result["execution_target"] == "sandbox"
    assert result["posture"] == "standard"
    assert result["backend"] == "noop"
    assert result["managed_network"] == "ready"
    assert result["sandbox"] == {
        "sandbox": True,
        "security_grading": True,
        "network_default": "proxy_allowlist",
    }
    catalog_by_id = {
        bundle["bundle_id"]: set(bundle["domains"])
        for bundle in result["bundle_catalog"]
    }
    expected_catalog_subsets = {
        "python-package-install": {
            "pypi.org",
            "files.pythonhosted.org",
            "pypi.python.org",
            "bootstrap.pypa.io",
        },
        "node-package-install": {
            "registry.npmjs.org",
            "registry.yarnpkg.com",
            "yarnpkg.com",
            "nodejs.org",
        },
        "rust-package-install": {
            "crates.io",
            "static.crates.io",
            "index.crates.io",
            "github.com",
            "objects.githubusercontent.com",
        },
        "go-package-install": {
            "proxy.golang.org",
            "sum.golang.org",
            "go.dev",
            "golang.org",
            "storage.googleapis.com",
        },
        "github-default": {
            "github.com",
            "api.github.com",
            "raw.githubusercontent.com",
            "codeload.github.com",
            "objects.githubusercontent.com",
        },
    }
    for bundle_id, expected_domains in expected_catalog_subsets.items():
        assert bundle_id in catalog_by_id
        assert expected_domains.issubset(catalog_by_id[bundle_id])
    assert result["permissions"] == {"default_mode": "off"}


@pytest.mark.asyncio
async def test_rpc_sandbox_status_reports_full_host_access_without_managed_controls() -> None:
    from opensquilla.gateway.rpc_sandbox import _handle_sandbox_status

    result = await _handle_sandbox_status(
        {},
        _ctx(
            _SessionManager(),
            run_mode="full",
            sandbox=False,
            security_grading=False,
            permissions_default_mode="full",
        ),
    )

    assert result["run_mode"] == "full"
    assert result["run_mode_label"] == "Full Host Access"
    assert result["execution_target"] == "host"
    assert result["posture"] == "full"
    assert result["managed_network"] == "inactive"


@pytest.mark.asyncio
async def test_rpc_sandbox_explain_returns_status_messages_and_optional_context() -> None:
    from opensquilla.gateway.rpc_sandbox import _handle_sandbox_explain
    from opensquilla.sandbox.run_context import RunContext, persist_run_context
    from opensquilla.sandbox.run_mode import RunMode

    manager = _SessionManager()
    await persist_run_context(
        manager,
        manager.node.session_key,
        RunContext(run_mode=RunMode.TRUSTED, workspace="/tmp/ws", source="saved"),
    )

    result = await _handle_sandbox_explain(
        {"sessionKey": manager.node.session_key},
        _ctx(manager),
    )

    assert result["status"]["run_mode"] == "standard"
    assert result["runContext"]["runMode"] == "trusted"
    assert result["messages"] == [
        {"kind": "run_mode", "message": "Run mode is standard."},
        {
            "kind": "managed_network",
            "message": "Managed network allowlist is ready.",
        },
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "params"),
    [
        ("_handle_sandbox_workspace_set", {"workspace": "/tmp/ws/project"}),
        ("_handle_sandbox_mount_remove", {"path": "/tmp/ws/extras"}),
        ("_handle_sandbox_domain_add", {"domain": "pypi.org"}),
        ("_handle_sandbox_domain_remove", {"domain": "pypi.org"}),
        ("_handle_sandbox_bundle_enable", {"bundleId": "python-package-install"}),
        ("_handle_sandbox_bundle_disable", {"bundleId": "python-package-install"}),
    ],
)
async def test_rpc_sandbox_mutations_reject_non_owner(
    handler_name: str,
    params: dict[str, str],
) -> None:
    from opensquilla.gateway.rpc import RpcHandlerError
    import opensquilla.gateway.rpc_sandbox as rpc_sandbox

    manager = _SessionManager()
    handler = getattr(rpc_sandbox, handler_name)

    with pytest.raises(RpcHandlerError, match="requires owner principal"):
        await handler(
            {"sessionKey": manager.node.session_key, **params},
            _ctx(manager, is_owner=False),
        )

    assert manager.node.origin is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "params", "message"),
    [
        ("_handle_sandbox_domain_add", {}, "params.domain is required"),
        ("_handle_sandbox_domain_remove", {"domain": ""}, "params.domain is required"),
        ("_handle_sandbox_bundle_enable", {}, "params.bundleId is required"),
        (
            "_handle_sandbox_bundle_enable",
            {"bundleId": "unknown-package-install"},
            "unknown_package_bundle",
        ),
        (
            "_handle_sandbox_bundle_disable",
            {"bundle_id": "   "},
            "params.bundleId is required",
        ),
        ("_handle_sandbox_workspace_set", {}, "params.workspace is required"),
    ],
)
async def test_rpc_sandbox_invalid_params_do_not_create_missing_session(
    handler_name: str,
    params: dict[str, str],
    message: str,
) -> None:
    import opensquilla.gateway.rpc_sandbox as rpc_sandbox

    manager = _SessionManager()
    missing_session_key = "agent:main:webchat:missing"
    handler = getattr(rpc_sandbox, handler_name)

    with pytest.raises(ValueError, match=message):
        await handler(
            {"sessionKey": missing_session_key, **params},
            _ctx(manager),
        )

    assert missing_session_key not in manager.sessions
    assert manager.created == []


@pytest.mark.asyncio
async def test_rpc_sandbox_path_pick_validates_workspace_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import opensquilla.gateway.rpc_sandbox as rpc_sandbox

    manager = _SessionManager()
    monkeypatch.setattr(rpc_sandbox, "_pick_directory_path", lambda initial_dir=None: "/etc")

    with pytest.raises(ValueError, match="sensitive_path"):
        await rpc_sandbox._handle_sandbox_path_pick(
            {
                "sessionKey": manager.node.session_key,
                "kind": "workspace",
            },
            _ctx(manager),
        )


@pytest.mark.asyncio
async def test_rpc_sandbox_path_pick_returns_valid_mount_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import opensquilla.gateway.rpc_sandbox as rpc_sandbox

    manager = _SessionManager()
    selected = tmp_path / "external"
    selected.mkdir()
    monkeypatch.setattr(
        rpc_sandbox,
        "_pick_directory_path",
        lambda initial_dir=None: str(selected),
    )

    result = await rpc_sandbox._handle_sandbox_path_pick(
        {
            "sessionKey": manager.node.session_key,
            "kind": "mount",
            "access": "ro",
        },
        _ctx(manager),
    )

    assert result == {"path": str(selected), "kind": "mount"}


@pytest.mark.asyncio
async def test_rpc_sandbox_path_list_returns_parent_directory_entries(
    tmp_path,
) -> None:
    import opensquilla.gateway.rpc_sandbox as rpc_sandbox

    manager = _SessionManager()
    parent = tmp_path / "parent"
    child = parent / "child"
    sibling = parent / "sibling"
    file_entry = parent / "notes.txt"
    child.mkdir(parents=True)
    sibling.mkdir()
    file_entry.write_text("not a directory", encoding="utf-8")
    handler = getattr(rpc_sandbox, "_handle_sandbox_path_list", None)

    assert callable(handler)

    result = await handler(
        {
            "sessionKey": manager.node.session_key,
            "path": str(child),
        },
        _ctx(manager),
    )

    assert result["path"] == str(child)
    assert result["parentPath"] == str(parent)
    entries_by_path = {entry["path"]: entry for entry in result["entries"]}
    assert {
        str(child),
        str(sibling),
        str(file_entry),
    }.issubset(entries_by_path)

    assert entries_by_path[str(child)]["name"] == "child"
    assert entries_by_path[str(child)]["kind"] == "directory"
    assert entries_by_path[str(child)]["selectable"] is True
    assert entries_by_path[str(sibling)]["name"] == "sibling"
    assert entries_by_path[str(sibling)]["kind"] == "directory"
    assert entries_by_path[str(sibling)]["selectable"] is True
    assert entries_by_path[str(file_entry)]["name"] == "notes.txt"
    assert entries_by_path[str(file_entry)]["kind"] == "file"
    assert entries_by_path[str(file_entry)]["selectable"] is True


@pytest.mark.asyncio
async def test_rpc_sandbox_path_list_requires_owner(tmp_path) -> None:
    from opensquilla.gateway.rpc import RpcHandlerError
    from opensquilla.gateway.rpc_sandbox import _handle_sandbox_path_list

    manager = _SessionManager()
    target = tmp_path / "target"
    target.mkdir()

    with pytest.raises(RpcHandlerError, match="requires owner principal"):
        await _handle_sandbox_path_list(
            {
                "sessionKey": manager.node.session_key,
                "path": str(target),
            },
            _ctx(manager, is_owner=False),
        )


@pytest.mark.asyncio
async def test_rpc_sandbox_path_list_supports_parent_row_and_child_drilldown(
    tmp_path,
) -> None:
    from opensquilla.gateway.rpc_sandbox import _handle_sandbox_path_list

    manager = _SessionManager()
    parent = tmp_path / "parent"
    child = parent / "child"
    grandchild = child / "grandchild"
    child_file = child / "inside.txt"
    child.mkdir(parents=True)
    grandchild.mkdir()
    child_file.write_text("inside", encoding="utf-8")

    result = await _handle_sandbox_path_list(
        {
            "sessionKey": manager.node.session_key,
            "path": str(child),
            "browseChildren": True,
        },
        _ctx(manager),
    )

    assert result["path"] == str(child)
    assert result["parentPath"] == str(child)
    entries_by_name = {entry["name"]: entry for entry in result["entries"]}
    assert entries_by_name[".."] == {
        "name": "..",
        "path": str(parent),
        "kind": "directory",
        "selectable": True,
    }
    assert entries_by_name["grandchild"]["path"] == str(grandchild)
    assert entries_by_name["grandchild"]["kind"] == "directory"
    assert entries_by_name["grandchild"]["selectable"] is True
    assert entries_by_name["inside.txt"]["path"] == str(child_file)
    assert entries_by_name["inside.txt"]["kind"] == "file"
    assert entries_by_name["inside.txt"]["selectable"] is True


@pytest.mark.asyncio
async def test_rpc_sandbox_path_browser_selection_is_validated_on_workspace_save(
    tmp_path,
) -> None:
    from opensquilla.gateway.rpc_sandbox import _handle_sandbox_workspace_set

    manager = _SessionManager()
    selected = tmp_path / ".aws" / "credentials"
    selected.parent.mkdir()
    selected.write_text("secret", encoding="utf-8")

    with pytest.raises(ValueError, match="sensitive_path"):
        await _handle_sandbox_workspace_set(
            {
                "sessionKey": manager.node.session_key,
                "workspace": str(selected),
            },
            _ctx(manager),
        )

    assert manager.node.origin is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "params", "message"),
    [
        ("_handle_sandbox_domain_add", {"domain": "127.0.0.1"}, "ip_literal"),
        ("_handle_sandbox_domain_remove", {"domain": "*.com"}, "broad_wildcard"),
        ("_handle_sandbox_workspace_set", {"workspace": "/"}, "sensitive_path"),
        (
            "_handle_sandbox_workspace_set",
            {"workspacePath": "/tmp/ws/.aws/credentials"},
            "sensitive_path",
        ),
        ("_handle_sandbox_mount_add", {"path": "/etc/shadow"}, "sensitive_path"),
        ("_handle_sandbox_mount_remove", {"path": "/"}, "sensitive_path"),
    ],
)
async def test_rpc_sandbox_semantic_validation_does_not_create_missing_session(
    handler_name: str,
    params: dict[str, str],
    message: str,
) -> None:
    import opensquilla.gateway.rpc_sandbox as rpc_sandbox

    manager = _SessionManager()
    missing_session_key = "agent:main:webchat:missing"
    handler = getattr(rpc_sandbox, handler_name)

    with pytest.raises(ValueError, match=message):
        await handler(
            {"sessionKey": missing_session_key, **params},
            _ctx(manager),
        )

    assert missing_session_key not in manager.sessions
    assert manager.created == []
