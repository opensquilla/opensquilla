"""Shared fixtures for the code-task test package."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_agent_config_discovery(monkeypatch, tmp_path_factory):
    """Keep subagent-config assembly hermetic and offline by default.

    ``runner.solve`` and ``LocalAdapter.run`` now assemble the per-run
    subagent config from the operator's effective config. The repo root is a
    documented config location (``./opensquilla.toml``) and the global
    conftest strips provider keys but not ``OPENSQUILLA_GATEWAY_CONFIG_PATH``,
    so without this guard a developer's real config/env would leak into the
    merged payload (and their credentials into per-run artifacts). Point
    discovery at a missing explicit path — the sole candidate, so neither the
    cwd nor the home config is consulted. Tests that exercise inheritance
    override this with their own ``monkeypatch.setenv``.
    """
    missing = tmp_path_factory.mktemp("no-operator-config") / "config.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(missing))
    monkeypatch.delenv("OPENSQUILLA_CODETASK_AGENT_CONFIG", raising=False)
    monkeypatch.delenv("OPENSQUILLA_LLM_API_KEY", raising=False)
