from __future__ import annotations

import os
import subprocess
import sys

from opensquilla.tools.builtin import load_builtin_tools
from opensquilla.tools.registry import ToolRegistry, get_default_registry


def test_load_builtin_tools_registers_default_builtin_surface() -> None:
    names = set(load_builtin_tools())
    registry = get_default_registry()

    assert {"read_file", "exec_command", "sessions_spawn", "web_fetch"} <= names
    assert registry.get("read_file") is not None
    assert registry.get("exec_command") is not None


def test_load_builtin_tools_can_copy_builtin_surface_to_custom_registry() -> None:
    registry = ToolRegistry()

    names = set(load_builtin_tools(registry))

    assert {"read_file", "exec_command", "sessions_spawn", "web_fetch"} <= names
    assert registry.get("read_file") is not None
    assert registry.get("exec_command") is not None
    assert registry.get("memory_save") is None


def test_scheduler_routing_import_does_not_drop_session_tools() -> None:
    script = """
import opensquilla.scheduler.routing
from opensquilla.tools.registry import get_default_registry
registry = get_default_registry()
missing = [
    name
    for name in ("sessions_spawn", "sessions_send", "sessions_yield", "session_status")
    if registry.get(name) is None
]
assert missing == [], missing
"""

    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        cwd=".",
        env=env,
    )
