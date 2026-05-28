from pathlib import Path

COMPONENTS_JS = Path("src/opensquilla/gateway/static/js/components.js")
SESSIONS_JS = Path("src/opensquilla/gateway/static/js/views/sessions.js")
OVERVIEW_JS = Path("src/opensquilla/gateway/static/js/views/overview.js")
OVERVIEW_CSS = Path("src/opensquilla/gateway/static/css/views/overview.css")
SESSIONS_CSS = Path("src/opensquilla/gateway/static/css/views/sessions.css")


def test_components_js_defines_session_status_helpers() -> None:
    source = COMPONENTS_JS.read_text(encoding="utf-8")

    # Function names exposed on window.UI.
    assert "sessionStatusClass" in source
    assert "sessionStatusChip" in source
    assert "sessionStatusLabel" in source

    # Every SessionStatus key must appear in the dot+chip lookup tables.
    for status in ("running", "done", "failed", "killed", "timeout"):
        assert f"{status}:" in source, f"missing status key '{status}' in components.js"

    # Default-branch literal — covers the unknown-input fall-through.
    # The new dot vocabulary uses 'off' for muted/unknown.
    assert "|| 'off'" in source

    # Human-readable labels used for tooltips / aria-labels.
    for label in ("Running", "Completed", "Failed", "Aborted by operator", "Timed out"):
        assert label in source, f"missing tooltip label '{label}' in components.js"


def test_components_js_deduplicates_visible_toasts_by_type_and_message() -> None:
    source = COMPONENTS_JS.read_text(encoding="utf-8")
    start = source.index("function toast(message, type = 'info', duration = 3000) {")
    end = source.index("  // -- Modal --", start)
    body = source[start:end]

    assert "_visibleToasts = new Map()" in source
    assert "const toastKey = `${type}\\u0000${message}`;" in body
    assert "if (_visibleToasts.has(toastKey)) return;" in body
    assert "_visibleToasts.set(toastKey, el);" in body
    assert "if (_visibleToasts.get(toastKey) === el)" in body
    assert "_visibleToasts.delete(toastKey);" in body


def test_components_rel_time_accepts_epoch_milliseconds() -> None:
    source = COMPONENTS_JS.read_text(encoding="utf-8")
    start = source.index("function relTime(isoOrTs) {")
    end = source.index("  // -- Session status helpers --", start)
    body = source[start:end]

    assert "Math.abs(numeric) < 10000000000 ? numeric * 1000 : numeric" in body
    assert "Number.isNaN(d.getTime())" in body


def test_sessions_view_uses_status_helper() -> None:
    source = SESSIONS_JS.read_text(encoding="utf-8")

    assert "UI.sessionStatusClass(" in source
    assert "UI.sessionStatusChip(" in source
    assert "UI.sessionStatusLabel(" in source

    # Legacy 3-bucket ternary fragment must be gone.
    assert "=== 'running' || s.status === 'active'" not in source


def test_sessions_view_uses_run_status_for_active_display() -> None:
    source = SESSIONS_JS.read_text(encoding="utf-8")

    assert "_sessionRunStatus(" in source
    assert "activeRuns" in source
    assert "run_status" in source
    assert "Executing" in source
    assert "open ·" in source
    assert "live conversations" not in source


def test_sessions_view_sorts_updated_at_numerically() -> None:
    source = SESSIONS_JS.read_text(encoding="utf-8")
    start = source.index("function _sortData() {")
    end = source.index("  function _renderStats()", start)
    body = source[start:end]

    assert "_sortCol === 'message_count' || _sortCol === 'updated_at'" in body
    assert "Number(va) || 0" in body


def test_sessions_view_does_not_count_killed_as_errored() -> None:
    source = SESSIONS_JS.read_text(encoding="utf-8")

    assert "failedOrTimedOut" in source
    assert "aborted" in source
    assert "s.status === 'failed' || s.status === 'killed' || s.status === 'timeout'" not in source


