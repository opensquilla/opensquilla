from __future__ import annotations

import subprocess
import tempfile
import textwrap
from pathlib import Path

SKILLS_VIEW = Path("src/opensquilla/gateway/static/js/views/skills.js")


def _run_skills_view_harness(assertion_script: str) -> str:
    source = SKILLS_VIEW.read_text(encoding="utf-8")
    instrumented = source.replace(
        "return { render, destroy };",
        """return { render, destroy, __test: {
      setState: (state) => {
        _el = state.el || _el;
        _rpc = state.rpc || _rpc;
        _allSkills = state.allSkills || _allSkills;
      },
      openSkillDialog: _openSkillDialog,
      dependencySummary: _dependencySummary
    } };""",
    )
    script = textwrap.dedent(
        f"""
        const vm = require('vm');

        function makeButton() {{
          return {{
            _listeners: {{}},
            addEventListener(type, fn) {{ this._listeners[type] = fn; }},
            click() {{
              if (this._listeners.click) {{
                return this._listeners.click({{ preventDefault() {{}}, stopPropagation() {{}} }});
              }}
            }},
          }};
        }}

        const closeButton = makeButton();

        const dialog = {{
          open: false,
          addEventListener() {{}},
          close() {{ this.open = false; }},
          showModal() {{ this.open = true; }},
          setAttribute(name) {{ if (name === 'open') this.open = true; }},
        }};

        const body = {{
          innerHTML: '',
          querySelector(selector) {{
            if (selector === '#skill-dialog-close') return closeButton;
            return null;
          }},
        }};

        const el = {{
          querySelector(selector) {{
            if (selector === '#skill-detail-dialog') return dialog;
            if (selector === '#skill-detail-body') return body;
            return null;
          }},
        }};

        const icons = new Proxy({{}}, {{
          get(_target, prop) {{
            return () => `[icon:${{String(prop)}}]`;
          }},
        }});

        const context = {{
          window: {{}},
          document: {{}},
          icons,
          App: {{ getRpc: () => null }},
          UI: {{ toast() {{}}, confirm: async () => true }},
          console,
          setTimeout,
          clearTimeout,
          encodeURIComponent,
        }};

        vm.createContext(context);
        vm.runInContext({instrumented!r}, context);

        const SkillsView = context.window.SkillsView;
        const env = {{ SkillsView, dialog, body, el, closeButton }};

        async function main() {{
        {textwrap.indent(assertion_script, "  ")}
        }}

        main().catch((error) => {{
          console.error(error && error.stack ? error.stack : String(error));
          process.exit(1);
        }});
        """
    )
    with tempfile.TemporaryDirectory() as tmp:
        script_path = Path(tmp) / "skills-view-harness.js"
        script_path.write_text(script, encoding="utf-8")
        result = subprocess.run(
            ["node", str(script_path)],
            check=False,
            capture_output=True,
            text=True,
        )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout


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


def test_skills_view_renders_missing_env_any_groups() -> None:
    view = Path("src/opensquilla/gateway/static/js/views/skills.js").read_text(encoding="utf-8")

    assert "missing_env_any" in view
    assert "env var group" in view


def test_skills_view_keeps_dialog_open_for_missing_env_any_after_install() -> None:
    view = Path("src/opensquilla/gateway/static/js/views/skills.js").read_text(encoding="utf-8")

    assert "const still = res.missing_still || {};" in view
    assert "(still.bins || []).length" in view
    assert "(still.env || []).length" in view
    assert "(still.env_any || []).length" in view


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


def test_skills_view_renders_dependency_badges_on_cards() -> None:
    view = Path("src/opensquilla/gateway/static/js/views/skills.js").read_text(encoding="utf-8")
    css = Path("src/opensquilla/gateway/static/css/views/skills.css").read_text(encoding="utf-8")

    assert "dependency_summary" in view
    assert "_renderDependencyBadges" in view
    assert "sk-card__deps" in view
    assert "sk-card__dep-badge" in view
    assert "py " in view
    assert "bin " in view
    assert "env " in view
    assert "missing " in view
    assert "advisory " in view

    assert ".sk-card__deps" in css
    assert ".sk-card__dep-badge" in css
    assert ".sk-card__dep-badge--missing" in css
    assert ".sk-card__dep-badge--advisory" in css


def test_skills_view_renders_detailed_dependency_section_in_dialog() -> None:
    view = Path("src/opensquilla/gateway/static/js/views/skills.js").read_text(encoding="utf-8")
    css = Path("src/opensquilla/gateway/static/css/views/skills.css").read_text(encoding="utf-8")

    assert "_rpc.call('skills.get'" in view
    assert "_renderDependencySection" in view
    assert "Dependencies" in view
    assert "Declared Python Packages" in view
    assert "Declared Binaries" in view
    assert "Declared API Env" in view
    assert "Missing Dependencies" in view
    assert "Suggested next steps" in view
    assert "Advisory only" in view
    assert "sub-skill rollup" in view
    assert "missing.binaries.any" in view
    assert "missing.api_env.any" in view
    assert "scan_errors" in view
    assert view.index("Suggested next steps") < view.index("Declared Python Packages")

    assert ".sk-dep-grid" in css
    assert ".sk-dep-block" in css
    assert ".sk-dep-block--suggestions" in css
    assert "grid-column: 1 / -1" in css
    assert ".sk-dep-block--suggestions .sk-dep-block__title" in css
    assert "text-transform: none" in css
    assert ".sk-dep-list" in css
    assert ".sk-dep-note" in css
    assert ".sk-dep-subskill-row" in css


