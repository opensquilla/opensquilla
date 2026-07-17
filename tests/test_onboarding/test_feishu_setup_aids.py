"""The Feishu setup aids must track what the integration actually uses.

The scope manifest is a paste-once console import; if a platform tool gains a
scope that never lands in the manifest, the operator pastes an incomplete
list and the tool 403s later with no obvious cause.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from opensquilla.onboarding.channel_specs import (
    FEISHU_TENANT_SCOPES,
    channel_catalog_payload,
    get_channel_setup_spec,
)


def _aids_by_id() -> dict[str, object]:
    spec = get_channel_setup_spec("feishu")
    return {aid.id: aid for aid in spec.setup_aids}


def test_scope_manifest_covers_every_platform_tool_scope() -> None:
    from opensquilla.tools.builtin.feishu_platform import _FEATURE_CAPABILITIES

    declared: set[str] = set()
    for feature in _FEATURE_CAPABILITIES.values():
        declared.update(feature.required_scopes)

    missing = declared - set(FEISHU_TENANT_SCOPES)
    assert not missing, f"platform tools use scopes absent from the manifest: {sorted(missing)}"


def test_scopes_json_aid_is_the_console_import_shape() -> None:
    aid = _aids_by_id()["scopes_json"]
    manifest = json.loads(aid.content)
    assert manifest == {"scopes": {"tenant": list(FEISHU_TENANT_SCOPES), "user": []}}


def test_quick_apply_link_carries_the_same_scopes() -> None:
    aid = _aids_by_id()["quick_apply_link"]
    assert "{app_id}" in aid.content
    parsed = urlparse(aid.content.replace("{app_id}", "cli_test"))
    query = parse_qs(parsed.query)
    assert query["q"][0].split(",") == list(FEISHU_TENANT_SCOPES)
    assert query["token_type"] == ["tenant"]


def test_catalog_payload_serializes_setup_aids() -> None:
    feishu = next(row for row in channel_catalog_payload() if row["type"] == "feishu")
    aids = {aid["id"]: aid for aid in feishu["setupAids"]}
    assert set(aids) == {"scopes_json", "credentials_link", "quick_apply_link", "ws_order_note"}
    assert aids["ws_order_note"]["kind"] == "note"
    # Channels without aids serialize an empty list, not a missing key.
    slack = next(row for row in channel_catalog_payload() if row["type"] == "slack")
    assert slack["setupAids"] == []
