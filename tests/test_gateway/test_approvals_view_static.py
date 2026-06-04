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


def test_sandbox_replaces_approvals_page_route_and_assets() -> None:
    app = APP_JS.read_text(encoding="utf-8")
    template = TEMPLATE.read_text(encoding="utf-8")

    assert "Router.register('/sandbox'" in app
    assert "Router.register('/approvals'" not in app
    assert 'data-path="/sandbox"' in app
    assert 'data-path="/approvals"' not in app
    assert "/static/js/views/sandbox.js" in template
    assert "/static/css/views/sandbox.css" in template
    assert "/static/js/views/approvals.js" not in template
    assert "/static/css/views/approvals.css" not in template


def test_sandbox_view_keeps_control_sections_read_oriented() -> None:
    js = SANDBOX_JS.read_text(encoding="utf-8")

    assert "App.getRpc()" in js
    assert "sandbox.status" in js
    assert "sandbox.explain" in js
    assert "sandbox.run_context.get" in js
    assert "Status" in js
    assert "Workspace & Mounts" in js
    assert "Managed Network" in js
    assert "Sandbox Rules" in js
    assert "Approval activity" not in js


def test_sandbox_metadata_wraps_long_runtime_identifiers() -> None:
    css = SANDBOX_CSS.read_text(encoding="utf-8")

    assert ".sandbox-detail-list strong," in css
    assert ".sandbox-list__main," in css
    assert ".sandbox-list__sub" in css
    wrap_start = css.index(".sandbox-detail-list strong,")
    wrap_rule = css[wrap_start : css.index("}", wrap_start)]
    detail_start = css.index(".sandbox-detail-list__row,\n.sandbox-rule-list__row {")
    detail_rule = css[detail_start : css.index("}", detail_start)]
    chip_start = css.index(".sandbox-chip {")
    chip_rule = css[chip_start : css.index("}", chip_start)]

    assert "min-width: 0" in wrap_rule
    assert "overflow-wrap: anywhere" in wrap_rule
    assert "minmax(0, 1fr)" in detail_rule
    assert "min-height: 22px" in chip_rule


def test_approval_monitor_inline_button_polls_instead_of_deleted_page() -> None:
    source = APPROVAL_MONITOR_JS.read_text(encoding="utf-8")
    start = source.index("inline.addEventListener('click'")
    handler = source[start : source.index("});", start) + 3]

    assert "Router.navigate('/approvals')" not in source
    assert "_resetPollBackoff();" in handler
    assert "_poll();" in handler
    assert "_modal" in handler
