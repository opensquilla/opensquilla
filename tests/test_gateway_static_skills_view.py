from __future__ import annotations

from pathlib import Path


def test_skills_view_exposes_direct_github_install_control() -> None:
    view = Path("src/opensquilla/gateway/static/js/views/skills.js").read_text(encoding="utf-8")

    assert 'id="skills-github-url"' in view
    assert 'class="btn btn--primary" id="skills-github-install"' in view
    assert "_installSkill(githubInput.value.trim(), 'github'," in view


def test_skills_view_search_stays_clawhub_only() -> None:
    view = Path("src/opensquilla/gateway/static/js/views/skills.js").read_text(encoding="utf-8")

    assert 'id="skills-registry-source"' not in view
    assert "Searching ClawHub" in view
    assert "skills.search', { query: query.trim(), limit: 20 }" in view


def test_skills_view_distinguishes_bundled_from_local_layers() -> None:
    view = Path("src/opensquilla/gateway/static/js/views/skills.js").read_text(encoding="utf-8")

    assert "Bundled skills ship with OpenSquilla." in view
    assert "Managed skills are locally installed into OpenSquilla state." in view
    assert "Personal skills are local user installs, not bundled." in view


def test_skills_view_uses_domain_view_state_helper_for_layers_and_status() -> None:
    view = Path("src/opensquilla/gateway/static/js/views/skills.js").read_text(encoding="utf-8")

    assert "const SkillsDomainViewState = Object.freeze" in view
    assert "SkillsDomainViewState.skillStatus" in view
    assert "SkillsDomainViewState.statusRank" in view
    assert "SkillsDomainViewState.layerLabel" in view
    assert "SkillsDomainViewState.layerHelp" in view
    assert "WebUiRpc.client()" in view
    assert "App.getRpc(" not in view
