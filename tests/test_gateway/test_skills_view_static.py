from pathlib import Path

SKILLS_JS = Path("src/opensquilla/gateway/static/js/views/skills.js")
SKILLS_CSS = Path("src/opensquilla/gateway/static/css/views/skills.css")


def test_skills_cards_keep_full_description_available_while_clamping_visually() -> None:
    source = SKILLS_JS.read_text(encoding="utf-8")
    css = SKILLS_CSS.read_text(encoding="utf-8")

    render_start = source.index("function _renderCard(skill)")
    render_end = source.index("  function _openSkillDialog", render_start)
    render_body = source[render_start:render_end]

    assert "const desc = skill.description || '';" in render_body
    assert "skill.description.length > 100" not in render_body
    assert 'title="${_esc(skill.name + (desc ? \': \' + desc : \'\'))}"' in render_body
    assert '<p class="sk-card__desc" title="${_esc(desc)}">${_esc(desc)}</p>' in render_body

    desc_start = css.index(".sk-card__desc {")
    desc_rule = css[desc_start : css.index("}", desc_start)]
    assert "-webkit-line-clamp: 3" in desc_rule
    assert "line-clamp: 3" in desc_rule
    assert "mask-image: linear-gradient" in desc_rule
    assert "min-height:" in desc_rule


def test_skill_detail_dialog_shows_full_description_for_touch_users() -> None:
    source = SKILLS_JS.read_text(encoding="utf-8")
    dialog_start = source.index("function _openSkillDialog(skill)")
    dialog_end = source.index("  async function _installDeps", dialog_start)
    dialog_body = source[dialog_start:dialog_end]

    assert '<p class="sk-dialog__desc">${_esc(skill.description || \'\')}</p>' in dialog_body
    assert "_truncDesc" not in source


def test_skills_primary_controls_keep_touch_friendly_hit_areas() -> None:
    css = SKILLS_CSS.read_text(encoding="utf-8")

    search_rule = css[
        css.index(".sk-search-input {") : css.index("}", css.index(".sk-search-input {"))
    ]
    icon_rule = css[css.index(".sk-iconbtn {") : css.index("}", css.index(".sk-iconbtn {"))]
    tab_rule = css[css.index(".sk-tab {") : css.index("}", css.index(".sk-tab {"))]

    assert "min-height: 40px" in search_rule
    assert "width: 40px; height: 40px" in icon_rule
    assert "min-width: 40px" in icon_rule
    assert "flex: 0 0 40px" in icon_rule
    assert "min-height: 40px" in tab_rule
    assert "#skills-refresh { min-height: 40px; }" in css
    assert "#skills-github-install { min-height: 40px; }" in css


def test_skills_active_tabs_use_theme_contrast_token() -> None:
    css = SKILLS_CSS.read_text(encoding="utf-8")
    start = css.index(".sk-tab.is-active {")
    rule = css[start : css.index("}", start)]

    assert "color: var(--accent-foreground)" in rule


def test_skill_card_names_wrap_instead_of_truncating_identifiers() -> None:
    css = SKILLS_CSS.read_text(encoding="utf-8")
    head_rule = css[css.index(".sk-card__head {") : css.index("}", css.index(".sk-card__head {"))]
    name_rule = css[css.index(".sk-card__name {") : css.index("}", css.index(".sk-card__name {"))]

    assert "align-items: flex-start" in head_rule
    assert "overflow-wrap: anywhere" in name_rule
    assert "white-space: normal" in name_rule
    assert "text-overflow: ellipsis" not in name_rule


def test_skill_card_variable_copy_wraps_inside_mobile_cards() -> None:
    css = SKILLS_CSS.read_text(encoding="utf-8")

    for selector in (".sk-card__desc {", ".sk-card__sub-chip {"):
        rule = css[css.index(selector) : css.index("}", css.index(selector))]

        assert "max-width: 100%" in rule, selector
        assert "min-width: 0" in rule, selector
        assert "overflow-wrap: anywhere" in rule, selector


def test_skills_mobile_stats_keep_list_visible_in_first_viewport() -> None:
    css = SKILLS_CSS.read_text(encoding="utf-8")
    mobile_start = css.index("@media (max-width: 720px)")
    mobile_rule = css[mobile_start : css.index("/* ─── Meta-Skill", mobile_start)]

    assert (
        ".sk-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); "
        "gap: var(--sp-2); }"
        in mobile_rule
    )
    assert (
        ".sk-stat { min-height: 86px; "
        "padding: var(--sp-3) var(--sp-3) var(--sp-3) var(--sp-4); }"
        in mobile_rule
    )
    assert ".sk-stat__value { font-size: 1.35rem; }" in mobile_rule
