"""Static contract for the web ``/meta`` slash-command wiring.

The served web UI is the Vite SPA under ``opensquilla-webui/`` (built into
``static/dist/``); its slash dispatch lives in
``composables/chat/useChatSlashCommands.ts``. JS/TS is not unit-tested with a JS
runner here, so we lock the SPA source text: the ``meta.menu`` case in
``selectSlashCmd`` must dispatch to both ``meta.list`` (no arg) and ``meta.run``
(with a skill name, passing the session key), and trigger a turn via the hidden
dispatch path. (The legacy ``static/js/views/chat.js`` is NOT served, so it is
intentionally not the file under test.)
"""

from pathlib import Path

SPA_SLASH = Path("opensquilla-webui/src/composables/chat/useChatSlashCommands.ts")


def _meta_menu_case_body() -> str:
    text = SPA_SLASH.read_text(encoding="utf-8")
    marker = "case 'meta.menu':"
    assert marker in text, f"missing {marker!r} in selectSlashCmd ({SPA_SLASH})"
    # The meta.menu case is the last case in the switch; everything after the
    # marker covers its body.
    return text[text.index(marker):]


def test_spa_slash_has_meta_menu_case() -> None:
    _meta_menu_case_body()  # asserts the case exists


def test_meta_menu_case_dispatches_to_both_meta_rpcs() -> None:
    body = _meta_menu_case_body()
    assert "meta.list" in body, "meta.menu case must call the meta.list RPC (no-arg list)"
    assert "meta.run" in body, "meta.menu case must call the meta.run RPC (with skill name)"
    assert "sessionKey" in body, "meta.run call must pass sessionKey"
    assert "dispatchHidden" in body, "meta.menu run path must trigger a turn via dispatchHidden"
