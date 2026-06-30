"""Tests for the channel catalog."""

from __future__ import annotations

import pytest

from opensquilla.gateway.config import (
    DingTalkChannelEntry,
    DiscordChannelEntry,
    FeishuChannelEntry,
    MatrixChannelEntry,
    QQChannelEntry,
    SlackChannelEntry,
    TelegramChannelEntry,
    WeComChannelEntry,
)
from opensquilla.onboarding.channel_specs import (
    ChannelSetupSpec,
    channel_catalog_payload,
    get_channel_setup_spec,
    list_channel_setup_specs,
)

# msteams is intentionally absent: the adapter is text-only and hidden
# from runtime catalog surfaces until first-class support lands.
ALL_TYPES = {
    "slack", "feishu", "discord", "dingtalk", "wecom", "qq",
    "matrix", "telegram",
}

ENTRY_MODELS = {
    "slack": SlackChannelEntry,
    "feishu": FeishuChannelEntry,
    "discord": DiscordChannelEntry,
    "dingtalk": DingTalkChannelEntry,
    "wecom": WeComChannelEntry,
    "qq": QQChannelEntry,
    "matrix": MatrixChannelEntry,
    "telegram": TelegramChannelEntry,
}

EXPECTED_PUBLIC_URL: set[str] = set()
CONDITIONAL_PUBLIC_URL = {"feishu", "slack", "telegram", "wecom"}


def test_catalog_includes_all_channels():
    types = {s.type for s in list_channel_setup_specs()}
    assert types == ALL_TYPES


@pytest.mark.parametrize("type_name", sorted(ALL_TYPES))
def test_each_channel_has_common_fields(type_name: str):
    spec = get_channel_setup_spec(type_name)
    names = {f.name for f in spec.fields}
    assert {"name", "enabled", "agent_id"} <= names


@pytest.mark.parametrize("type_name", sorted(ALL_TYPES))
def test_spec_fields_align_with_pydantic_model(type_name: str):
    spec = get_channel_setup_spec(type_name)
    model = ENTRY_MODELS[type_name]
    pydantic_fields = set(model.model_fields.keys())
    spec_fields = {f.name for f in spec.fields}
    assert "type" not in spec_fields
    extra = spec_fields - pydantic_fields - {"type"}
    assert not extra, f"setup spec exposes unknown field(s): {extra}"


@pytest.mark.parametrize("type_name", sorted(ALL_TYPES))
def test_required_pydantic_fields_are_required_in_spec(type_name: str):
    spec = get_channel_setup_spec(type_name)
    model = ENTRY_MODELS[type_name]
    spec_required = {f.name for f in spec.fields if f.required}
    for fname, finfo in model.model_fields.items():
        if fname == "type":
            continue
        if finfo.is_required():
            assert fname in spec_required, (
                f"{type_name}.{fname} is required in pydantic but not in setup spec"
            )


def test_slack_secrets_are_marked_secret():
    spec = get_channel_setup_spec("slack")
    secrets = {f.name for f in spec.fields if f.secret}
    assert {"token", "app_token", "signing_secret"} <= secrets


def test_telegram_secrets_are_marked_secret():
    spec = get_channel_setup_spec("telegram")
    secrets = {f.name for f in spec.fields if f.secret}
    assert {"token", "webhook_secret_token"} <= secrets


def test_discord_gateway_auth_fields_do_not_expose_interactions_public_key():
    spec = get_channel_setup_spec("discord")
    fields = {f.name: f for f in spec.fields}

    assert fields["token"].required is True
    assert fields["token"].secret is True
    assert fields["application_id"].secret is False
    assert "public_key" not in fields


def test_dingtalk_stream_credentials_are_marked_correctly():
    spec = get_channel_setup_spec("dingtalk")
    fields = {f.name: f for f in spec.fields}

    assert fields["client_id"].required is True
    assert fields["client_id"].secret is False
    assert fields["client_secret"].required is True
    assert fields["client_secret"].secret is True


def test_feishu_webhook_secrets_are_marked_secret():
    spec = get_channel_setup_spec("feishu")
    secrets = {f.name for f in spec.fields if f.secret}

    assert {"app_secret", "encrypt_key", "verification_token"} <= secrets


def test_feishu_connection_mode_choices():
    spec = get_channel_setup_spec("feishu")
    field = next(f for f in spec.fields if f.name == "connection_mode")
    assert field.field_type == "select"
    assert field.default == "websocket"
    assert field.choices == ("webhook", "websocket")


def test_slack_connection_mode_choices():
    spec = get_channel_setup_spec("slack")
    field = next(f for f in spec.fields if f.name == "connection_mode")
    assert field.field_type == "select"
    assert field.default == "webhook"
    assert field.choices == ("webhook", "socket")
    assert field.advanced is False


def test_wecom_connection_mode_choices():
    spec = get_channel_setup_spec("wecom")
    field = next(f for f in spec.fields if f.name == "connection_mode")
    assert spec.transport == "mixed"
    assert spec.requires_public_url is False
    assert field.field_type == "select"
    assert field.default == "websocket"
    assert field.choices == ("websocket", "webhook")


