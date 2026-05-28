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


def test_logs_mobile_toolbar_keeps_level_filters_compact() -> None:
    css = LOGS_CSS.read_text(encoding="utf-8")

    levels_start = css.index(".lg-levels__row {")
    levels_rule = css[levels_start : css.index("}", levels_start)]
    assert "flex-wrap: wrap" in levels_rule

    level_button_start = css.index(".lg-level-btn {")
    level_button_rule = css[
        level_button_start : css.index("}", level_button_start)
    ]
    assert "min-height: 40px" in level_button_rule

    mobile_start = css.index("@media (max-width: 720px)")
    mobile_block = css[mobile_start:]
    mobile_levels_wrap_start = mobile_block.index(".lg-levels {")
    mobile_levels_wrap_rule = mobile_block[
        mobile_levels_wrap_start : mobile_block.index("}", mobile_levels_wrap_start)
    ]
    mobile_levels_start = mobile_block.index(".lg-levels__row {")
    mobile_levels_rule = mobile_block[
        mobile_levels_start : mobile_block.index("}", mobile_levels_start)
    ]
    mobile_button_start = mobile_block.index(".lg-level-btn {")
    mobile_button_rule = mobile_block[
        mobile_button_start : mobile_block.index("}", mobile_button_start)
    ]

    assert "width: 100%" in mobile_levels_wrap_rule
    assert "flex-direction: column" in mobile_levels_wrap_rule
    assert "align-items: stretch" in mobile_levels_wrap_rule
    assert "gap: 6px" in mobile_levels_wrap_rule
    assert "width: 100%" in mobile_levels_rule
    assert "flex-wrap: wrap" in mobile_levels_rule
    assert "min-width: 0" in mobile_levels_rule
    assert "overflow: visible" in mobile_levels_rule
    assert "overflow-x: auto" not in mobile_levels_rule
    assert "mask-image: linear-gradient" not in mobile_levels_rule
    assert "padding-inline-end" not in mobile_levels_rule
    assert "flex: 0 0 auto" in mobile_button_rule
    assert ".lg-search-wrap" in mobile_block
    assert "width: 100%" in mobile_block
    assert "min-width: 0" in mobile_block
    assert ".lg-toggle { width: 100%; min-height: 40px; }" in mobile_block


def test_logs_auto_follow_toggle_keeps_touch_friendly_hit_area() -> None:
    css = LOGS_CSS.read_text(encoding="utf-8")

    toggle_rule = css[css.index(".lg-toggle {") : css.index("}", css.index(".lg-toggle {"))]
    track_start = css.index(".lg-toggle__track {")
    track_rule = css[track_start : css.index("}", track_start)]
    thumb_start = css.index(".lg-toggle__thumb {")
    thumb_rule = css[thumb_start : css.index("}", thumb_start)]

    assert "min-height: 40px" in toggle_rule
    assert "width: 40px; height: 22px" in track_rule
    assert "width: 18px; height: 18px" in thumb_rule
    assert "input:focus-visible + .lg-toggle__track" in css


def test_logs_search_keeps_touch_friendly_hit_area() -> None:
    css = LOGS_CSS.read_text(encoding="utf-8")
    start = css.index(".lg-search-input {")
    rule = css[start : css.index("}", start)]

    assert "min-height: 40px" in rule


def test_logs_header_actions_keep_touch_friendly_hit_area() -> None:
    css = LOGS_CSS.read_text(encoding="utf-8")
    start = css.index(".lg-stage__actions .btn {")
    rule = css[start : css.index("}", start)]

    assert "min-height: 40px" in rule


def test_logs_lines_wrap_at_words_before_breaking_long_tokens() -> None:
    css = LOGS_CSS.read_text(encoding="utf-8")

    line_start = css.index(".lg-line {")
    line_rule = css[line_start : css.index("}", line_start)]
    msg_start = css.index(".lg-line__msg {")
    msg_rule = css[msg_start : css.index("}", msg_start)]

    assert "white-space: pre-wrap" in line_rule
    assert "min-width: 0" in line_rule
    assert "word-break: break-all" not in line_rule
    assert "min-width: 0" in msg_rule
    assert "word-break: normal" in msg_rule
    assert "overflow-wrap: break-word" in msg_rule

    mobile_start = css.index("@media (max-width: 720px)")
    mobile_block = css[mobile_start:]
    mobile_msg_start = mobile_block.index(".lg-line__msg {")
    mobile_msg_rule = mobile_block[
        mobile_msg_start : mobile_block.index("}", mobile_msg_start)
    ]
    assert "grid-column: 1 / -1" in mobile_msg_rule


def test_config_mobile_tabs_scroll_instead_of_wrapping() -> None:
    css = CONFIG_CSS.read_text(encoding="utf-8")

    mobile_start = css.index("@media (max-width: 760px)")
    mobile_block = css[mobile_start:]
    assert ".cfg-tabs" in mobile_block
    assert "flex-wrap: nowrap" in mobile_block
    assert "overflow-x: auto" in mobile_block
    assert "overflow-y: hidden" in mobile_block
    assert "scroll-snap-type: x proximity" in mobile_block
    assert ".cfg-tab" in mobile_block
    assert "flex: 0 0 auto" in mobile_block
    assert "min-height: 40px" in mobile_block

    help_rule = css[css.index(".cfg-help-btn {") : css.index("}", css.index(".cfg-help-btn {"))]
    assert "min-width: 40px" in help_rule
    assert "min-height: 40px" in help_rule


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
