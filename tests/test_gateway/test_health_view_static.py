from __future__ import annotations

from pathlib import Path

APP_JS = Path("src/opensquilla/gateway/static/js/app.js")
OVERVIEW_JS = Path("src/opensquilla/gateway/static/js/views/overview.js")
OVERVIEW_CSS = Path("src/opensquilla/gateway/static/css/views/overview.css")
HEALTH_JS = Path("src/opensquilla/gateway/static/js/views/health.js")
HEALTH_CSS = Path("src/opensquilla/gateway/static/css/views/health.css")
INDEX_HTML = Path("src/opensquilla/gateway/templates/index.html")


def test_health_view_is_registered_and_loaded() -> None:
    app = APP_JS.read_text(encoding="utf-8")
    index = INDEX_HTML.read_text(encoding="utf-8")

    assert "HealthView.render" in app
    assert 'data-path="/health"' in app
    assert "views/health.js" in index
    assert "views/health.css" in index


def test_health_view_calls_doctor_status_and_renders_fix_steps() -> None:
    source = HEALTH_JS.read_text(encoding="utf-8")

    assert "_rpc.call('doctor.status', { agentId: 'main', deep: true })" in source
    assert "fixSteps" in source
    assert "restartRequired" in source
    assert "health-finding" in source


def test_overview_surfaces_readiness_summary() -> None:
    source = OVERVIEW_JS.read_text(encoding="utf-8")

    assert "doctor.status" in source
    assert "ov-health" in source
    assert 'data-nav="/health"' in source


def test_overview_humanizes_readiness_status() -> None:
    source = OVERVIEW_JS.read_text(encoding="utf-8")
    css = OVERVIEW_CSS.read_text(encoding="utf-8")
    health_tile_start = source.index('id="ov-health-status"')
    health_tile = source[health_tile_start - 120 : health_tile_start + 180]

    assert "function _readinessStatusLabel(status)" in source
    assert "action_required: 'Action required'" in source
    assert "_readinessStatusLabel(report.status ?? 'unknown')" in source
    assert "ov-stat__value--mono" not in health_tile
    assert "ov-stat__value--status" in health_tile
    value_rule = css.split(".ov-stat__value {", 1)[1].split("}", 1)[0]
    mono_rule = css.split(".ov-stat__value--mono", 1)[1].split("}", 1)[0]
    status_rule = css.split(".ov-stat__value--status", 1)[1].split("}", 1)[0]
    assert "line-height: 1.18" in value_rule
    assert "line-height: 1.3" in mono_rule
    assert "line-height: 1.2" in status_rule
    assert "white-space: nowrap" in status_rule


def test_health_css_defines_responsive_finding_rows() -> None:
    css = HEALTH_CSS.read_text(encoding="utf-8")

    assert ".health-layout" in css
    assert ".health-finding" in css
    assert "@media (max-width: 760px)" in css


def test_health_mobile_refresh_button_keeps_visible_width() -> None:
    css = HEALTH_CSS.read_text(encoding="utf-8")
    mobile = css.split("@media (max-width: 760px)", 1)[1]
    refresh_rule = mobile.split(".health-stage__header .btn", 1)[1].split("}", 1)[0]

    assert "align-self: flex-start" in refresh_rule
    assert "width: auto" in refresh_rule
    assert "width: 100%" not in refresh_rule


def test_health_status_numerals_have_breathing_room() -> None:
    css = HEALTH_CSS.read_text(encoding="utf-8")
    score_rule = css.split(".health-score strong {", 1)[1].split("}", 1)[0]
    count_rule = css.split(".health-count strong {", 1)[1].split("}", 1)[0]

    assert "line-height: 1.12" in score_rule
    assert "line-height: 1.12" in count_rule


def test_health_view_uses_status_visual_system() -> None:
    source = HEALTH_JS.read_text(encoding="utf-8")
    css = HEALTH_CSS.read_text(encoding="utf-8")

    assert "health-status__rail" in source
    assert "health-score" in source
    assert "health-finding__dot" in source
    assert "health-evidence" in source
    assert "health-step__number" in source
    assert ".health-status__rail" in css
    assert ".health-finding__dot" in css
    assert ".health-evidence" in css
    assert ".health-step__number" in css


def test_health_view_groups_findings_by_actionability() -> None:
    source = HEALTH_JS.read_text(encoding="utf-8")
    css = HEALTH_CSS.read_text(encoding="utf-8")

    assert "Needs action" in source
    assert "Degraded capabilities" in source
    assert "Optional setup" in source
    assert "Ready checks" in source
    assert "health-finding-group" in source
    assert ".health-finding-group" in css


def test_health_view_keeps_unknown_severity_findings_visible() -> None:
    source = HEALTH_JS.read_text(encoding="utf-8")

    assert "function _findingGroupKind" in source
    assert "const impact = _impactValue(finding);" in source
    assert "if (impact === 'blocks_ready') return 'action';" in source
    assert "if (impact === 'degrades') return 'degraded';" in source
    assert "function _impactValue" in source
    assert "if (severity === 'warn') return 'degrades';" in source
    assert "if (severity === 'info') return 'optional';" in source
    assert "return 'none';" in source