def test_sessions_view_counts_terminal_task_failures_as_failed() -> None:
    source = SESSIONS_JS.read_text(encoding="utf-8")

    assert "function _sessionVisualStatus(row)" in source
    assert "const visualStatus = _sessionVisualStatus(row);" in source
    assert "const failedOrTimedOut = _allSessions.filter(s => {" in source
    stats_start = source.index("const failedOrTimedOut = _allSessions.filter(s => {")
    stats_end = source.index("const aborted =", stats_start)
    stats_block = source[stats_start:stats_end]
    assert "_sessionVisualStatus(s)" in stats_block
    assert "status === 'failed' || status === 'timeout'" in stats_block
    assert "s.status === 'failed' || s.status === 'timeout'" not in stats_block


def test_sessions_view_counts_terminal_cancellations_as_aborted() -> None:
    source = SESSIONS_JS.read_text(encoding="utf-8")

    assert (
        "const aborted = _allSessions.filter(s => _sessionVisualStatus(s) === 'killed').length;"
        in source
    )
    assert "const aborted = _allSessions.filter(s => s.status === 'killed').length;" not in source


def test_sessions_mobile_keeps_row_actions_reachable() -> None:
    css = SESSIONS_CSS.read_text(encoding="utf-8")

    action_start = css.index(".sess-table__cell--actions {")
    action_rule = css[action_start : css.index("}", action_start)]
    assert "position: sticky" in action_rule
    assert "right: 0" in action_rule
    assert "z-index:" in action_rule

    icon_rule = css[css.index(".sess-iconbtn {") : css.index("}", css.index(".sess-iconbtn {"))]
    assert "min-width: 32px" in icon_rule
    assert "min-height: 32px" in icon_rule


def test_overview_view_uses_status_helper() -> None:
    source = OVERVIEW_JS.read_text(encoding="utf-8")

    assert "UI.sessionStatusClass(" in source

    # Legacy 3-bucket ternary fragment must be gone.
    assert "? 'is-on'" not in source


def test_overview_ignores_stale_load_after_view_destroy() -> None:
    source = OVERVIEW_JS.read_text(encoding="utf-8")
    render_start = source.index("function render(el)")
    render_end = source.index("  function destroy()", render_start)
    render_body = source[render_start:render_end]
    destroy_start = source.index("function destroy()")
    destroy_end = source.index("  function _updateConnectionPill", destroy_start)
    destroy_body = source[destroy_start:destroy_end]
    start = source.index("async function _loadData()")
    end = source.index("  function _pushEvent", start)
    body = source[start:end]

    assert "let _viewGeneration = 0;" in source
    assert "_viewGeneration += 1;" in render_body
    assert "_viewGeneration += 1;" in destroy_body
    assert "const root = _el;" in body
    assert "const generation = _viewGeneration;" in body
    assert "const rpc = _rpc;" in body
    assert "if (!rpc) return;" in body
    assert "function _isCurrentView(root, rpc, generation)" in body
    assert "return _el === root && _rpc === rpc && _viewGeneration === generation;" in body
    assert body.count("if (!_isCurrentView(root, rpc, generation)) return;") >= 8
    assert "root.querySelector('#' + id)" in body
    assert "root.querySelector('#ov-cost-line')" in body
    assert "root.querySelector('#ov-recent-sessions')" in body
    assert "rpc.call('status')" in body
    assert "rpc.call('doctor.status'" in body


def test_overview_text_links_have_touch_friendly_hit_area() -> None:
    css = OVERVIEW_CSS.read_text(encoding="utf-8")
    start = css.index(".ov-link {")
    rule = css[start : css.index("}", start)]

    assert "display: inline-flex" in rule
    assert "min-height: 40px" in rule
    assert "padding: 0 var(--sp-1)" in rule


def test_overview_mobile_recent_session_keys_wrap_inside_rows() -> None:
    css = OVERVIEW_CSS.read_text(encoding="utf-8")
    mobile = css.split("@media (max-width: 720px)", 1)[1]
    key_rule = mobile.split(".ov-recent__key {", 1)[1].split("}", 1)[0]

    assert "max-width: 100%" in key_rule
    assert "white-space: normal" in key_rule
    assert "overflow-wrap: anywhere" in key_rule
    assert "text-overflow: clip" in key_rule


def test_overview_mobile_recent_session_arrow_does_not_create_ghost_row() -> None:
    css = OVERVIEW_CSS.read_text(encoding="utf-8")
    mobile = css.split("@media (max-width: 720px)", 1)[1]
    arrow_rule = mobile.split(".ov-recent__arrow {", 1)[1].split("}", 1)[0]

    assert "display: none" in arrow_rule
