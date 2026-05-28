from pathlib import Path

APPROVALS_CSS = Path("src/opensquilla/gateway/static/css/views/approvals.css")
APPROVALS_JS = Path("src/opensquilla/gateway/static/js/views/approvals.js")


def test_approvals_radio_indicator_keeps_visible_keyboard_focus() -> None:
    css = APPROVALS_CSS.read_text(encoding="utf-8")
    indicator_start = css.index(".ap-radio__indicator {")
    indicator_rule = css[indicator_start : css.index("}", indicator_start)]
    focus_start = css.index(".ap-radio input:focus-visible + .ap-radio__indicator {")
    focus_rule = css[focus_start : css.index("}", focus_start)]

    assert "transition: border-color var(--transition), box-shadow var(--transition)" in (
        indicator_rule
    )
    assert "border-color: var(--accent)" in focus_rule
    assert "box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 22%, transparent)" in (
        focus_rule
    )


def test_approvals_radio_markup_keeps_indicator_after_input() -> None:
    js = APPROVALS_JS.read_text(encoding="utf-8")
    input_start = js.index('<input type="radio" name="ap-mode"')
    indicator_start = js.index('<span class="ap-radio__indicator"></span>')
    between_input_and_indicator = js[js.index("/>", input_start) + 2 : indicator_start]

    assert input_start < indicator_start
    assert between_input_and_indicator.strip() == ""


def test_approvals_active_radio_label_uses_accessible_accent_text() -> None:
    css = APPROVALS_CSS.read_text(encoding="utf-8")
    start = css.index(".ap-radio.is-active .ap-radio__label {")
    rule = css[start : css.index("}", start)]

    assert "color: var(--accent-hover)" in rule


def test_approval_card_metadata_wraps_long_runtime_identifiers() -> None:
    css = APPROVALS_CSS.read_text(encoding="utf-8")

    assert ".ap-card__meta span {" in css
    meta_start = css.index(".ap-card__meta {")
    meta_rule = css[meta_start : css.index("}", meta_start)]
    meta_item_start = css.index(".ap-card__meta span {")
    meta_item_rule = css[meta_item_start : css.index("}", meta_item_start)]
    code_start = css.index(".ap-card__meta code {")
    code_rule = css[code_start : css.index("}", code_start)]

    assert "min-width: 0" in meta_rule
    assert "overflow-wrap: anywhere" in meta_rule
    assert "max-width: 100%" in meta_item_rule
    assert "min-width: 0" in meta_item_rule
    assert "overflow-wrap: anywhere" in meta_item_rule
    assert "white-space: normal" in code_rule
    assert "overflow-wrap: anywhere" in code_rule
