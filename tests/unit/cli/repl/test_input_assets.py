from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from typing import Any

import pytest


def test_input_assets_has_no_raw_prompt_application_dependency(monkeypatch) -> None:
    monkeypatch.delitem(
        sys.modules,
        "opensquilla.cli.repl.input_assets",
        raising=False,
    )

    original_import = __import__

    def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        if name == "prompt_toolkit" or name.startswith("prompt_toolkit."):
            raise AssertionError(f"input assets imported prompt_toolkit via {name}")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _guarded_import)

    module = importlib.import_module("opensquilla.cli.repl.input_assets")
    source = inspect.getsource(module)

    assert "ChatApplication" not in source


def test_input_assets_wrap_existing_file_and_path_helpers(tmp_path: Path) -> None:
    from opensquilla.cli.repl import input_assets

    csv_path = tmp_path / "data.csv"
    csv_path.write_text("a,b\n1,2\n", encoding="utf-8")
    png_path = tmp_path / "screen.png"
    png_path.write_bytes(b"\x89PNG\r\n\x1a\npayload")

    file_prompt, file_attachments = input_assets.file_prompt_and_attachments(
        f"/file {csv_path} summarize",
        upload_callable=None,
    )
    image_prompt, image_attachments = input_assets.image_prompt_and_attachments(
        f"/image {png_path} describe",
    )
    path_prompt, path_attachments = input_assets.path_prompt_and_attachments(
        f"/path {csv_path} inspect",
    )

    assert file_prompt == "summarize"
    assert file_attachments[0]["type"] == "text/csv"
    assert input_assets.image_prompt_from_command(f"/image {png_path} describe") == "describe"
    assert image_prompt == "describe"
    assert image_attachments[0]["type"] == "image/png"
    assert "inspect" in path_prompt
    assert str(csv_path.resolve(strict=False)) in path_prompt
    assert path_attachments == []


def test_gateway_slash_adapter_uses_input_bridge_for_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.cli.repl import slash_adapter

    captured: dict[str, Any] = {}

    def fake_path_prompt_and_attachments(command: str) -> tuple[str, list[dict[str, Any]]]:
        captured["command"] = command
        return "inspect from input assets", []

    monkeypatch.setattr(
        slash_adapter._input_bridge,
        "path_prompt_and_attachments",
        fake_path_prompt_and_attachments,
    )

    prompt, attachments = slash_adapter.path_prompt_and_attachments("/path /repo inspect")

    assert captured["command"] == "/path /repo inspect"
    assert prompt == "inspect from input assets"
    assert attachments == []


def test_turn_bridge_default_image_builder_uses_input_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.cli.repl import turn_bridge
    from opensquilla.cli.tui import turn_stream_defaults

    captured: dict[str, str] = {}

    def fake_image_prompt_and_attachments(command: str) -> tuple[str, list[dict[str, str]]]:
        captured["command"] = command
        return "describe via input assets", [{"type": "image/png", "data": "x", "name": "x.png"}]

    monkeypatch.setattr(
        turn_stream_defaults._input_bridge,
        "image_prompt_and_attachments",
        fake_image_prompt_and_attachments,
    )

    prompt, attachments = turn_bridge.image_prompt_and_attachments("/image x.png describe")

    assert captured["command"] == "/image x.png describe"
    assert prompt == "describe via input assets"
    assert attachments == [{"type": "image/png", "data": "x", "name": "x.png"}]


def test_standalone_slash_adapter_uses_input_bridge_for_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.cli.repl import standalone_slash_adapter

    captured: dict[str, Any] = {}

    def fake_path_prompt_and_attachments(command: str) -> tuple[str, list[dict[str, Any]]]:
        captured["command"] = command
        return "standalone inspect from input bridge", []

    monkeypatch.setattr(
        standalone_slash_adapter._input_bridge,
        "path_prompt_and_attachments",
        fake_path_prompt_and_attachments,
    )

    prompt, attachments = standalone_slash_adapter._path_prompt_and_attachments(
        "/path /repo inspect"
    )

    assert captured["command"] == "/path /repo inspect"
    assert prompt == "standalone inspect from input bridge"
    assert attachments == []
