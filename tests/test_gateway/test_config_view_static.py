import re
from pathlib import Path

BASE_CSS = Path("src/opensquilla/gateway/static/css/base.css")
COMPONENTS_CSS = Path("src/opensquilla/gateway/static/css/components.css")
CONFIG_JS = Path("src/opensquilla/gateway/static/js/views/config.js")
CONFIG_CSS = Path("src/opensquilla/gateway/static/css/views/config.css")


def _relative_luminance(hex_color: str) -> float:
    channels = [int(hex_color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92
        if channel <= 0.03928
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted(
        (_relative_luminance(foreground), _relative_luminance(background)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def _light_theme_token(name: str) -> str:
    css = BASE_CSS.read_text(encoding="utf-8")
    light_start = css.index('[data-theme="light"] {')
    light_rule = css[light_start : css.index("}", light_start)]
    match = re.search(rf"--{name}:\s*(#[0-9A-Fa-f]{{6}});", light_rule)
    assert match is not None
    return match.group(1)


def test_config_mode_toggle_keeps_touch_friendly_hit_area() -> None:
    css = CONFIG_CSS.read_text(encoding="utf-8")
    rule = css[css.index(".cfg-mode-btn {") : css.index("}", css.index(".cfg-mode-btn {"))]

    assert "min-height: 40px" in rule


def test_config_header_actions_keep_touch_friendly_hit_area() -> None:
    css = CONFIG_CSS.read_text(encoding="utf-8")
    rule = css[css.index(".cfg-btn {") : css.index("}", css.index(".cfg-btn {"))]

    assert "min-height: 40px" in rule


def test_config_primary_buttons_use_theme_contrast_token() -> None:
    css = CONFIG_CSS.read_text(encoding="utf-8")
    rule = css[
        css.index(".cfg-btn--primary {") : css.index(
            "}",
            css.index(".cfg-btn--primary {"),
        )
    ]

    assert "color: var(--accent-foreground)" in rule


def test_config_header_actions_stay_single_row_scrollable_on_mobile() -> None:
    components = COMPONENTS_CSS.read_text(encoding="utf-8")
    source = CONFIG_JS.read_text(encoding="utf-8")
    css = CONFIG_CSS.read_text(encoding="utf-8")

    assert ".mobile-action-strip {" in components
    assert ".mobile-action-strip.mobile-action-strip { flex-wrap: nowrap; }" in components
    assert "overflow-x: auto" in components
    assert "scrollbar-width: none" in components
    assert "-webkit-overflow-scrolling: touch" in components
    assert ".mobile-action-strip__button {" in components
    assert "width: var(--mobile-action-button-size, 40px)" in components
    assert ".mobile-action-strip__label {" in components
    assert "clip: rect(0 0 0 0)" in components

    assert 'cfg-stage__actions mobile-action-strip' in source
    assert 'cfg-mode-toggle mobile-action-strip__item' in source
    assert 'mobile-action-strip__button' in source
    assert 'mobile-action-strip__label' in source
    assert ".cfg-stage__actions .cfg-btn span" not in css


def test_config_help_buttons_keep_touch_friendly_hit_area() -> None:
    css = CONFIG_CSS.read_text(encoding="utf-8")
    rule = css[css.index(".cfg-help-btn {") : css.index("}", css.index(".cfg-help-btn {"))]

    assert "min-width: 40px" in rule
    assert "min-height: 40px" in rule
    assert "width: 40px" in rule
    assert "height: 40px" in rule


def test_config_search_input_keeps_touch_friendly_hit_area() -> None:
    css = CONFIG_CSS.read_text(encoding="utf-8")
    rule = css[css.index(".cfg-search-input {") : css.index("}", css.index(".cfg-search-input {"))]

    assert "min-height: 40px" in rule


def test_config_scalar_inputs_keep_touch_friendly_hit_area() -> None:
    css = CONFIG_CSS.read_text(encoding="utf-8")
    text_rule = css[css.index(".cfg-input-text {") : css.index("}", css.index(".cfg-input-text {"))]
    number_rule = css[
        css.index(".cfg-input-number {") : css.index("}", css.index(".cfg-input-number {"))
    ]

    assert "min-height: 40px" in text_rule
    assert "min-height: 40px" in number_rule


def test_config_switches_keep_touch_friendly_hit_area() -> None:
    css = CONFIG_CSS.read_text(encoding="utf-8")
    switch_rule = css[css.index(".cfg-switch {") : css.index("}", css.index(".cfg-switch {"))]
    track_rule = css[
        css.index(".cfg-switch-track {") : css.index("}", css.index(".cfg-switch-track {"))
    ]
    thumb_rule = css[
        css.index(".cfg-switch-thumb {") : css.index("}", css.index(".cfg-switch-thumb {"))
    ]
    checked_rule = css[
        css.index(".cfg-switch input:checked + .cfg-switch-track .cfg-switch-thumb {") : css.index(
            "}",
            css.index(".cfg-switch input:checked + .cfg-switch-track .cfg-switch-thumb {"),
        )
    ]

    assert "min-height: 40px" in switch_rule
    assert "width: 40px" in track_rule
    assert "height: 22px" in track_rule
    assert "width: 18px" in thumb_rule
    assert "height: 18px" in thumb_rule
    assert "transform: translateX(18px)" in checked_rule


def test_config_tabs_keep_touch_friendly_hit_area() -> None:
    css = CONFIG_CSS.read_text(encoding="utf-8")
    rule = css[css.index(".cfg-tab {") : css.index("}", css.index(".cfg-tab {"))]

    assert "min-height: 40px" in rule


def test_config_active_controls_use_accessible_light_theme_contrast() -> None:
    css = CONFIG_CSS.read_text(encoding="utf-8")
    mode_rule = css[
        css.index(".cfg-mode-btn.is-active {") : css.index(
            "}",
            css.index(".cfg-mode-btn.is-active {"),
        )
    ]
    tab_rule = css[
        css.index(".cfg-tab.is-active {") : css.index(
            "}",
            css.index(".cfg-tab.is-active {"),
        )
    ]
    action_rule = css[
        css.index(".cfg-object-action {") : css.index(
            "}",
            css.index(".cfg-object-action {"),
        )
    ]

    assert "color: var(--accent-foreground)" in mode_rule
    assert "color: var(--accent-hover)" in tab_rule
    assert "color: var(--accent-hover)" in action_rule
    assert (
        _contrast_ratio(_light_theme_token("accent-foreground"), _light_theme_token("accent"))
        >= 4.5
    )
    assert (
        _contrast_ratio(_light_theme_token("accent-hover"), _light_theme_token("bg-surface"))
        >= 4.5
    )


def test_config_toolbar_stacks_tabs_and_search_on_tablet_widths() -> None:
    css = CONFIG_CSS.read_text(encoding="utf-8")
    tablet = css.split("@media (max-width: 900px)", 1)[1]
    toolbar_rule = tablet.split(".cfg-toolbar {", 1)[1].split("}", 1)[0]
    search_rule = tablet.split(".cfg-search-wrap {", 1)[1].split("}", 1)[0]

    assert "align-items: stretch" in toolbar_rule
    assert "flex-direction: column" in toolbar_rule
    assert "flex-basis: auto" in search_rule
    assert "width: 100%" in search_rule
    assert "min-width: 0" in search_rule


def test_config_tabs_stay_single_row_scrollable_on_mobile() -> None:
    css = CONFIG_CSS.read_text(encoding="utf-8")
    mobile = css.split("@media (max-width: 760px)", 1)[1]
    tabs_rule = mobile.split(".cfg-tabs {", 1)[1].split("}", 1)[0]
    tab_rule = mobile.split(".cfg-tab {", 1)[1].split("}", 1)[0]

    assert "flex-wrap: nowrap" in tabs_rule
    assert "mask-image: linear-gradient(" in tabs_rule
    assert "transparent" in tabs_rule
    assert "#000 14px" in tabs_rule
    assert "#000 calc(100% - 44px)" in tabs_rule
    assert "overflow-x: auto" in tabs_rule
    assert "overflow-y: hidden" in tabs_rule
    assert "padding-inline: var(--sp-2) var(--sp-8)" in tabs_rule
    assert "scroll-snap-type: x proximity" in tabs_rule
    assert "scroll-padding-inline: var(--sp-2)" in tabs_rule
    assert "-webkit-mask-image: linear-gradient(" in tabs_rule
    assert "-webkit-overflow-scrolling: touch" in tabs_rule
    assert "flex: 0 0 auto" in tab_rule
    assert "min-height: 40px" in tab_rule
    assert "scroll-snap-align: start" in tab_rule


def test_config_object_summaries_wrap_on_phone_widths() -> None:
    css = CONFIG_CSS.read_text(encoding="utf-8")
    mobile = css.split("@media (max-width: 640px)", 1)[1]
    summary_rule = mobile.split(".cfg-object-summary {", 1)[1].split("}", 1)[0]

    assert "white-space: normal" in summary_rule
    assert "overflow-wrap: anywhere" in summary_rule
    assert "text-overflow: clip" in summary_rule


def test_config_field_labels_wrap_long_keys_on_phone_widths() -> None:
    css = CONFIG_CSS.read_text(encoding="utf-8")
    mobile = css.split("@media (max-width: 640px)", 1)[1]
    label_rule = mobile.split(
        ".config-field > .form-label,\n  .config-field__label-row > .form-label {",
        1,
    )[1].split("}", 1)[0]

    assert "max-width: 100%" in label_rule
    assert "overflow-wrap: anywhere" in label_rule
    assert "text-overflow: clip" in label_rule
    assert "white-space: normal" in label_rule
