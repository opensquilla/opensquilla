from __future__ import annotations

from opensquilla import commands
from opensquilla.engine import commands as engine_commands


def test_engine_commands_reexports_shared_registry_objects() -> None:
    assert engine_commands.DEFAULT_REGISTRY is commands.DEFAULT_REGISTRY
    assert engine_commands.CommandDef is commands.CommandDef
    assert engine_commands.Surface is commands.Surface
