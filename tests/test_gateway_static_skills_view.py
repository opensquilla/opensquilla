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


def test_skills_view_renders_pending_proposals_section() -> None:
    """Path 3 of the auto-propose feature plugs into the Skills view.
    Static asserts cover (a) the RPC calls that feed it,
    (b) the visible HTML markers, and (c) the three action handlers."""
    view = Path("src/opensquilla/gateway/static/js/views/skills.js").read_text(encoding="utf-8")
    css = Path("src/opensquilla/gateway/static/css/views/skills.css").read_text(encoding="utf-8")

    # RPC calls
    assert "_rpc.call('exec.proposals.list')" in view
    assert "_rpc.call('exec.proposals.show'" in view
    assert "_rpc.call('exec.proposals.accept'" in view
    assert "_rpc.call('exec.proposals.reject'" in view

    # HTML structure
    assert "sk-group--proposals" in view
    assert "Pending Proposals" in view
    assert "_renderProposalRow" in view

    # Action handlers wired into the click delegate
    assert "[data-proposal-show]" in view
    assert "[data-proposal-accept]" in view
    assert "[data-proposal-reject]" in view

    # CSS for the new chips + dialog
    assert ".sk-group--proposals" in css
    assert ".sk-prop-chip--auto" in css
    assert ".sk-proposal-row" in css


def test_skills_view_force_accepts_after_gate_failure_confirm() -> None:
    """When proposals.accept returns refused because of failed gates,
    the UI prompts and retries with force=true. Static check that the
    retry path passes force=true."""
    view = Path("src/opensquilla/gateway/static/js/views/skills.js").read_text(encoding="utf-8")
    assert "force: true" in view


def test_skills_view_auto_chip_recognises_auto_triggered_by() -> None:
    """Provenance chip: rows from cron/dream show [auto] alongside the
    proposal_id so operators can spot bot-generated proposals at a glance."""
    view = Path("src/opensquilla/gateway/static/js/views/skills.js").read_text(encoding="utf-8")
    assert "p.triggered_by.startsWith('auto_')" in view
    assert "sk-prop-chip--auto" in view
