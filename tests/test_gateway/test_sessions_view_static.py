from pathlib import Path

SESSIONS_JS = Path("src/opensquilla/gateway/static/js/views/sessions.js")
SESSIONS_CSS = Path("src/opensquilla/gateway/static/css/views/sessions.css")


def test_sessions_page_size_select_keeps_touch_friendly_hit_area() -> None:
    css = SESSIONS_CSS.read_text(encoding="utf-8")
    start = css.index(".sess-page-size select {")
    rule = css[start : css.index("}", start)]

    assert "min-height: 40px" in rule


def test_sessions_search_keeps_touch_friendly_hit_area() -> None:
    css = SESSIONS_CSS.read_text(encoding="utf-8")
    start = css.index(".sess-search-input {")
    rule = css[start : css.index("}", start)]

    assert "min-height: 40px" in rule


def test_sessions_mobile_header_keeps_search_readable() -> None:
    css = SESSIONS_CSS.read_text(encoding="utf-8")
    mobile_start = css.index("@media (max-width: 480px)")
    mobile_block = css[mobile_start:]

    assert ".sess-search-wrap" in mobile_block
    assert "flex: 1 1 100%" in mobile_block
    assert ".sess-stage__actions > .btn" in mobile_block
    assert "flex: 1 1 0" in mobile_block
    assert "justify-content: center" in mobile_block


def test_sessions_extra_narrow_stats_use_single_column() -> None:
    css = SESSIONS_CSS.read_text(encoding="utf-8")
    mobile_start = css.index("@media (max-width: 360px)")
    mobile_block = css[mobile_start:]
    stat_start = mobile_block.index(".sess-stage .stat-row {")
    stat_rule = mobile_block[stat_start : mobile_block.index("}", stat_start)]

    assert "grid-template-columns: 1fr" in stat_rule


def test_sessions_agent_subline_wraps_long_runtime_identifiers() -> None:
    css = SESSIONS_CSS.read_text(encoding="utf-8")
    subline_start = css.index(".sess-key__sub {")
    subline_rule = css[subline_start : css.index("}", subline_start)]
    agent_start = css.index(".sess-key__agent {")
    agent_rule = css[agent_start : css.index("}", agent_start)]

    assert "min-width: 0" in subline_rule
    assert "overflow-wrap: anywhere" in subline_rule
    assert "max-width: 100%" in agent_rule
    assert "min-width: 0" in agent_rule
    assert "overflow-wrap: anywhere" in agent_rule


def test_single_session_delete_checks_backend_partial_failure_response() -> None:
    source = SESSIONS_JS.read_text(encoding="utf-8")
    start = source.index("function _deleteSession(key)")
    end = source.index("  async function _openNewSessionModal()", start)
    body = source[start:end]

    assert "const res = await _rpc.call('sessions.delete', { key });" in body
    assert "res.errors" in body
    assert "res.deleted" in body
    assert "deleted.includes(key)" in body
    assert "typeof first === 'string'" in body
    assert "Session deleted" in body
    assert "Delete failed" in body
    assert body.index("res.errors") < body.index("Session deleted")
