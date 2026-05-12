from __future__ import annotations

from typer.testing import CliRunner

from opensquilla.cli.main import app


def test_mcp_server_cli_help_exposes_real_bridge_without_benchmark_mode() -> None:
    result = CliRunner().invoke(app, ["mcp-server", "run", "--help"])

    assert result.exit_code == 0
    assert "--gateway" in result.output
    assert "stdio" in result.output.lower()
    assert "--transport" not in result.output
    assert "--host" not in result.output
    assert "--port" not in result.output
    assert "--allow-nonlocal" not in result.output
    assert "benchmark" not in result.output.lower()
    assert "mock" not in result.output.lower()
