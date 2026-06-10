from __future__ import annotations

from pathlib import Path

CHAT_JS = Path("src/opensquilla/gateway/static/js/views/chat.js")


def test_web_chat_defaults_to_full_host_access() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "const _RUN_MODE_DEFAULT = 'full';" in source
    assert "Establish sandbox" in source
