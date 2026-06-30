from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHAT_JS = ROOT / "src" / "opensquilla" / "gateway" / "static" / "js" / "views" / "chat.js"


def test_web_chat_defaults_are_policy_driven() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "const _RUN_MODE_FALLBACK = 'trusted';" in source
    assert "_applyHelloRunModePolicy" in source
    assert "_runModePolicyDefault" in source
    assert "new Set(['standard', 'trusted']);" in source
    assert "Establish sandbox" in source


def _extract_js_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"could not extract JS function {name}")


def test_web_chat_run_mode_policy_fails_closed_for_missing_or_malformed_policy() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    helper_names = [
        "_runModePolicyValue",
        "_normalizeRunModePolicyValue",
        "_runModeAllowed",
        "_firstAllowedRunMode",
        "_clampRunMode",
        "_fullHostAccessDisabledMessage",
        "_applyHelloRunModePolicy",
    ]
    helpers = "\n".join(_extract_js_function(source, name) for name in helper_names)
    script = f"""
const assert = require('assert');
const _RUN_MODE_FALLBACK = 'trusted';
let _runModePolicyDefault = _RUN_MODE_FALLBACK;
let _allowedRunModes = new Set(['standard', 'trusted', 'full']);
let _fullHostAccessDisabledReason = null;
let _runMode = _runModePolicyDefault;
let _toolbarState = {{ runMode: _runModePolicyDefault }};
function _updateRunModeControl() {{}}
function _refreshToolbarTriggerGlow() {{}}
{helpers}

_applyHelloRunModePolicy(null);
assert.deepStrictEqual([..._allowedRunModes].sort(), ['standard', 'trusted']);
assert.strictEqual(_runModePolicyDefault, 'trusted');
assert.strictEqual(_runMode, 'trusted');
assert.strictEqual(_fullHostAccessDisabledReason, 'owner_required');

_applyHelloRunModePolicy({{ auth: {{ runModePolicy: {{
  allowedRunModes: ['unknown'],
  defaultRunMode: 'full',
}} }} }});
assert.deepStrictEqual([..._allowedRunModes].sort(), ['standard', 'trusted']);
assert.strictEqual(_runModePolicyDefault, 'trusted');
assert.strictEqual(_runMode, 'trusted');
assert.strictEqual(_fullHostAccessDisabledReason, 'owner_required');

_applyHelloRunModePolicy({{ auth: {{ runModePolicy: {{
  allowedRunModes: ['standard', 'trusted', 'full'],
}} }} }});
assert.deepStrictEqual([..._allowedRunModes].sort(), ['full', 'standard', 'trusted']);
assert.strictEqual(_runModePolicyDefault, 'full');
assert.strictEqual(_runMode, 'full');
assert.strictEqual(_fullHostAccessDisabledReason, null);

_applyHelloRunModePolicy({{ auth: {{ runModePolicy: {{
  allowedRunModes: ['standard', 'trusted'],
  defaultRunMode: 'full',
  fullHostAccessDisabledReason: 'owner_required',
}} }} }});
assert.deepStrictEqual([..._allowedRunModes].sort(), ['standard', 'trusted']);
assert.strictEqual(_runModePolicyDefault, 'trusted');
assert.strictEqual(_runMode, 'trusted');
assert.strictEqual(_fullHostAccessDisabledReason, 'owner_required');
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_web_chat_run_mode_switch_uses_setup_gate_for_sandbox_modes() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "_requestSandboxSetupForMode" in source
    assert "_ensureSandboxSetupOnly" in source
    assert "_sandboxSetupReadyForMode" in source
    assert "const pendingPrompt = !!_pendingSandboxSetupMode;" in source
    assert "const optionalPrompt = setupKnown && !_sandboxSetupPromptDismissed;" in source
    assert "sandbox.setup.status" in source
    assert "sandbox.setup.ensure" in source
    assert "if (mode === 'full') return true;" in source
    assert "if (!(await _requestSandboxSetupForMode(mode))) return;" in source


def test_web_chat_run_mode_is_not_loaded_from_gateway_or_session_context() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "_loadRunModeStatusFallback" not in source
    assert "sandbox.status" not in source
    assert "_loadRunContext" not in source
    assert "_syncRunMode" not in source
    assert "sandbox.run_context.get" not in source
    assert "sandbox.run_context.set" not in source