def test_wecom_mode_specific_fields_are_conditional():
    spec = get_channel_setup_spec("wecom")
    fields = {f.name: f for f in spec.fields}

    assert fields["bot_id"].show_when == {"connection_mode": "websocket"}
    assert fields["bot_secret"].show_when == {"connection_mode": "websocket"}
    assert fields["websocket_url"].show_when == {"connection_mode": "websocket"}
    assert fields["corp_id"].show_when == {"connection_mode": "webhook"}
    assert fields["corp_secret"].show_when == {"connection_mode": "webhook"}
    assert fields["token"].show_when == {"connection_mode": "webhook"}
    assert fields["encoding_aes_key"].show_when == {"connection_mode": "webhook"}
    assert fields["bot_secret"].secret is True
    assert fields["corp_secret"].secret is True


def test_slack_mode_specific_fields_are_conditional():
    spec = get_channel_setup_spec("slack")
    fields = {f.name: f for f in spec.fields}
    assert fields["app_token"].show_when == {"connection_mode": "socket"}
    assert fields["signing_secret"].show_when == {"connection_mode": "webhook"}
    assert fields["signing_secret"].required is True
    assert fields["slack_channel_id"].required is False


def test_feishu_status_reactions_are_enabled_by_default():
    entry = FeishuChannelEntry(
        name="feishu",
        app_id="cli_test",
        app_secret="secret",
    )

    assert entry.status_reactions_enabled is True


def test_feishu_status_reactions_are_exposed_in_setup_spec():
    spec = get_channel_setup_spec("feishu")
    field = next(f for f in spec.fields if f.name == "status_reactions_enabled")

    assert field.field_type == "bool"
    assert field.default is True
    assert field.advanced is True


def test_feishu_webhook_fields_are_conditional():
    spec = get_channel_setup_spec("feishu")
    fields = {f.name: f for f in spec.fields}
    assert fields["webhook_path"].show_when == {"connection_mode": "webhook"}
    assert fields["verification_token"].show_when == {"connection_mode": "webhook"}
    assert fields["encrypt_key"].advanced is True


def test_telegram_webhook_fields_are_conditional():
    spec = get_channel_setup_spec("telegram")
    fields = {f.name: f for f in spec.fields}
    assert fields["transport_name"].default == "polling"
    assert fields["webhook_path"].show_when == {"transport_name": "webhook"}
    assert fields["webhook_url"].show_when == {"transport_name": "webhook"}
    assert fields["webhook_secret_token"].show_when == {"transport_name": "webhook"}
    assert fields["poll_timeout_s"].show_when == {"transport_name": "polling"}


def test_channel_catalog_payload_exposes_ui_metadata():
    payload = channel_catalog_payload()
    feishu = next(c for c in payload if c["type"] == "feishu")
    fields = {f["name"]: f for f in feishu["fields"]}
    assert fields["app_secret"]["group"] == "credentials"
    assert fields["app_secret"]["placeholder"]
    assert fields["webhook_path"]["showWhen"] == {"connection_mode": "webhook"}
    assert fields["encrypt_key"]["advanced"] is True
    assert feishu["blocking"] is False
    assert feishu["whatYouNeed"]
    slack = next(c for c in payload if c["type"] == "slack")
    assert "public URL" in slack["help"]
    assert slack["transport"] == "mixed"
    assert slack["requiresPublicUrl"] is False
    slack_fields = {f["name"]: f for f in slack["fields"]}
    assert slack_fields["app_token"]["showWhen"] == {"connection_mode": "socket"}


def test_matrix_encryption_choices():
    spec = get_channel_setup_spec("matrix")
    field = next(f for f in spec.fields if f.name == "encryption")
    assert field.choices == ("off", "required", "best_effort")


@pytest.mark.parametrize("type_name", sorted(EXPECTED_PUBLIC_URL))
def test_webhook_channels_require_public_url(type_name: str):
    spec = get_channel_setup_spec(type_name)
    assert spec.requires_public_url is True


@pytest.mark.parametrize("type_name", sorted(CONDITIONAL_PUBLIC_URL))
def test_conditional_webhook_channels_flagged(type_name: str):
    spec = get_channel_setup_spec(type_name)
    assert spec.transport in {"mixed", "webhook"}


def test_base_channel_specs_do_not_advertise_legacy_extras():
    for type_name in ("feishu", "telegram", "dingtalk", "wecom", "qq"):
        spec = get_channel_setup_spec(type_name)
        assert spec.dependency_extra is None


def test_matrix_advertises_its_real_optional_extra():
    spec = get_channel_setup_spec("matrix")
    assert spec.dependency_extra == "matrix"


def test_channel_catalog_payload_only_advertises_real_install_extras():
    payload = {entry["type"]: entry for entry in channel_catalog_payload()}
    for type_name in ("feishu", "telegram", "dingtalk", "wecom", "qq"):
        assert payload[type_name]["dependencyExtra"] is None
    assert payload["matrix"]["dependencyExtra"] == "matrix"


def test_unknown_channel_raises():
    with pytest.raises(KeyError):
        get_channel_setup_spec("not-a-channel")


def test_msteams_is_hidden_from_catalog():
    """msteams must not be advertised via the onboarding catalog."""
    types = {s.type for s in list_channel_setup_specs()}
    assert "msteams" not in types
    with pytest.raises(KeyError):
        get_channel_setup_spec("msteams")


def test_payload_redacts_secret_defaults():
    payload = channel_catalog_payload()
    for entry in payload:
        for f in entry["fields"]:
            if f.get("secret"):
                assert f["default"] in (None, "", False)


def test_catalog_is_sorted():
    types = [s.type for s in list_channel_setup_specs()]
    assert types == sorted(types)


def test_returns_setup_spec_instance():
    assert isinstance(get_channel_setup_spec("slack"), ChannelSetupSpec)
