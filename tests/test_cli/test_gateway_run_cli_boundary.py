from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATEWAY_CMD = ROOT / "src" / "opensquilla" / "cli" / "gateway_cmd.py"
GATEWAY_WORKFLOWS = ROOT / "src" / "opensquilla" / "cli" / "gateway_run_workflows.py"
GATEWAY_PRESENTERS = ROOT / "src" / "opensquilla" / "cli" / "gateway_run_presenters.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} was not found")


def _referenced_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
    return names


def _imported_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def test_run_gateway_delegates_to_gateway_run_workflow() -> None:
    tree = _tree(GATEWAY_CMD)
    run_gateway = _function(tree, "run_gateway")
    calls = [
        node
        for node in ast.walk(run_gateway)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run_gateway_for_cli"
    ]

    assert calls, "run_gateway should delegate to gateway_run_workflows.run_gateway_for_cli"
    assert not [
        node
        for node in ast.walk(run_gateway)
        if isinstance(node, (ast.AsyncFunctionDef, ast.Try))
    ], "run_gateway should keep only Typer option declaration and workflow delegation"


def test_gateway_cmd_no_longer_owns_gateway_run_dependencies() -> None:
    tree = _tree(GATEWAY_CMD)
    run_gateway = _function(tree, "run_gateway")
    prohibited = {
        "start_gateway_server",
        "SubscriptionManager",
        "GatewayConfig",
        "is_public_bind",
        "resolve_listen_address",
        "asyncio",
    }

    assert _imported_names(tree).isdisjoint(prohibited)
    assert _referenced_names(run_gateway).isdisjoint(prohibited)


def test_gateway_run_modules_own_workflow_and_presenter_dependencies() -> None:
    workflow_tree = _tree(GATEWAY_WORKFLOWS)
    presenter_tree = _tree(GATEWAY_PRESENTERS)

    workflow_imports = _imported_names(workflow_tree)
    assert {
        "asyncio",
        "start_gateway_server",
        "GatewayConfig",
        "resolve_listen_address",
        "SubscriptionManager",
    } <= workflow_imports

    presenter_imports = _imported_names(presenter_tree)
    assert {"console", "default_opensquilla_home", "is_public_bind"} <= presenter_imports

    presenter_source = GATEWAY_PRESENTERS.read_text(encoding="utf-8")
    assert "gateway is bound to a wildcard address" in presenter_source
    assert "reachable from every interface" in presenter_source
    assert "auth.mode=none + wildcard bind = LAN-open" in presenter_source
    assert "Bypass / elevated mode remains owner-only" in presenter_source


def test_gateway_run_presenter_preserves_startup_guidance_and_public_bind_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.cli import gateway_run_presenters

    printed: list[str] = []
    monkeypatch.setattr(gateway_run_presenters.console, "print", printed.append)
    monkeypatch.setattr(
        gateway_run_presenters,
        "default_opensquilla_home",
        lambda: Path("/tmp/opensquilla-home"),
    )

    config = SimpleNamespace(auth=SimpleNamespace(mode="none"))

    guidance = gateway_run_presenters.gateway_startup_guidance("0.0.0.0", 18790)
    gateway_run_presenters.render_gateway_startup(host="0.0.0.0", port=18790, config=config)
    gateway_run_presenters.render_gateway_stopped()

    assert guidance == (
        "[bold]Web UI:[/bold] http://0.0.0.0:18790/control/",
        "[bold]API base:[/bold] http://0.0.0.0:18790",
        "[bold]Debug log:[/bold] /tmp/opensquilla-home/logs/debug.log",
        "[dim]Keep this terminal open. Press Ctrl+C to stop.[/dim]",
    )
    assert printed[0] == (
        "[bold green]Starting OpenSquilla gateway[/bold green] on [red]0.0.0.0[/red]:18790"
    )
    assert list(guidance) == printed[1:5]
    assert (
        "[yellow]WARNING: gateway is bound to a wildcard address - "
        "reachable from every interface.[/yellow]"
    ) in printed
    assert any("auth.mode=none + wildcard bind = LAN-open" in line for line in printed)
    assert any("Bypass / elevated mode remains owner-only" in line for line in printed)
    assert printed[-1] == "\n[yellow]Gateway stopped.[/yellow]"


