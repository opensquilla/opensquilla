"""End-to-end check that the advertised search recovery one-liner is safe.

``onboard status`` and the next-steps guidance advertise
``opensquilla onboard configure search --search-provider duckduckgo`` as the
headless recovery path. Re-running it on a config that already carries
operator-tuned global search settings must keep those settings (keep-current
semantics for every omitted flag), otherwise the recovery advice itself
resets the operator's configuration.
"""

from __future__ import annotations

from typer.testing import CliRunner

from opensquilla.cli.main import app
from opensquilla.onboarding.config_store import load_config
from opensquilla.onboarding.next_steps import headless_setup_command

runner = CliRunner()


def test_advertised_search_recovery_one_liner_keeps_saved_settings(tmp_path):
    target = tmp_path / "config.toml"

    seeded = runner.invoke(
        app,
        [
            "onboard", "configure", "search",
            "--search-provider", "duckduckgo",
            "--max-results", "9",
            "--fallback-policy", "network",
            "--diagnostics",
            "--use-env-proxy",
            "--proxy", "http://127.0.0.1:3128",
            "--config", str(target),
        ],
    )
    assert seeded.exit_code == 0, seeded.output
    before = load_config(target)
    assert before.search_max_results == 9
    assert before.search_fallback_policy == "network"
    assert before.search_diagnostics is True
    assert before.search_use_env_proxy is True
    assert before.search_proxy == "http://127.0.0.1:3128"

    # Run the exact command the guidance advertises (not a re-typed copy).
    entry = headless_setup_command("search")
    assert entry is not None
    _label, advertised = entry
    tokens = advertised.split()
    assert tokens[0] == "opensquilla"
    result = runner.invoke(app, [*tokens[1:], "--config", str(target)])

    assert result.exit_code == 0, result.output
    after = load_config(target)
    assert after.search_provider == "duckduckgo"
    assert after.search_max_results == 9
    assert after.search_fallback_policy == "network"
    assert after.search_diagnostics is True
    assert after.search_use_env_proxy is True
    assert after.search_proxy == "http://127.0.0.1:3128"
