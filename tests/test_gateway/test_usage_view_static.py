"""Static smoke tests for Usage view cost provenance display."""

from pathlib import Path

USAGE_JS = Path("src/opensquilla/gateway/static/js/views/usage.js")
USAGE_CSS = Path("src/opensquilla/gateway/static/css/views/usage.css")


def test_usage_view_renders_cost_source_badges_and_exports_fields() -> None:
    source = USAGE_JS.read_text(encoding="utf-8")

    assert "_renderCostSourceBadge(row)" in source
    assert "{ key: 'cost_source', label: 'Source' }" in source
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
    # New pro-rated style for the billed-but-split breakdown items.
    assert ".usage-source--provider_billed_prorated" in source
    assert ".usage-source--opensquilla_estimate" in source
    assert ".usage-source--mixed" in source
    assert ".usage-source--unavailable" in source
    assert ".usage-source--ephemeral" in source


def test_usage_view_recognises_prorated_source() -> None:
    """The cost-source label/tooltip switch must handle provider_billed_prorated.

    UI choice: the badge text stays "Actual" (the total IS the real billed
    amount; only the per-model split is estimated). The visual differentiation
    is the dashed-border CSS variant and the tooltip explaining the nuance.
    """
    source = USAGE_JS.read_text(encoding="utf-8")
    assert "case 'provider_billed_prorated':" in source
    # Tooltip must call out the split-is-estimated nuance without resorting
    # to billing-period terms like "pro-rated" which carry misleading
    # connotations of partial-time refunds.
    assert "Total is real billed" in source
    assert "per-model split is estimated" in source
    assert "'provider_billed_prorated'" in source  # in _costSourceClass known list


def test_usage_expand_row_renders_cost_source_badge() -> None:
    """Per-model expand rows must surface a Source badge.

    Without a per-row badge, the pro-rated source is invisible to the user.
    Without this assertion a regression could re-hide the per-model source by
    accidentally removing the cell.
    """
    source = USAGE_JS.read_text(encoding="utf-8")
    start = source.index("function _buildExpandedContent(row)")
    end = source.index("\n  function ", start + 1)
    body = source[start:end]

    assert "usage-expand__source" in body
    assert "_renderCostSourceBadge(m)" in body
    # The grouped disclosure shown when any item is pro-rated.
    assert "usage-expand__notice" in body
    # Disclosure copy: must mention that the split is estimated.
    assert "split is estimated" in body


def test_usage_view_has_expand_source_styles() -> None:
    source = USAGE_CSS.read_text(encoding="utf-8")
    # Desktop grid must include the Source column.
    assert ".usage-expand__source" in source
    assert "usage-expand__notice" in source


def test_usage_view_range_selector_is_page_wide() -> None:
    source = USAGE_JS.read_text(encoding="utf-8")

    assert 'data-range="all"' in source
    assert "let _range" in source
    assert "_visibleSessions()" in source
    assert "Number(btn.dataset.range)" not in source
    # _renderMetrics dropped its unused `cost` parameter when usage.cost was
    # removed from the polling loop; usage.cost RPC still exists for CLI / chat
    # / HTTP consumers — the view just doesn't fetch it twice per poll.
    assert "_renderMetrics(_lastStatus)" in source
    assert "_lastCost" not in source
    assert "_rpc.call('usage.cost')" not in source
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
        "function _renderMetrics(status)",
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


def test_usage_expand_row_colspan_tracks_session_table_columns() -> None:
    source = USAGE_JS.read_text(encoding="utf-8")

    assert "const USAGE_SESSION_TABLE_COLUMNS" in source
    assert "USAGE_SESSION_TABLE_COLUMNS.forEach" in source
    assert "td.colSpan = USAGE_SESSION_TABLE_COLUMNS.length" in source
    assert "td.colSpan = (typeof cols" not in source
