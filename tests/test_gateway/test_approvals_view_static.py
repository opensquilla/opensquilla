from pathlib import Path

APP_JS = Path("src/opensquilla/gateway/static/js/app.js")
APPROVAL_MONITOR_JS = Path("src/opensquilla/gateway/static/js/approval_monitor.js")
APPROVALS_CSS = Path("src/opensquilla/gateway/static/css/views/approvals.css")
APPROVALS_JS = Path("src/opensquilla/gateway/static/js/views/approvals.js")
SANDBOX_CSS = Path("src/opensquilla/gateway/static/css/views/sandbox.css")
SANDBOX_JS = Path("src/opensquilla/gateway/static/js/views/sandbox.js")
TEMPLATE = Path("src/opensquilla/gateway/templates/index.html")


def test_standalone_approvals_page_assets_stay_removed() -> None:
    assert not APPROVALS_JS.exists()
    assert not APPROVALS_CSS.exists()


def test_standalone_sandbox_page_route_and_assets_are_removed() -> None:
    app = APP_JS.read_text(encoding="utf-8")
    template = TEMPLATE.read_text(encoding="utf-8")

    assert not SANDBOX_JS.exists()
    assert not SANDBOX_CSS.exists()
    assert "Router.register('/sandbox'" not in app
    assert "Router.register('/approvals'" not in app
    assert 'data-path="/sandbox"' not in app
    assert 'data-path="/approvals"' not in app
    assert "/static/js/views/sandbox.js" not in template
    assert "/static/css/views/sandbox.css" not in template
    assert "/static/js/views/approvals.js" not in template
    assert "/static/css/views/approvals.css" not in template


def test_approval_monitor_inline_button_polls_instead_of_deleted_page() -> None:
    source = APPROVAL_MONITOR_JS.read_text(encoding="utf-8")
    start = source.index("inline.addEventListener('click'")
    handler = source[start : source.index("});", start) + 3]

    assert "Router.navigate('/approvals')" not in source
    assert "_resetPollBackoff();" in handler
    assert "_poll();" in handler
    assert "_modal" in handler
