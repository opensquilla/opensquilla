from pathlib import Path

COMPONENTS_JS = Path("src/opensquilla/gateway/static/js/components.js")
AGENTS_JS = Path("src/opensquilla/gateway/static/js/views/agents.js")
SESSIONS_JS = Path("src/opensquilla/gateway/static/js/views/sessions.js")
OVERVIEW_JS = Path("src/opensquilla/gateway/static/js/views/overview.js")
LOGS_JS = Path("src/opensquilla/gateway/static/js/views/logs.js")


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


def test_sessions_view_uses_status_helper() -> None:
    source = SESSIONS_JS.read_text(encoding="utf-8")

    assert "UI.sessionStatusClass(" in source
    assert "UI.sessionStatusChip(" in source
    assert "UI.sessionStatusLabel(" in source

    # Legacy 3-bucket ternary fragment must be gone.
    assert "=== 'running' || s.status === 'active'" not in source


def test_overview_view_uses_status_helper() -> None:
    source = OVERVIEW_JS.read_text(encoding="utf-8")

    assert "UI.sessionStatusClass(" in source

    # Legacy 3-bucket ternary fragment must be gone.
    assert "? 'is-on'" not in source


def test_components_js_defines_control_view_stat_card_helper() -> None:
    source = COMPONENTS_JS.read_text(encoding="utf-8")

    assert "function statCard({" in source
    assert "stat stat--hero" in source
    assert "stat-value mono" in source
    assert "stat-hint" in source
    assert "statCard," in source


def test_control_views_use_shared_stat_card_helper() -> None:
    for path in (AGENTS_JS, SESSIONS_JS, LOGS_JS):
        source = path.read_text(encoding="utf-8")
        assert "UI.statCard(" in source, f"{path} should use the shared stat card helper"
