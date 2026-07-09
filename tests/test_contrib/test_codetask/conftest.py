"""Shared fixtures for the code-task test package."""

import pytest

from opensquilla.contrib.codetask import preflight as _preflight
from opensquilla.onboarding.probe import ProviderProbeResult


@pytest.fixture(autouse=True)
def _stub_provider_probe(monkeypatch):
    """Make the credential preflight offline-safe by default.

    The default suite runs keyless (the global conftest strips provider keys),
    so a real probe would classify every run as auth_invalid and block it
    before clone. Stub the network round-trip to succeed; tests that exercise
    the preflight override this with their own probe result.
    """

    async def _ok(*, provider_id, model, **_kw):
        return ProviderProbeResult(ok=True, provider_id=provider_id, model=model)

    monkeypatch.setattr(_preflight, "probe_llm_provider", _ok)


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
