from __future__ import annotations

from pathlib import Path

CHAT_JS = Path("src/opensquilla/gateway/static/js/views/chat.js")


def test_web_chat_defaults_to_trusted_sandbox() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "const _RUN_MODE_DEFAULT = 'trusted';" in source