def test_health_view_labels_degraded_ready_state_without_hiding_warnings() -> None:
    source = HEALTH_JS.read_text(encoding="utf-8")

    assert "Ready with warnings" in source
    assert "if (ready && status === 'degraded')" in source


def test_health_view_fallback_report_uses_readiness_impact_schema() -> None:
    source = HEALTH_JS.read_text(encoding="utf-8")

    assert "impactCounts: { blocks_ready: 1, degrades: 0, optional: 0, none: 0 }" in source
    assert "readinessImpact: 'blocks_ready'" in source
    assert "gateway.unavailable" in source


def test_health_view_remote_unavailable_does_not_offer_local_start() -> None:
    source = HEALTH_JS.read_text(encoding="utf-8")

    assert "function _gatewayUnavailableFixSteps" in source
    assert "function _isLocalGatewayUrl" in source
    assert "Run local doctor" in source
    assert "Inspect remote gateway" in source
    assert "Repair remote deployment" in source
    assert "Start local gateway" in source
    assert "_gatewayUnavailableFixSteps(gatewayUrl)" in source
    assert "opensquilla gateway status --gateway ${_shellArg(gatewayUrl)} --json" in source
    assert "opensquilla gateway status --listen ${target.host}" not in source
    assert "` --gateway ${_shellArg(gatewayUrl)}`" in source
    assert "opensquilla doctor${doctorTarget}${configTarget} --json" in source


def test_health_view_labels_recovery_and_optional_steps_differently() -> None:
    source = HEALTH_JS.read_text(encoding="utf-8")
    css = HEALTH_CSS.read_text(encoding="utf-8")

    assert "Recovery steps" in source
    assert "Optional setup steps" in source
    assert "Recovery requires restart" in source
    assert ">Restart required<" not in source
    assert "restartRequired</span>" not in source
    assert "_stepsHeading" in source
    assert "const kind = _findingGroupKind(finding);" in source
    assert "_renderSteps(finding.fixSteps || [], kind)" in source
    assert ".health-steps__heading" in css


def test_health_view_prioritizes_impact_counts_in_summary_tiles() -> None:
    source = HEALTH_JS.read_text(encoding="utf-8")
    css = HEALTH_CSS.read_text(encoding="utf-8")

    assert "const impactCounts = report.impactCounts || _impactCountsFromSeverity" in source
    assert "_countTile('Needs action', impactCounts.blocks_ready || 0, 'blocks_ready')" in source
    assert "_countTile('Degraded', impactCounts.degrades || 0, 'degrades')" in source
    assert "_countTile('Optional', impactCounts.optional || 0, 'optional')" in source
    assert "_countTile('Ready', impactCounts.none || 0, 'none')" in source
    assert "function _impactCountsFromSeverity" in source
    assert ".health-count.is-blocks_ready::before" in css
    assert ".health-count.is-degrades::before" in css
    assert ".health-count.is-optional::before" in css
    assert ".health-count.is-none::before" in css


def test_health_view_surfaces_report_context_for_config_and_agent() -> None:
    source = HEALTH_JS.read_text(encoding="utf-8")
    css = HEALTH_CSS.read_text(encoding="utf-8")
    index = INDEX_HTML.read_text(encoding="utf-8")

    assert "function _renderReportContext" in source
    assert "function _gatewayContextUrl" in source
    assert 'data-config-path="{{ config_path }}"' in index
    assert "report.gatewayUrl" in source
    assert "report.configPath" in source
    assert "report.requestedConfigPath" in source
    assert "Requested config" in source
    assert "report.agentId" in source
    assert "health-report-context" in source
    assert "health-report-context__item" in source
    assert "health-report-context__value" in source
    assert ".health-report-context" in css


def test_health_report_context_wraps_long_paths_on_mobile() -> None:
    css = HEALTH_CSS.read_text(encoding="utf-8")
    source = HEALTH_JS.read_text(encoding="utf-8")

    assert "class=\"health-report-context__item\"" in source
    assert "class=\"health-report-context__value\"" in source
    context_item = css.split(".health-report-context__item", 1)[1].split("}", 1)[0]
    context_value = css.split(".health-report-context__value", 1)[1].split("}", 1)[0]
    mobile_context = css.split("@media (max-width: 480px)", 1)[1]
    mobile_context_item = mobile_context.split(".health-report-context__item", 1)[1].split(
        "}", 1
    )[0]

    assert "display: inline-grid" in context_item
    assert "grid-template-columns: auto minmax(0, 1fr)" in context_item
    assert "min-width: 0" in context_value
    assert "overflow-wrap: anywhere" in context_value
    assert "word-break: break-word" in context_value
    assert "grid-template-columns: minmax(0, 1fr)" in mobile_context_item
    assert "width: 100%" in mobile_context_item


