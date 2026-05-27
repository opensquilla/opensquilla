import re
from pathlib import Path

CSS_DIR = Path("src/opensquilla/gateway/static/css")
COMPONENTS_CSS = Path("src/opensquilla/gateway/static/css/components.css")
VIEW_CSS_DIR = Path("src/opensquilla/gateway/static/css/views")


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


def _mix_srgb(foreground: str, foreground_percent: int, background: str) -> str:
    ratio = foreground_percent / 100
    foreground_channels = [int(foreground[index : index + 2], 16) for index in (1, 3, 5)]
    background_channels = [int(background[index : index + 2], 16) for index in (1, 3, 5)]
    mixed = [
        round(foreground_channel * ratio + background_channel * (1 - ratio))
        for foreground_channel, background_channel in zip(
            foreground_channels,
            background_channels,
            strict=True,
        )
    ]
    return "#" + "".join(f"{channel:02X}" for channel in mixed)


def test_non_onboarding_webui_css_does_not_use_negative_letter_spacing() -> None:
    offenders: list[str] = []
    for css_path in sorted(CSS_DIR.rglob("*.css")):
        if css_path.name == "setup.css":
            continue
        for line_no, line in enumerate(css_path.read_text(encoding="utf-8").splitlines(), 1):
            if (
                ("letter-spacing:" in line and "letter-spacing: -" in line)
                or ("--track" in line and ": -" in line)
            ):
                offenders.append(f"{css_path}:{line_no}:{line.strip()}")

    assert offenders == []


def test_shared_mono_stat_values_have_room_for_glyphs() -> None:
    css = COMPONENTS_CSS.read_text(encoding="utf-8")
    rule = css[css.index(".stat-value.mono {") : css.index("}", css.index(".stat-value.mono {"))]

    assert "line-height: 1.3" in rule


def test_header_search_inputs_keep_polished_hit_areas() -> None:
    search_rules = {
        "skills.css": ".sk-search-input {",
        "sessions.css": ".sess-search-input {",
        "cron.css": ".cron-search-input {",
        "logs.css": ".lg-search-input {",
        "config.css": ".cfg-search-input {",
    }

    for filename, selector in search_rules.items():
        css = (VIEW_CSS_DIR / filename).read_text(encoding="utf-8")
        rule = css[css.index(selector) : css.index("}", css.index(selector))]
        match = re.search(r"min-height:\s*(\d+)px", rule)
        assert match is not None, filename
        assert int(match.group(1)) >= 36, filename


def test_text_entry_inputs_keep_polished_hit_areas() -> None:
    component_css = COMPONENTS_CSS.read_text(encoding="utf-8")
    component_rule = component_css[
        component_css.index(".input {") : component_css.index("}", component_css.index(".input {"))
    ]
    overview_css = (VIEW_CSS_DIR / "overview.css").read_text(encoding="utf-8")
    overview_rule = overview_css[
        overview_css.index(".ov-field__input {") : overview_css.index(
            "}", overview_css.index(".ov-field__input {")
        )
    ]
    chat_css = (VIEW_CSS_DIR / "chat.css").read_text(encoding="utf-8")
    chat_rule_start = chat_css.rindex(".chat-textarea {")
    chat_rule = chat_css[chat_rule_start : chat_css.index("}", chat_rule_start)]

    assert "min-height: 36px" in component_rule
    assert "min-height: 40px" in overview_rule
    assert "min-height: 40px" in chat_rule


def test_empty_state_copy_stays_inside_mobile_cards() -> None:
    copy_rules = {
        "components.css": ".state-text {",
        "channels.css": ".ch-empty__msg {",
        "sessions.css": ".sess-empty__msg {",
        "cron.css": ".cron-empty__msg {",
    }

    for filename, selector in copy_rules.items():
        css_path = COMPONENTS_CSS if filename == "components.css" else VIEW_CSS_DIR / filename
        css = css_path.read_text(encoding="utf-8")
        rule = css[css.index(selector) : css.index("}", css.index(selector))]

        assert "width: 100%" in rule, filename
        assert "max-width:" in rule, filename
        assert "box-sizing: border-box" in rule, filename
        assert "overflow-wrap: anywhere" in rule, filename


def test_empty_state_svg_art_boxes_drop_inline_baseline() -> None:
    art_rules = {
        "overview.css": (".ov-recent__empty-icon {", ".ov-recent__empty-icon svg {"),
        "channels.css": (".ch-empty__art {", ".ch-empty__art svg {"),
        "sessions.css": (".sess-empty__art {", ".sess-empty__art svg {"),
        "cron.css": (".cron-empty__clock {", ".cron-empty__clock svg {"),
    }

    for filename, (box_selector, svg_selector) in art_rules.items():
        css = (VIEW_CSS_DIR / filename).read_text(encoding="utf-8")
        box_rule = css[css.index(box_selector) : css.index("}", css.index(box_selector))]
        svg_rule = css[css.index(svg_selector) : css.index("}", css.index(svg_selector))]

        assert "line-height: 1" in box_rule, filename
        assert "display: block" in svg_rule, filename