def test_gateway_run_workflow_builds_config_with_listen_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.cli import gateway_run_workflows

    events: list[tuple[str, object]] = []

    class FakeConfig:
        auth = SimpleNamespace(mode="token")

        def model_copy(self, *, update: dict[str, object]) -> SimpleNamespace:
            events.append(("model_copy", update))
            return SimpleNamespace(auth=self.auth, **update)

    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", "gateway.toml")
    monkeypatch.setattr(
        gateway_run_workflows.GatewayConfig,
        "load",
        staticmethod(lambda path: events.append(("load", path)) or FakeConfig()),
    )
    monkeypatch.setattr(
        gateway_run_workflows,
        "resolve_listen_address",
        lambda explicit: events.append(("resolve", explicit)) or "0.0.0.0",
    )

    config = gateway_run_workflows.build_gateway_run_config(
        port=18888,
        bind="127.0.0.1",
        listen="0.0.0.0",
        debug=True,
    )

    assert events == [
        ("resolve", "0.0.0.0"),
        ("load", "gateway.toml"),
        ("model_copy", {"host": "0.0.0.0", "port": 18888, "debug": True}),
    ]
    assert config.host == "0.0.0.0"
    assert config.port == 18888
    assert config.debug is True


@pytest.mark.asyncio
async def test_gateway_run_workflow_starts_server_with_subscription_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.cli import gateway_run_workflows

    config = SimpleNamespace(host="127.0.0.1", port=18790, debug=False)
    events: list[tuple[str, object]] = []

    class FakeSubscriptionManager:
        def __init__(self) -> None:
            events.append(("subscription_manager", self))

    class FakeServer:
        def __init__(self) -> None:
            self._task = asyncio.create_task(asyncio.sleep(0))
            self.closed_with: str | None = None

        async def close(self, reason: str) -> None:
            self.closed_with = reason
            events.append(("close", reason))

    async def fake_start_gateway_server(**kwargs: object) -> FakeServer:
        events.append(("start_gateway_server", kwargs))
        return FakeServer()

    monkeypatch.setattr(gateway_run_workflows, "SubscriptionManager", FakeSubscriptionManager)
    monkeypatch.setattr(gateway_run_workflows, "start_gateway_server", fake_start_gateway_server)

    await gateway_run_workflows.run_gateway_server(config)

    start_event = events[1]
    assert start_event[0] == "start_gateway_server"
    assert start_event[1]["config"] is config
    assert isinstance(start_event[1]["subscription_manager"], FakeSubscriptionManager)
    assert start_event[1]["run"] is True
    assert ("close", "keyboard_interrupt") not in events


def test_gateway_run_workflow_keyboard_interrupt_renders_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.cli import gateway_run_workflows

    stopped: list[bool] = []
    config = SimpleNamespace(host="127.0.0.1", port=18790, debug=False)
    rendered: list[tuple[str, int, object]] = []

    monkeypatch.setattr(gateway_run_workflows, "build_gateway_run_config", lambda **_: config)
    monkeypatch.setattr(
        gateway_run_workflows.gateway_run_presenters,
        "render_gateway_startup",
        lambda *, host, port, config: rendered.append((host, port, config)),
    )
    monkeypatch.setattr(
        gateway_run_workflows.gateway_run_presenters,
        "render_gateway_stopped",
        lambda: stopped.append(True),
    )

    def fake_asyncio_run(coro: object) -> None:
        assert hasattr(coro, "close")
        coro.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(gateway_run_workflows.asyncio, "run", fake_asyncio_run)

    gateway_run_workflows.run_gateway_for_cli(
        port=18790,
        bind="127.0.0.1",
        listen="",
        debug=False,
    )

    assert rendered == [("127.0.0.1", 18790, config)]
    assert stopped == [True]
