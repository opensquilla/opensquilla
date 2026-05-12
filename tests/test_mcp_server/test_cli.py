from __future__ import annotations

import click
from typer.testing import CliRunner

from opensquilla.cli.main import app


def test_mcp_server_cli_help_exposes_real_bridge_without_benchmark_mode() -> None:
    result = CliRunner().invoke(app, ["mcp-server", "run", "--help"])
    output = click.unstyle(result.output)

    assert result.exit_code == 0
    assert "--gateway" in output
    assert "stdio" in output.lower()
    assert "--transport" not in output
    assert "--host" not in output
    assert "--port" not in output
    assert "--allow-nonlocal" not in output
    assert "benchmark" not in output.lower()
    assert "mock" not in output.lower()