def test_header_search_icons_drop_inline_svg_baseline() -> None:
    css = (VIEW_CSS_DIR / "config.css").read_text(encoding="utf-8")
    box_selector = ".cfg-search-icon {"
    svg_selector = ".cfg-search-icon svg {"
    box_rule = css[css.index(box_selector) : css.index("}", css.index(box_selector))]
    svg_rule = css[css.index(svg_selector) : css.index("}", css.index(svg_selector))]

    assert "line-height: 1" in box_rule
    assert "display: block" in svg_rule


def test_light_theme_dim_text_meets_accessible_contrast() -> None:
    css = (CSS_DIR / "base.css").read_text(encoding="utf-8")
    light_start = css.index('[data-theme="light"] {')
    light_rule = css[light_start : css.index("}", light_start)]

    bg = re.search(r"--bg:\s*(#[0-9A-Fa-f]{6});", light_rule)
    surface = re.search(r"--bg-surface:\s*(#[0-9A-Fa-f]{6});", light_rule)
    dim = re.search(r"--text-dim:\s*(#[0-9A-Fa-f]{6});", light_rule)
    accent = re.search(r"--accent:\s*(#[0-9A-Fa-f]{6});", light_rule)
    accent_foreground = re.search(r"--accent-foreground:\s*(#[0-9A-Fa-f]{6});", light_rule)
    assert bg is not None
    assert surface is not None
    assert dim is not None
    assert accent is not None
    assert accent_foreground is not None

    assert _contrast_ratio(dim.group(1), bg.group(1)) >= 4.5
    assert _contrast_ratio(dim.group(1), surface.group(1)) >= 4.5
    assert _contrast_ratio(accent.group(1), bg.group(1)) >= 4.5
    assert _contrast_ratio(accent_foreground.group(1), accent.group(1)) >= 4.5


def test_light_theme_status_tokens_meet_accessible_tinted_contrast() -> None:
    css = (CSS_DIR / "base.css").read_text(encoding="utf-8")
    light_start = css.index('[data-theme="light"] {')
    light_rule = css[light_start : css.index("}", light_start)]

    status_tokens = {
        "ok": 10,
        "warn": 14,
        "danger": 14,
        "info": 14,
    }
    elevated = re.search(r"--bg-elevated:\s*(#[0-9A-Fa-f]{6});", light_rule)
    assert elevated is not None

    for token, tint in status_tokens.items():
        color = re.search(rf"--{token}:\s*(#[0-9A-Fa-f]{{6}});", light_rule)
        assert color is not None
        pill_background = _mix_srgb(color.group(1), tint, elevated.group(1))
        bg = re.search(r"--bg:\s*(#[0-9A-Fa-f]{6});", light_rule)
        assert bg is not None
        body_background = _mix_srgb(color.group(1), tint, bg.group(1))

        assert _contrast_ratio(color.group(1), pill_background) >= 4.5, token
        assert _contrast_ratio(color.group(1), body_background) >= 4.5, token

    danger = re.search(r"--danger:\s*(#[0-9A-Fa-f]{6});", light_rule)
    bg = re.search(r"--bg:\s*(#[0-9A-Fa-f]{6});", light_rule)
    assert danger is not None
    assert bg is not None
    log_line_background = _mix_srgb(danger.group(1), 4, bg.group(1))
    error_label_background = _mix_srgb(danger.group(1), 14, log_line_background)

    assert _contrast_ratio(danger.group(1), error_label_background) >= 4.5


def test_dark_theme_dim_and_status_tokens_meet_accessible_contrast() -> None:
    css = (CSS_DIR / "base.css").read_text(encoding="utf-8")
    dark_start = css.index('[data-theme="dark"], :root {')
    dark_rule = css[dark_start : css.index("}", dark_start)]

    bg = re.search(r"--bg:\s*(#[0-9A-Fa-f]{6});", dark_rule)
    surface = re.search(r"--bg-surface:\s*(#[0-9A-Fa-f]{6});", dark_rule)
    elevated = re.search(r"--bg-elevated:\s*(#[0-9A-Fa-f]{6});", dark_rule)
    dim = re.search(r"--text-dim:\s*(#[0-9A-Fa-f]{6});", dark_rule)
    assert bg is not None
    assert surface is not None
    assert elevated is not None
    assert dim is not None

    assert _contrast_ratio(dim.group(1), bg.group(1)) >= 4.5
    assert _contrast_ratio(dim.group(1), surface.group(1)) >= 4.5
    assert _contrast_ratio(dim.group(1), elevated.group(1)) >= 4.5

    for token in ("danger", "info"):
        color = re.search(rf"--{token}:\s*(#[0-9A-Fa-f]{{6}});", dark_rule)
        assert color is not None
        tinted_background = _mix_srgb(color.group(1), 14, elevated.group(1))

        assert _contrast_ratio(color.group(1), tinted_background) >= 4.5, token


def test_primary_buttons_use_theme_contrast_token() -> None:
    css = COMPONENTS_CSS.read_text(encoding="utf-8")
    rule = css[css.index(".btn--primary {") : css.index("}", css.index(".btn--primary {"))]

    assert "color: var(--accent-foreground)" in rule