def test_skills_view_detail_x_uses_dialog_close_delegate() -> None:
    view = Path("src/opensquilla/gateway/static/js/views/skills.js").read_text(encoding="utf-8")

    assert 'id="skill-dialog-close" data-dialog-close' in view
    assert "_closeSkillDialog" in view


def test_skills_view_detail_x_closes_dialog_without_reference_error() -> None:
    _run_skills_view_harness(
        """
        const detail = {
          name: 'demo-skill',
          description: 'Needs setup',
          layer: 'managed',
          status: 'needs_setup',
          dependency_summary: {
            declared: {
              binaries: { all: [], any: [] },
              python_packages: [],
              api_env: { all: [], any: [] },
            },
            missing: {
              binaries: { all: [], any: [] },
              api_env: { all: [], any: [] },
              count: 0,
            },
            inferred: { python_imports: [], api_env: [], scan_errors: [] },
            sub_skill_dependencies: {
              skills: [],
              missing_count: 0,
              inferred_count: 0,
              missing_references: [],
            },
          },
        };
        const rpc = {
          async call(method, payload) {
            if (method !== 'skills.get' || payload.name !== 'demo-skill') {
              throw new Error(`unexpected rpc call ${method}`);
            }
            return detail;
          },
        };

        SkillsView.__test.setState({ el, rpc, allSkills: [] });
        await SkillsView.__test.openSkillDialog(detail);
        if (!dialog.open) throw new Error('dialog should be open before close click');

        closeButton.click();

        if (dialog.open) {
          throw new Error('dialog should close after clicking the X button');
        }
        """
    )


def test_skills_view_dialog_suggests_missing_dependency_next_steps() -> None:
    _run_skills_view_harness(
        """
        const detail = {
          name: 'demo-skill',
          description: 'Needs setup',
          layer: 'managed',
          status: 'needs_setup',
          dependency_summary: {
            declared: {
              binaries: { all: ['demo-tool'], any: [] },
              python_packages: [
                {
                  install_id: 'py',
                  label: 'Demo Python package',
                  package: 'demo-pkg',
                  module: 'demo_pkg',
                },
              ],
              api_env: { all: ['DEMO_API_KEY'], any: [] },
            },
            missing: {
              binaries: { all: ['demo-tool'], any: [] },
              api_env: { all: ['DEMO_API_KEY'], any: [] },
              count: 2,
            },
            inferred: { python_imports: [], api_env: [], scan_errors: [] },
            sub_skill_dependencies: {
              skills: [],
              missing_count: 0,
              inferred_count: 0,
              missing_references: ['child-skill'],
            },
          },
        };
        const rpc = {
          async call(method, payload) {
            if (method !== 'skills.get' || payload.name !== 'demo-skill') {
              throw new Error(`unexpected rpc call ${method}`);
            }
            return detail;
          },
        };

        SkillsView.__test.setState({ el, rpc, allSkills: [] });
        await SkillsView.__test.openSkillDialog(detail);

        const html = body.innerHTML;
        if (!html.includes('Suggested next steps')) {
          throw new Error(`missing suggestion section: ${html}`);
        }
        if (!html.includes('uv pip install demo-pkg')) {
          throw new Error(`missing python install command: ${html}`);
        }
        if (!html.includes('Install demo-tool')) {
          throw new Error(`missing binary install advice: ${html}`);
        }
        if (!html.includes('Set DEMO_API_KEY')) {
          throw new Error(`missing env setup advice: ${html}`);
        }
        if (!html.includes('Install or enable sub-skill child-skill')) {
          throw new Error(`missing sub-skill setup advice: ${html}`);
        }
        if (!html.includes('opensquilla skills install child-skill')) {
          throw new Error(`missing sub-skill install command: ${html}`);
        }
        """
    )


