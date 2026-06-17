"""Static contract for the web ``/meta`` slash-command wiring in chat.js.

JS is not unit-tested with a JS runner here; mirror the static-assertion
approach used by ``test_chat_meta_ribbon_static.py`` and lock the source text
so the ``meta.menu`` slash case keeps dispatching to both ``meta.list`` (no
arg) and ``meta.run`` (with a skill name).
"""

import re
from pathlib import Path

CHAT_JS = Path("src/opensquilla/gateway/static/js/views/chat.js")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_chat_js_has_meta_menu_slash_case() -> None:
    text = _read_text(CHAT_JS)
    assert "case 'meta.menu':" in text, "missing case 'meta.menu' in _selectSlashCmd"


def test_meta_menu_case_dispatches_to_both_meta_rpcs() -> None:
    text = _read_text(CHAT_JS)
    # The single meta.menu case must reach both RPCs: list (no arg) and run
    # (with a skill name). Scope the search to the case body so we assert the
    # case itself dispatches to both, not merely that the strings exist
    # somewhere in the file.
    match = re.search(
        r"case 'meta\.menu':\s*\{(?P<body>.*?)\n      \}",
        text,
        re.DOTALL,
    )
    assert match is not None, "could not isolate the meta.menu case body"
    body = match.group("body")
    assert "meta.list" in body, "meta.menu case must call the meta.list RPC"
    assert "meta.run" in body, "meta.menu case must call the meta.run RPC"
    # run path passes the session key and a skill name; list path renders skills.
    assert "sessionKey" in body, "meta.run call must pass sessionKey"
