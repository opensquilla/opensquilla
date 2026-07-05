"""Channel-crypto secrets must not echo through the public config view.

``channels.feishu.encrypt_key`` and ``channels.wecom.encoding_aes_key`` are
crypto material, but neither matches the generic redaction suffixes
(``_token``/``_secret``/``_password``/``_api_key``), so before they were
added to ``_PUBLIC_SECRET_EXACT_KEYS`` both echoed in cleartext through
``config.get``. These tests pin the fix against a full-dump-shaped config
(the exact shape ``config.get`` returns) carrying feishu + wecom tables.

All values are synthetic public dummies (CONTRIBUTING.md data hygiene).
"""

from __future__ import annotations

import pytest

from opensquilla.gateway.config import (
    GatewayConfig,
    LlmProviderConfig,
    is_sensitive_config_key,
    redact_public_config,
)

REDACTION_MARKER = "[redacted]"

FEISHU_ENCRYPT_KEY = "feishu-encrypt-key-000"
WECOM_ENCODING_AES_KEY = "wecom-aes-key-000"
API_KEY_ENV_NAME = "SYNTHETIC_PROVIDER_API_KEY"


@pytest.fixture()
def full_dump_config(tmp_path, monkeypatch: pytest.MonkeyPatch) -> GatewayConfig:
    """A config carrying feishu + wecom channel tables, rc1-full-dump shaped."""
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "state"))
    return GatewayConfig(
        config_path=str(tmp_path / "opensquilla.toml"),
        llm=LlmProviderConfig(api_key_env=API_KEY_ENV_NAME),
        channels={
            "channels": [
                {
                    "name": "feishu-main",
                    "type": "feishu",
                    "app_id": "cli_dummy_0000",
                    "app_secret": "feishu-app-secret-000",
                    "encrypt_key": FEISHU_ENCRYPT_KEY,
                    "verification_token": "feishu-verify-000",
                },
                {
                    "name": "wecom-main",
                    "type": "wecom",
                    "connection_mode": "webhook",
                    "corp_id": "ww_dummy_0000",
                    "corp_secret": "wecom-corp-secret-000",
                    "agent_id_int": 1000002,
                    "token": "wecom-token-000",
                    "encoding_aes_key": WECOM_ENCODING_AES_KEY,
                },
            ]
        },
    )


def _channel_by_type(public: dict, channel_type: str) -> dict:
    entries = public["channels"]["channels"]
    matches = [entry for entry in entries if entry.get("type") == channel_type]
    assert len(matches) == 1, f"expected one {channel_type} entry, got {matches!r}"
    return matches[0]


def test_feishu_encrypt_key_is_masked_in_full_dump(full_dump_config: GatewayConfig) -> None:
    public = redact_public_config(full_dump_config.model_dump())
    feishu = _channel_by_type(public, "feishu")
    assert feishu["encrypt_key"] == REDACTION_MARKER
    assert FEISHU_ENCRYPT_KEY not in repr(public)


def test_wecom_encoding_aes_key_is_masked_in_full_dump(full_dump_config: GatewayConfig) -> None:
    public = redact_public_config(full_dump_config.model_dump())
    wecom = _channel_by_type(public, "wecom")
    assert wecom["encoding_aes_key"] == REDACTION_MARKER
    assert WECOM_ENCODING_AES_KEY not in repr(public)


def test_to_public_dict_masks_channel_crypto_too(full_dump_config: GatewayConfig) -> None:
    # to_public_dict is the config.get surface; both crypto fields must be
    # masked there as well, alongside the already-covered suffix-matched
    # secrets in the same tables.
    public = full_dump_config.to_public_dict()
    assert _channel_by_type(public, "feishu")["encrypt_key"] == REDACTION_MARKER
    assert _channel_by_type(public, "wecom")["encoding_aes_key"] == REDACTION_MARKER
    assert FEISHU_ENCRYPT_KEY not in repr(public)
    assert WECOM_ENCODING_AES_KEY not in repr(public)


def test_api_key_env_name_stays_readable(full_dump_config: GatewayConfig) -> None:
    # The redactor extension deliberately adds exact keys, not a blanket
    # "_key" suffix: env-NAME fields carry which env var a secret loads
    # from (not the secret itself) and clients must keep rendering them.
    public = full_dump_config.to_public_dict()
    assert public["llm"]["api_key_env"] == API_KEY_ENV_NAME


def test_sensitivity_predicate_covers_channel_crypto_exact_keys() -> None:
    assert is_sensitive_config_key("encrypt_key")
    assert is_sensitive_config_key("encoding_aes_key")
    # Normalization parity with the rest of the predicate.
    assert is_sensitive_config_key("Encoding-AES-Key")
    # Non-secret key-name/reference fields must stay readable.
    assert not is_sensitive_config_key("api_key_env")
    assert not is_sensitive_config_key("search_api_key_env")
