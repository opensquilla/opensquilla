"""Static smoke tests for Usage view cost provenance display."""

from pathlib import Path

USAGE_JS = Path("src/opensquilla/gateway/static/js/views/usage.js")
USAGE_CSS = Path("src/opensquilla/gateway/static/css/views/usage.css")
COMPONENTS_CSS = Path("src/opensquilla/gateway/static/css/components.css")


def test_usage_view_renders_cost_source_badges_and_exports_fields() -> None:
    source = USAGE_JS.read_text(encoding="utf-8")

    assert "_renderCostSourceBadge(row)" in source
    assert "{ key: 'cost_source', label: 'Source' }" in source
    assert "billed_cost_usd" in source
    assert "estimated_cost_usd" in source
    assert "missing_cost_entries" in source
    assert "cost_ephemeral" in source


def test_usage_sessions_default_to_modified_time_sort() -> None:
    source = USAGE_JS.read_text(encoding="utf-8")

    assert "let _sortCol = 'updated_at';" in source
    assert "{ key: 'updated_at', label: 'Modified' }" in source
    assert "case 'updated_at':" in source
    assert "return _sessionTimestamp(row) || 0;" in source
    assert "'updated_at', 'input_tokens'" in source
    assert "const modified = timestamp != null ? UI.relTime(timestamp) : '—';" in source


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


def test_usage_model_card_identifiers_wrap_inside_mobile_cards() -> None:
    source = USAGE_CSS.read_text(encoding="utf-8")
    provider_start = source.index(".usage-model-card__provider {")
    provider_rule = source[provider_start : source.index("}", provider_start)]
    name_start = source.index(".usage-model-card__name {")
    name_rule = source[name_start : source.index("}", name_start)]

    for rule in (provider_rule, name_rule):
        assert "max-width: 100%" in rule
        assert "min-width: 0" in rule
        assert "overflow-wrap: anywhere" in rule

    assert "white-space: normal" in name_rule
    assert "text-overflow: clip" in name_rule


def test_usage_view_has_cost_source_styles() -> None:
    source = USAGE_CSS.read_text(encoding="utf-8")

    assert ".usage-source--provider_billed" in source
    # New pro-rated style for the billed-but-split breakdown items.
    assert ".usage-source--provider_billed_prorated" in source
    assert ".usage-source--opensquilla_estimate" in source
    assert ".usage-source--mixed" in source
    assert ".usage-source--unavailable" in source
    assert ".usage-source--ephemeral" in source


def test_usage_segmented_controls_keep_touch_friendly_hit_areas() -> None:
    source = USAGE_CSS.read_text(encoding="utf-8")
    currency_start = source.index(".usage-currency__btn {")
    seg_start = source.index(".usage-seg, .usage-range__btn {")
    currency_rule = source[
        currency_start : source.index("}", currency_start)
    ]
    seg_rule = source[seg_start : source.index("}", seg_start)]

    assert "min-height: 40px" in currency_rule
    assert "min-height: 40px" in seg_rule


def test_usage_active_segmented_controls_use_theme_contrast_token() -> None:
    source = USAGE_CSS.read_text(encoding="utf-8")
    currency_start = source.index(".usage-currency__btn.is-active {")
    seg_start = source.index(".usage-seg.is-active {")
    currency_rule = source[currency_start : source.index("}", currency_start)]
    seg_rule = source[seg_start : source.index("}", seg_start)]

    assert "color: var(--accent-foreground)" in currency_rule
    assert "color: var(--accent-foreground)" in seg_rule


def test_usage_header_actions_stay_single_row_scrollable_on_mobile() -> None:
    components = COMPONENTS_CSS.read_text(encoding="utf-8")
    js = USAGE_JS.read_text(encoding="utf-8")
    source = USAGE_CSS.read_text(encoding="utf-8")

    mobile_start = source.rindex("@media (max-width: 720px)")
    mobile_block = source[mobile_start:]

    assert ".mobile-action-strip {" in components
    assert ".mobile-action-strip.mobile-action-strip { flex-wrap: nowrap; }" in components
    assert ".mobile-action-strip__button {" in components
    assert ".mobile-action-strip__label {" in components
    assert 'usage-stage__actions mobile-action-strip' in js
    assert 'usage-currency mobile-action-strip__item' in js
    assert 'mobile-action-strip__button' in js
    assert 'mobile-action-strip__label' in js
    assert "--mobile-action-button-size: 44px" in source
    assert ".usage-stage__actions .btn span" not in source

    button_start = mobile_block.rindex(".usage-stage__actions .btn {")
    button_rule = mobile_block[button_start : mobile_block.index("}", button_start)]
    assert "background: var(--bg-surface)" in button_rule
    assert "border-color: var(--border)" in button_rule


