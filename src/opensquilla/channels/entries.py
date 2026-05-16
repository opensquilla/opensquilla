"""Config entry schemas owned by channel adapters."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator, model_validator


class ConfiguredChannelEntry(BaseModel):
    """Common fields shared by gateway-managed channel entries."""

    name: str
    type: str
    enabled: bool = True
    agent_id: str = "main"
    debounce_window_s: float = 0.0
    status_reactions_enabled: bool = False

    @field_validator("debounce_window_s")
    @classmethod
    def _validate_debounce_window(cls, value: float) -> float:
        if value != 0.0 and not 0.1 <= value <= 30.0:
            raise ValueError("debounce_window_s must be 0 or in [0.1, 30.0]")
        return value


class SlackChannelEntry(ConfiguredChannelEntry):
    """Config entry for a Slack channel."""

    type: Literal["slack"] = "slack"
    token: str
    slack_channel_id: str = ""
    signing_secret: str | None = None
    reply_in_thread: bool = False


class FeishuChannelEntry(ConfiguredChannelEntry):
    """Config entry for a Feishu (Lark) channel."""

    type: Literal["feishu"] = "feishu"
    status_reactions_enabled: bool = True
    app_id: str
    app_secret: str
    encrypt_key: str = ""
    verification_token: str = ""
    default_chat_id: str = ""
    webhook_path: str = "/feishu/events"
    api_base: str = "https://open.feishu.cn/open-apis"
    connection_mode: Literal["webhook", "websocket"] = "websocket"
    domain: Literal["feishu", "lark"] = "feishu"


class DiscordChannelEntry(ConfiguredChannelEntry):
    """Config entry for a Discord channel."""

    type: Literal["discord"] = "discord"
    token: str
    application_id: str = ""
    default_channel_id: str = ""
    gateway_url: str = "wss://gateway.discord.gg/?v=10&encoding=json"
    intents: int = 33281


class DingTalkChannelEntry(ConfiguredChannelEntry):
    """Config entry for a DingTalk channel."""

    type: Literal["dingtalk"] = "dingtalk"
    client_id: str
    client_secret: str


class WeComChannelEntry(ConfiguredChannelEntry):
    """Config entry for a WeCom corp-app channel."""

    type: Literal["wecom"] = "wecom"
    corp_id: str
    corp_secret: str
    agent_id_int: int
    token: str
    encoding_aes_key: str
    webhook_path: str = "/wecom/events"
    api_base: str = "https://qyapi.weixin.qq.com"


class QQChannelEntry(ConfiguredChannelEntry):
    """Config entry for a QQ Bot channel."""

    type: Literal["qq"] = "qq"
    app_id: str
    app_secret: str


class MSTeamsChannelEntry(ConfiguredChannelEntry):
    """Config entry for an MS Teams channel."""

    type: Literal["msteams"] = "msteams"
    app_id: str
    app_password: str
    webhook_path: str = "/msteams/messages"


class MatrixChannelEntry(ConfiguredChannelEntry):
    """Config entry for a Matrix channel."""

    type: Literal["matrix"] = "matrix"
    homeserver_url: str
    user_id: str
    password: str = ""
    access_token: str = ""
    device_id: str = ""
    encryption: Literal["off", "required", "best_effort"] = "off"


class TelegramChannelEntry(ConfiguredChannelEntry):
    """Config entry for a Telegram Bot API channel."""

    type: Literal["telegram"] = "telegram"
    token: str
    default_chat_id: str = ""
    api_base: str = "https://api.telegram.org"
    transport_name: Literal["polling", "webhook"] = "polling"
    webhook_path: str = "/telegram/events"
    webhook_url: str = ""
    webhook_secret_token: str = ""
    drop_pending_updates: bool = False
    poll_timeout_s: int = 30
    poll_limit: int = 100
    poll_idle_sleep_s: float = 0.1

    @model_validator(mode="after")
    def _validate_webhook_auth(self) -> TelegramChannelEntry:
        if self.transport_name == "webhook":
            if not self.webhook_url:
                raise ValueError("webhook_url is required for telegram webhook mode")
            if not self.webhook_secret_token:
                raise ValueError(
                    "webhook_secret_token is required for telegram webhook mode"
                )
        return self


ChannelConfigEntry = ConfiguredChannelEntry
