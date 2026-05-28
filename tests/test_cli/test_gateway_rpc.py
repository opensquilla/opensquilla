from __future__ import annotations

from opensquilla.cli.gateway_rpc import default_gateway_token


def test_default_gateway_token_uses_explicit_config_path(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENSQUILLA_GATEWAY_TOKEN", raising=False)
    monkeypatch.delenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", raising=False)
    config = tmp_path / "custom-opensquilla.toml"
    config.write_text(
        """
[auth]
mode = "token"
token = "from-explicit-config"
""",
        encoding="utf-8",
    )

    assert default_gateway_token(config) == "from-explicit-config"


def test_default_gateway_token_env_override_wins_over_explicit_config(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_TOKEN", "from-env")
    config = tmp_path / "custom-opensquilla.toml"
    config.write_text(
        """
[auth]
mode = "token"
token = "from-explicit-config"
""",
        encoding="utf-8",
    )

    assert default_gateway_token(config) == "from-env"
