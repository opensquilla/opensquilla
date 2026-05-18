from pathlib import Path

COMPONENTS_JS = Path("src/opensquilla/gateway/static/js/components.js")
SESSIONS_JS = Path("src/opensquilla/gateway/static/js/views/sessions.js")
OVERVIEW_JS = Path("src/opensquilla/gateway/static/js/views/overview.js")
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
