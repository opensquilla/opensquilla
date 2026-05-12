from __future__ import annotations

import re
from pathlib import Path

import yaml

WORKFLOW_DIR = Path(".github/workflows")
TEST_PATH_RE = re.compile(r"tests/[A-Za-z0-9_./-]+\.py")


def _workflow(name: str) -> dict:
    path = WORKFLOW_DIR / name
    assert path.is_file(), f"missing workflow: {path}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _trigger_keys(data: dict) -> set[str]:
    triggers = data.get("on", {})
    if triggers is None:
        return set()
    if isinstance(triggers, str):
        return {triggers}
    return set(triggers)


def _workflow_texts() -> list[str]:
    return [path.read_text(encoding="utf-8") for path in WORKFLOW_DIR.glob("*.yml")]


def test_default_ci_blocks_pull_requests_and_main_pushes() -> None:
    ci_path = WORKFLOW_DIR / "ci.yml"
    if not ci_path.exists():
        return

    data = _workflow("ci.yml")
    text = ci_path.read_text(encoding="utf-8")

    assert {"pull_request", "push", "workflow_dispatch"} <= _trigger_keys(data)
    assert "branches: [main]" in text
    assert "PYTHONPATH: ${{ github.workspace }}" in text
    assert "Configure runtime directories" in text
    assert 'OPENSQUILLA_STATE_DIR=%s/opensquilla-state\\n' in text
    assert 'OPENSQUILLA_LOG_DIR=%s/opensquilla-logs\\n' in text
    assert "OPENSQUILLA_TURN_CALL_LOG: \"0\"" in text
    assert "actionlint@v1.7.12" in text


def test_manual_workflows_reference_existing_test_files() -> None:
    for text in _workflow_texts():
        for raw_path in TEST_PATH_RE.findall(text):
            assert Path(raw_path).is_file(), f"workflow references missing test: {raw_path}"


def test_webui_browser_workflow_is_manual_and_opt_in() -> None:
    data = _workflow("webui-browser-smoke.yml")
    text = (WORKFLOW_DIR / "webui-browser-smoke.yml").read_text(encoding="utf-8")

    assert _trigger_keys(data) == {"workflow_dispatch"}
    assert 'OPENSQUILLA_WEBUI_BROWSER_E2E: "1"' in text
    assert "tests/functional/test_webui_browser_e2e.py" in text
    assert "playwright install chromium" in text


def test_llm_workflow_is_single_manual_smoke() -> None:
    data = _workflow("llm-e2e.yml")
    text = (WORKFLOW_DIR / "llm-e2e.yml").read_text(encoding="utf-8")

    assert _trigger_keys(data) == {"workflow_dispatch"}
    assert "OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}" in text
    assert "tests/functional/test_llm_smoke.py" in text
    assert "llm_costly" not in text
    assert "tests/functional/test_webui_llm_e2e.py" not in text


def test_live_release_e2e_workflow_is_manual_and_separates_private_inputs() -> None:
    data = _workflow("live-release-e2e.yml")
    text = (WORKFLOW_DIR / "live-release-e2e.yml").read_text(encoding="utf-8")

    assert _trigger_keys(data) == {"workflow_dispatch"}
    assert "tests/functional/test_gateway_llm_e2e.py" in text
    assert "tests/functional/test_webui_browser_chat_e2e.py" in text
    assert "tests/functional/test_live_channel_telegram_smoke.py" in text
    assert "OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}" in text
    assert (
        "OPENSQUILLA_LIVE_TELEGRAM_BOT_TOKEN: "
        "${{ secrets.OPENSQUILLA_LIVE_TELEGRAM_BOT_TOKEN }}"
    ) in text
    assert (
        "OPENSQUILLA_LIVE_TELEGRAM_CHAT_ID: "
        "${{ secrets.OPENSQUILLA_LIVE_TELEGRAM_CHAT_ID }}"
    ) in text
    assert "tests/private" not in text


def test_default_ci_stays_offline_and_does_not_run_live_gates() -> None:
    text = (WORKFLOW_DIR / "ci.yml").read_text(encoding="utf-8")

    assert "OPENROUTER_API_KEY" not in text
    assert "OPENSQUILLA_LIVE_TELEGRAM" not in text
    assert "OPENSQUILLA_GATEWAY_LLM_E2E" not in text
    assert "OPENSQUILLA_WEBUI_BROWSER_E2E" not in text
    assert "OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E" not in text
    assert "test_gateway_llm_e2e.py" not in text
    assert "test_live_channel_telegram_smoke.py" not in text


def test_live_release_e2e_fails_fast_when_required_provider_secret_is_missing() -> None:
    text = (WORKFLOW_DIR / "live-release-e2e.yml").read_text(encoding="utf-8")

    assert "Fail if OpenRouter secret is missing" in text
    assert 'if [ -z "$OPENROUTER_API_KEY" ]; then' in text
    assert "OPENROUTER_API_KEY GitHub secret is required" in text
    assert "Fail if Telegram secrets are missing when channel smoke is enabled" in text
    assert 'if [ -z "$OPENSQUILLA_LIVE_TELEGRAM_BOT_TOKEN" ]' in text
    assert 'if [ -z "$OPENSQUILLA_LIVE_TELEGRAM_CHAT_ID" ]' in text


def test_wheelhouse_release_publishes_only_recommended_router_profile() -> None:
    text = (WORKFLOW_DIR / "wheelhouse-release.yml").read_text(encoding="utf-8")

    assert "      profile:\n" not in text
    assert "RELEASE_PROFILE: recommended" in text
    assert "--profile \"${RELEASE_PROFILE}\"" in text
    assert "- core" not in text
