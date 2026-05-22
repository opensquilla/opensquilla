from __future__ import annotations

from pathlib import Path

LOGS_JS = Path("src/opensquilla/gateway/static/js/views/logs.js")
LOGS_CSS = Path("src/opensquilla/gateway/static/css/views/logs.css")
CONFIG_JS = Path("src/opensquilla/gateway/static/js/views/config.js")
CONFIG_CSS = Path("src/opensquilla/gateway/static/css/views/config.css")
CONFIG_EXAMPLE = Path("opensquilla.toml.example")


def test_logs_view_describes_configurable_debug_logging() -> None:
    source = LOGS_JS.read_text(encoding="utf-8")

    assert "Gateway file logging is configurable" in source
    assert "logs.status" in source
    assert "Raw turn-call capture is enabled by" in source
    assert "opensquilla diagnostics on --raw" in source
    assert "OPENSQUILLA_LOG_DIR" in source
    assert "OPENSQUILLA_TURN_CALL_LOG=1" in source


def test_config_view_explains_debug_file_logging_fields() -> None:
    source = CONFIG_JS.read_text(encoding="utf-8")

    assert "'debug'" in source
    assert "Security-sensitive developer mode" in source
    assert "'diagnostics_enabled'" in source
    assert "Default standard diagnostics mode" in source
    assert "'log_file_enabled'" in source
    assert "'log_level'" in source
    assert "'log_file_max_bytes'" in source
    assert "'log_file_backup_count'" in source


def test_logs_mobile_toolbar_wraps_controls() -> None:
    css = LOGS_CSS.read_text(encoding="utf-8")

    levels_start = css.index(".lg-levels__row {")
    levels_rule = css[levels_start : css.index("}", levels_start)]
    assert "flex-wrap: wrap" in levels_rule

    level_button_start = css.index(".lg-level-btn {")
    level_button_rule = css[
        level_button_start : css.index("}", level_button_start)
    ]
    assert "min-height: 32px" in level_button_rule

    mobile_start = css.index("@media (max-width: 720px)")
    mobile_block = css[mobile_start:]
    assert ".lg-search-wrap" in mobile_block
    assert "width: 100%" in mobile_block
    assert "min-width: 0" in mobile_block


def test_config_mobile_tabs_wrap_instead_of_clipping() -> None:
    css = CONFIG_CSS.read_text(encoding="utf-8")

    mobile_start = css.index("@media (max-width: 760px)")
    mobile_block = css[mobile_start:]
    assert ".cfg-tabs" in mobile_block
    assert "flex-wrap: wrap" in mobile_block
    assert "overflow-x: visible" in mobile_block
    assert ".cfg-tab" in mobile_block
    assert "min-height: 36px" in mobile_block

    help_rule = css[css.index(".cfg-help-btn {") : css.index("}", css.index(".cfg-help-btn {"))]
    assert "min-width: 32px" in help_rule
    assert "min-height: 32px" in help_rule


def test_example_config_lists_debug_file_logging_controls() -> None:
    source = CONFIG_EXAMPLE.read_text(encoding="utf-8")

    assert "log_file_enabled" in source
    assert "log_level" in source
    assert "log_file_max_bytes" in source
    assert "log_file_backup_count" in source
    assert "diagnostics_enabled enables standard diagnostics" in source
    assert "OPENSQUILLA_TURN_CALL_LOG=1" in source


def test_logs_poll_does_not_overlap_or_fail_silently() -> None:
    source = LOGS_JS.read_text(encoding="utf-8")

    assert "let _pollInFlight = false;" in source
    assert "let _pollErrorShown = false;" in source
    start = source.index("async function _poll()")
    end = source.index("  function _guessLevel", start)
    body = source[start:end]

    assert "if (!_el || _pollInFlight) return;" in body
    assert "_pollInFlight = true;" in body
    assert "Log refresh failed" in body
    assert "_pollErrorShown = true;" in body
    assert "_pollInFlight = false;" in body
    assert "finally" in body


def test_config_view_resets_mode_and_preserves_unsaved_yaml_draft() -> None:
    source = CONFIG_JS.read_text(encoding="utf-8")

    render_start = source.index("function render(el)")
    render_end = source.index("  function destroy()", render_start)
    render_body = source[render_start:render_end]
    destroy_start = render_end
    destroy_end = source.index("  async function _loadData()", destroy_start)
    destroy_body = source[destroy_start:destroy_end]

    assert "_setMode(_mode);" in render_body
    assert "_mode = 'form';" in destroy_body
    assert "let _yamlDraft = '';" in source
    assert "let _yamlDirty = false;" in source
    assert "_bindYamlDraftTracking();" in source
    assert "_yamlDraft = e.target.value;" in source
    assert "_yamlDirty = _yamlDraft !== _yamlText;" in source
    assert "_yamlDirty ? _yamlDraft : _yamlText" in source
