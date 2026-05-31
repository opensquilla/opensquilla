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
    assert "_rpc.call('exec.proposals.auto_enabled.list')" in view
    assert "_rpc.call('exec.proposals.auto_enabled.disable'" in view

    # HTML structure
    assert "sk-group--proposals" in view
    assert "Pending Proposals" in view
    assert "_renderProposalRow" in view
    assert "_renderAutoEnabledRow" in view

    # Action handlers wired into the click delegate
    assert "[data-proposal-show]" in view
    assert "[data-proposal-accept]" in view
    assert "[data-proposal-reject]" in view
    assert "[data-auto-enabled-disable]" in view

    # CSS for the new chips + dialog
    assert ".sk-group--proposals" in css
    assert ".sk-prop-chip--auto" in css
    assert ".sk-proposal-row" in css


def test_skills_view_renders_auto_enable_audit_summary() -> None:
    view = Path("src/opensquilla/gateway/static/js/views/skills.js").read_text(encoding="utf-8")
    css = Path("src/opensquilla/gateway/static/css/views/skills.css").read_text(encoding="utf-8")

    assert "_renderAutoEnableAudit" in view
    assert "auto_enable_audit" in view
    assert "validation_profile" in view
    assert "static-safety" in view
    assert "sk-audit-grid" in view
    assert ".sk-audit-grid" in css


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


def test_skills_view_renders_auto_propose_settings_panel() -> None:
    """The settings toggle for unattended-synthesis must be in the Skills
    view: RPC calls, two checkbox bindings, and the CSS class names."""
    view = Path("src/opensquilla/gateway/static/js/views/skills.js").read_text(encoding="utf-8")
    css = Path("src/opensquilla/gateway/static/css/views/skills.css").read_text(encoding="utf-8")

    # RPC calls present
    assert "_rpc.call('exec.proposals.settings.get')" in view
    assert "_rpc.call('exec.proposals.settings.set'" in view

    # Distinct toggles
    assert 'data-ap-toggle="enabled"' in view
    assert 'data-ap-toggle="on_dream_complete"' in view
    assert 'data-ap-toggle="auto_enable"' in view
    assert 'data-ap-risk-select' in view

    # Section renderer
    assert "_renderAutoProposeSettings" in view
    assert "sk-group--ap-settings" in view
    assert "Off by default. Enable cron or dream" in view
    assert ".sk-group--ap-settings" in css
    assert ".sk-ap-toggle" in css

    # Bookkeeping state
    assert "_proposalsSettings" in view
    assert "_toggleAutoPropose" in view
    assert "_setAutoEnableRisk" in view


def test_skills_view_renders_settings_panel_even_with_no_pending_proposals() -> None:
    """The toggle has to appear before any proposal exists, otherwise
    the operator can't turn the feature on from a clean state."""
    view = Path("src/opensquilla/gateway/static/js/views/skills.js").read_text(encoding="utf-8")
    # The settings renderer is gated on _proposalsSettings.available
    # rather than on _proposals.length.
    assert "if (_proposalsSettings && _proposalsSettings.available)" in view