def test_skills_view_dialog_exposes_package_only_install_actions() -> None:
    _run_skills_view_harness(
        """
        const detail = {
          name: 'package-only',
          description: 'Needs a Python package setup action',
          layer: 'managed',
          status: 'not_declared',
          dependency_summary: {
            declared: {
              binaries: { all: [], any: [] },
              python_packages: [
                {
                  install_id: 'py-dep',
                  label: 'Install package dependency',
                  package: 'package-dep',
                  module: 'package_dep',
                },
              ],
              api_env: { all: [], any: [] },
            },
            missing: {
              binaries: { all: [], any: [] },
              api_env: { all: [], any: [] },
              count: 0,
            },
            inferred: { python_imports: [], api_env: [], scan_errors: [] },
            sub_skill_dependencies: {
              skills: [],
              missing_count: 0,
              inferred_count: 0,
              missing_references: [],
            },
          },
          install: [
            {
              id: 'py-dep',
              kind: 'uv',
              label: 'Install package dependency',
            },
          ],
        };
        const rpc = {
          async call(method, payload) {
            if (method !== 'skills.get' || payload.name !== 'package-only') {
              throw new Error(`unexpected rpc call ${method}`);
            }
            return detail;
          },
        };

        SkillsView.__test.setState({ el, rpc, allSkills: [] });
        await SkillsView.__test.openSkillDialog(detail);

        const html = body.innerHTML;
        if (!html.includes('data-install-deps-id="py-dep"')) {
          throw new Error(`missing package-only install action: ${html}`);
        }
        if (!html.includes('uv pip install package-dep')) {
          throw new Error(`missing package-only install command: ${html}`);
        }
        """
    )


def test_skills_view_dialog_ignores_stale_fetch_and_hides_optional_installs() -> None:
    _run_skills_view_harness(
        """
        function deferred() {
          let resolve;
          let reject;
          const promise = new Promise((res, rej) => {
            resolve = res;
            reject = rej;
          });
          return { promise, resolve, reject };
        }

        const first = deferred();
        const second = deferred();
        const calls = [];
        const rpc = {
          async call(method, payload) {
            calls.push({ method, payload });
            if (method !== 'skills.get') {
              throw new Error(`unexpected rpc method: ${method}`);
            }
            if (payload.name === 'alpha') return first.promise;
            if (payload.name === 'beta') return second.promise;
            throw new Error(`unexpected skill name: ${payload.name}`);
          },
        };

        SkillsView.__test.setState({ el, rpc, allSkills: [] });

        const alpha = {
          name: 'alpha',
          description: 'Alpha list payload',
          layer: 'managed',
          status: 'needs_setup',
          dependency_summary: {
            declared: {
              binaries: { all: ['alpha-bin'], any: [] },
              python_packages: [],
              api_env: { all: [], any: [] },
            },
            missing: {
              binaries: { all: ['alpha-bin'], any: [] },
              api_env: { all: [], any: [] },
              count: 1,
            },
            inferred: { python_imports: [], api_env: [], scan_errors: [] },
            sub_skill_dependencies: {
              skills: [],
              missing_count: 0,
              inferred_count: 0,
              missing_references: [],
            },
          },
          install: [
            { id: 'alpha-installer', kind: 'uv', label: 'Install alpha', bins: ['alpha-bin'] },
          ],
        };
        const beta = {
          name: 'beta',
          description: 'Beta list payload',
          layer: 'managed',
          status: 'ready',
          dependency_summary: {
            declared: {
              binaries: { all: ['beta-bin'], any: ['beta-alt-a', 'beta-alt-b'] },
              python_packages: [
                {
                  install_id: 'pkg',
                  label: 'Install pkg',
                  package: 'beta-pkg',
                  module: 'beta_pkg',
                },
              ],
              api_env: { all: [], any: ['BETA_API_KEY', 'ALT_BETA_API_KEY'] },
            },
            missing: {
              binaries: { all: [], any: [] },
              api_env: { all: [], any: [] },
              count: 0,
            },
            inferred: { python_imports: [], api_env: [], scan_errors: [] },
            sub_skill_dependencies: {
              skills: [],
              missing_count: 0,
              inferred_count: 0,
              missing_references: [],
            },
          },
          install: [
            { id: 'beta-installer', kind: 'uv', label: 'Install beta', bins: ['beta-bin'] },
          ],
        };

        const alphaPromise = SkillsView.__test.openSkillDialog(alpha);
        if (!dialog.open) throw new Error('dialog should open immediately');
        if (!body.innerHTML.includes('Loading latest dependency details')) {
          throw new Error(`loading state missing: ${body.innerHTML}`);
        }
        if (body.innerHTML.includes('data-install-deps-id="alpha-installer"')) {
          throw new Error(`loading state should not show stale install action: ${body.innerHTML}`);
        }

        const betaPromise = SkillsView.__test.openSkillDialog(beta);

        second.resolve({
          ...beta,
          description: 'Beta detail payload',
        });
        await betaPromise;
        if (!body.innerHTML.includes('Beta detail payload')) {
          throw new Error(`latest skill detail not rendered: ${body.innerHTML}`);
        }
        if (body.innerHTML.includes('data-install-deps-id="beta-installer"')) {
          throw new Error(`ready skill should not show install action: ${body.innerHTML}`);
        }

        first.resolve({
          ...alpha,
          description: 'Alpha detail payload',
        });
        await alphaPromise;
        if (body.innerHTML.includes('Alpha detail payload')) {
          throw new Error(`stale skill response overwrote active dialog: ${body.innerHTML}`);
        }
        if (!body.innerHTML.includes('Beta detail payload')) {
          throw new Error(`beta detail should remain after stale resolve: ${body.innerHTML}`);
        }

        if (calls.length !== 2) {
          throw new Error(`expected 2 skills.get calls, saw ${calls.length}`);
        }
        """
    )
