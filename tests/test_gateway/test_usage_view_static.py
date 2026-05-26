"""Static smoke tests for Usage view cost provenance display."""

from pathlib import Path

USAGE_JS = Path("src/opensquilla/gateway/static/js/views/usage.js")
USAGE_CSS = Path("src/opensquilla/gateway/static/css/views/usage.css")


def test_usage_view_renders_cost_source_badges_and_exports_fields() -> None:
    source = USAGE_JS.read_text(encoding="utf-8")

    assert "_renderCostSourceBadge(row)" in source
    assert "{ key: 'cost_source', label: 'Cost Source' }" in source
    assert "case 'opensquilla_estimate': return 'Cost est.'" in source
    assert "billed_cost_usd" in source
    assert "estimated_cost_usd" in source
    assert "missing_cost_entries" in source
    assert "cost_ephemeral" in source


def test_usage_collapsed_model_display_uses_model_breakdown() -> None:
    source = USAGE_JS.read_text(encoding="utf-8")
    start = source.index("function _renderModelCell(row)")
    end = source.index("  function _buildExpandedContent(row)", start)
    body = source[start:end]

    assert "function _modelDisplayLabel(row)" in source
    assert "bd.length > 1 ? `auto · ${bd.length} models`" in source
    assert "bd[0].model || row.model" in source
    assert "const label = _modelDisplayLabel(row);" in body
    assert "const label = bd.length > 1 ? `auto · ${bd.length} models` : _esc(model);" not in body


def test_usage_view_has_cost_source_styles() -> None:
    source = USAGE_CSS.read_text(encoding="utf-8")

    assert ".usage-source--provider_billed" in source
    assert ".usage-source--opensquilla_estimate" in source
    assert ".usage-source--mixed" in source
    assert ".usage-source--unavailable" in source
    assert ".usage-source--ephemeral" in source


def test_usage_view_range_selector_is_page_wide() -> None:
    source = USAGE_JS.read_text(encoding="utf-8")

    assert 'data-range="all"' in source
    assert "let _range" in source
    assert "_visibleSessions()" in source
    assert "Number(btn.dataset.range)" not in source
    assert "_renderMetrics(_lastStatus, _lastCost)" in source
    assert "_renderTable()" in source
    assert "_renderChart()" in source
    assert "_renderModelBreakdown()" in source


def test_usage_view_visible_session_helper_drives_renderers_and_export() -> None:
    source = USAGE_JS.read_text(encoding="utf-8")

    assert "function _sessionTimestamp(row)" in source
    assert "function _rangeCutoffMs" in source
    assert "function _visibleSessions()" in source
    assert "function _undatedHiddenCount()" in source
    assert "function _usageTotals(rows)" in source
    assert "undated legacy session" in source

    for marker in [
        "function _renderMetrics(status, cost)",
        "function _renderTable()",
        "function _renderChart()",
        "function _renderModelBreakdown()",
        "function _exportCsv()",
    ]:
        start = source.index(marker)
        body = source[start : source.index("\n  function ", start + 1)]
        assert "_visibleSessions()" in body or "visibleRows" in body


def test_usage_view_model_expansion_uses_visible_sessions() -> None:
    source = USAGE_JS.read_text(encoding="utf-8")
    start = source.index("function _bindModelToggles(wrap)")
    end = source.index("  function _renderModelBreakdown()", start)
    body = source[start:end]

    assert "_visibleSessions().find" in body
