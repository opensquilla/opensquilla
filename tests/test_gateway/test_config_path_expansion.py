from __future__ import annotations

from opensquilla.gateway.config import GatewayConfig
from opensquilla.onboarding.config_store import resolve_config_path


def test_gateway_load_expands_tilde_in_explicit_config_path(monkeypatch, tmp_path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    # pathlib follows the native platform convention: POSIX reads HOME,
    # while Windows reads USERPROFILE when expanding ``~``.
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))

    real_config = fake_home / "myconfig.toml"
    real_config.write_text("port = 4242\n", encoding="utf-8")

    literal = "~/myconfig.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", literal)

    # CLI (config_store) already expands the tilde; the gateway must agree.
    resolved, source = resolve_config_path()
    assert resolved == real_config
    assert source == "env"

    cfg = GatewayConfig.load(literal)
    assert cfg.port == 4242
    assert cfg.config_path == str(real_config)