def test_health_runtime_diagnostics_wrap_inside_cards() -> None:
    css = HEALTH_CSS.read_text(encoding="utf-8")

    wrapping_selectors = (
        ".health-score__summary",
        ".health-finding__meta",
        ".health-finding__title",
        ".health-finding__detail",
        ".health-evidence",
        ".health-evidence span",
        ".health-step__command",
    )

    for selector in wrapping_selectors:
        rule = css.split(f"{selector} {{", 1)[1].split("}", 1)[0]
        assert "min-width: 0" in rule
        assert "overflow-wrap: anywhere" in rule


def test_health_view_scopes_local_fallback_commands_to_bootstrap_config() -> None:
    source = HEALTH_JS.read_text(encoding="utf-8")

    assert "function _bootstrapConfigPath" in source
    assert "function _usesDefaultGatewayUrl" in source
    assert "function _configOption" in source
    assert (
        "const useConfigTarget = _usesDefaultGatewayUrl(gatewayUrl) "
        "&& Boolean(_bootstrapConfigPath());"
    ) in source
    assert (
        "const doctorTarget = useConfigTarget ? '' "
        ": (gatewayUrl ? ` --gateway ${_shellArg(gatewayUrl)}` : '');"
    ) in source
    assert "const targetArgs = useConfigTarget ? '' : bindArgs;" in source
    assert "command: `opensquilla doctor${doctorTarget}${configTarget} --json`" in source
    assert "command: `opensquilla gateway start${targetArgs}${configTarget}`" in source
    assert "command: `opensquilla gateway status${targetArgs} --json${configTarget}`" in source


def test_health_view_treats_ipv6_loopback_gateway_as_local() -> None:
    source = HEALTH_JS.read_text(encoding="utf-8")

    assert "['127.0.0.1', '::1', 'localhost', '0.0.0.0'].includes(target.host)" in source
    assert "if (host.startsWith('[') && host.endsWith(']')) host = host.slice(1, -1);" in source


def test_health_view_shows_readiness_impact_as_a_first_class_badge() -> None:
    source = HEALTH_JS.read_text(encoding="utf-8")
    css = HEALTH_CSS.read_text(encoding="utf-8")

    assert "function _impactValue" in source
    assert "function _impactLabel" in source
    assert "class=\"health-impact\"" in source
    assert "_impactLabel(impact)" in source
    assert "blocks_ready: 'Blocks readiness'" in source
    assert ".health-impact" in css


def test_health_view_marks_incomplete_diagnostics_explicitly() -> None:
    source = HEALTH_JS.read_text(encoding="utf-8")
    css = HEALTH_CSS.read_text(encoding="utf-8")

    assert "function _findingBadges" in source
    assert ".diagnostic.incomplete" in source
    assert "Diagnostics incomplete" in source
    assert "health-chip--diagnostic" in source
    assert ".health-chip--diagnostic" in css


def test_health_view_marks_pending_repairs_explicitly() -> None:
    source = HEALTH_JS.read_text(encoding="utf-8")
    css = HEALTH_CSS.read_text(encoding="utf-8")

    assert ".repair.pending" in source
    assert "Repair pending" in source
    assert "health-chip--repair" in source
    assert ".health-chip--repair" in css


def test_health_view_marks_config_mismatch_explicitly() -> None:
    source = HEALTH_JS.read_text(encoding="utf-8")
    css = HEALTH_CSS.read_text(encoding="utf-8")

    assert "gateway.config.mismatch" in source
    assert "Config mismatch" in source
    assert "health-chip--config" in source
    assert ".health-chip--config" in css


def test_health_view_formats_evidence_for_operator_readability() -> None:
    source = HEALTH_JS.read_text(encoding="utf-8")

    assert "function _visibleEvidenceEntries" in source
    assert "function _evidenceLabel" in source
    assert "restart_required" in source
    assert "replace(/([a-z0-9])([A-Z])/g" in source


def test_health_view_makes_recovery_commands_copyable() -> None:
    source = HEALTH_JS.read_text(encoding="utf-8")
    css = HEALTH_CSS.read_text(encoding="utf-8")

    assert "data-health-copy-command" in source
    assert "navigator.clipboard.writeText" in source
    assert "Copied command" in source
    assert "health-step__copy" in source
    assert ".health-step__copy" in css
    copy_start = css.index(".health-step__copy {")
    copy_rule = css[copy_start : css.index("}", copy_start)]
    assert "height: 40px" in copy_rule
    assert "width: 40px" in copy_rule

    mobile_start = css.index("@media (max-width: 480px)")
    mobile_css = css[mobile_start:]
    command_start = mobile_css.index(".health-step__command {")
    command_rule = mobile_css[command_start : mobile_css.index("}", command_start)]
    command_code_start = mobile_css.index(".health-step__command code {")
    command_code_rule = mobile_css[
        command_code_start : mobile_css.index("}", command_code_start)
    ]
    assert "width: 100%" in command_rule
    assert "flex: 1 1 auto" in command_code_rule
    assert "min-width: 0" in command_code_rule