def test_usage_chart_labels_wrap_on_mobile() -> None:
    source = USAGE_CSS.read_text(encoding="utf-8")

    mobile_start = source.rindex("@media (max-width: 720px)")
    mobile_block = source[mobile_start:]
    row_start = mobile_block.index(".usage-bar-row {")
    row_rule = mobile_block[row_start : mobile_block.index("}", row_start)]
    label_start = mobile_block.index(".usage-bar-row__label {")
    label_rule = mobile_block[label_start : mobile_block.index("}", label_start)]

    assert "grid-template-columns: minmax(0, 1fr) auto" in row_rule
    assert "align-items: start" in row_rule
    assert "row-gap: 6px" in row_rule
    assert "grid-column: 1 / -1" in label_rule
    assert "max-width: 100%" in label_rule
    assert "white-space: normal" in label_rule
    assert "overflow-wrap: anywhere" in label_rule
    assert "text-overflow: clip" in label_rule


def test_usage_empty_table_state_stays_visible_on_mobile() -> None:
    source = USAGE_CSS.read_text(encoding="utf-8")

    empty_start = source.index(".usage-empty-row .state {")
    empty_rule = source[empty_start : source.index("}", empty_start)]
    mobile_start = source.index("@media (max-width: 720px)")
    mobile_block = source[mobile_start:]
    mobile_empty_start = mobile_block.index(".usage-empty-row .state {")
    mobile_empty_rule = mobile_block[
        mobile_empty_start : mobile_block.index("}", mobile_empty_start)
    ]

    assert "width: min(100%, 520px)" in empty_rule
    assert "margin-inline: auto" in empty_rule
    assert "width: min(100%, calc(100vw - 64px))" in mobile_empty_rule
    assert "margin-inline: 0" in mobile_empty_rule


def test_usage_table_scroll_edge_has_visual_affordance() -> None:
    source = USAGE_CSS.read_text(encoding="utf-8")

    wrap_start = source.index(".usage-table-wrap {")
    wrap_rule = source[wrap_start : source.index("}", wrap_start)]
    tablet_start = source.index("@media (max-width: 900px)")
    next_mobile_start = source.index("@media (max-width: 720px)", tablet_start)
    tablet_block = source[tablet_start:next_mobile_start]
    fade_start = tablet_block.index(".usage-table-wrap::after {")
    fade_rule = tablet_block[fade_start : tablet_block.index("}", fade_start)]

    assert "position: relative" in wrap_rule
    assert "overflow-x: auto" in wrap_rule
    assert 'content: ""' in fade_rule
    assert "position: absolute" in fade_rule
    assert "right: 0" in fade_rule
    assert "pointer-events: none" in fade_rule
    assert "linear-gradient" in fade_rule
    assert "box-shadow" in fade_rule


def test_usage_session_table_becomes_labeled_cards_on_mobile() -> None:
    js = USAGE_JS.read_text(encoding="utf-8")
    source = USAGE_CSS.read_text(encoding="utf-8")

    mobile_start = source.rindex("@media (max-width: 720px)")
    mobile_block = source[mobile_start:]

    for label in [
        "Session",
        "Modified",
        "Input",
        "Output",
        "Cache R",
        "Cache W",
        "Cost",
        "Source",
        "Model",
    ]:
        assert f'data-label="{label}"' in js

    assert ".usage-table-wrap { overflow-x: hidden; }" in mobile_block
    assert ".usage-table-wrap::after { content: none; }" in mobile_block
    assert ".usage-table thead {" in mobile_block
    assert "clip: rect(0 0 0 0)" in mobile_block
    assert "clip-path: inset(50%)" in mobile_block
    assert ".usage-table thead tr," in mobile_block
    assert ".usage-table tbody {" in mobile_block
    assert "display: grid" in mobile_block
    assert ".usage-table tbody td {" in mobile_block
    assert "grid-template-columns: minmax(72px, 0.34fr) minmax(0, 1fr)" in mobile_block
    assert "content: attr(data-label)" in mobile_block
    assert "usage-expand-cell" in js
    assert ".usage-expand-cell::before" in mobile_block


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
