from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import yaml

WORKFLOW_DIR = Path(".github/workflows")
CLASSIFIER = Path(".github/scripts/classify-ci-changes.sh")
PR_TARGET_VALIDATOR = Path(".github/scripts/validate-pr-target-branch.sh")
PR_BODY_LINT = Path(".github/scripts/validate_pr_body.py")
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


def _is_windows_wsl_bash(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return normalized.endswith("/windows/system32/bash.exe")


def _bash_executable(
    *,
    os_name: str = os.name,
    path_lookup: Callable[[str], str | None] = shutil.which,
    exists: Callable[[Path], bool] = Path.is_file,
    program_files: str | None = None,
) -> str:
    found = path_lookup("bash")
    if os_name != "nt":
        return found or "bash"

    candidates: list[Path] = []
    if found and not _is_windows_wsl_bash(found):
        candidates.append(Path(found))

    git_root = Path(program_files or os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git"
    candidates.extend(
        [
            git_root / "bin" / "bash.exe",
            git_root / "usr" / "bin" / "bash.exe",
        ]
    )

    for candidate in candidates:
        if exists(candidate):
            return str(candidate)

    raise AssertionError("Git Bash is required to run the CI change classifier on Windows")


def _classify_changed_files(
    tmp_path: Path,
    paths: list[str],
    *,
    line_ending: str = "\n",
) -> dict[str, str]:
    changed_file = tmp_path / "changed-files.txt"
    output_file = tmp_path / "github-output.txt"
    changed_file.write_text(
        line_ending.join(paths) + line_ending,
        encoding="utf-8",
        newline="",
    )

    env = os.environ.copy()
    env["GITHUB_OUTPUT"] = output_file.as_posix()
    subprocess.run(
        [_bash_executable(), CLASSIFIER.as_posix(), changed_file.as_posix()],
        check=True,
        env=env,
        text=True,
        capture_output=True,
    )

    outputs: dict[str, str] = {}
    for line in output_file.read_text(encoding="utf-8").splitlines():
        key, value = line.split("=", 1)
        outputs[key] = value
    return outputs


def _validate_pr_target(
    tmp_path: Path,
    *,
    base: str,
    head: str = "feature/example",
    title: str = "Example change",
    labels: list[str] | None = None,
    changed_files: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    event_path = tmp_path / "event.json"
    changed_files_path = tmp_path / "changed-files.txt"
    if changed_files is not None:
        changed_files_path.write_text("\n".join(changed_files) + "\n", encoding="utf-8")

    event_path.write_text(
        json.dumps(
            {
                "pull_request": {
                    "base": {"ref": base},
                    "head": {"ref": head},
                    "labels": [{"name": label} for label in labels or []],
                    "title": title,
                },
            }
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "GITHUB_EVENT_PATH": event_path.as_posix(),
            "PR_BASE_REF": base,
            "PR_HEAD_REF": head,
            "PR_LABELS": ",".join(labels or []),
            "PR_TITLE": title,
        }
    )
    if changed_files is not None:
        env["PR_CHANGED_FILES_PATH"] = changed_files_path.as_posix()
    return subprocess.run(
        [_bash_executable(), PR_TARGET_VALIDATOR.as_posix()],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_default_ci_blocks_pull_requests_and_main_and_dev_pushes() -> None:
    ci_path = WORKFLOW_DIR / "ci.yml"
    if not ci_path.exists():
        return

    data = _workflow("ci.yml")
    text = ci_path.read_text(encoding="utf-8")

    assert {"pull_request", "push", "workflow_dispatch"} <= _trigger_keys(data)
    assert "branches: [main, dev]" in text
    assert "PYTHONPATH: ${{ github.workspace }}" in text
    assert "Configure runtime directories" in text
    assert 'OPENSQUILLA_STATE_DIR=%s/opensquilla-state\\n' in text
    assert 'OPENSQUILLA_LOG_DIR=%s/opensquilla-logs\\n' in text
    assert "OPENSQUILLA_TURN_CALL_LOG: \"0\"" in text
    assert "actionlint@v1.7.12" in text
    assert "Classify changed files" in text
    assert "Ubuntu quality gate" in text
    assert "Windows compatibility tests" in text
    assert "Release packaging contracts" in text
    assert "CI result" in text
    assert 'push)\n              printf \'.ci/run-all\\n\' > "${changed_files}"' in text
    assert "runtime_changed" in text
    assert "test_changed" in text
    assert "ci_changed" in text
    assert "dependency_changed" in text
    assert "release_changed" in text
    assert "code_changed" not in text
    assert "workflow_changed" not in text


def test_pr_target_validator_allows_dev_pull_requests(tmp_path: Path) -> None:
    result = _validate_pr_target(tmp_path, base="dev")

    assert result.returncode == 0


def test_pr_target_validator_blocks_ordinary_main_pull_requests(tmp_path: Path) -> None:
    result = _validate_pr_target(
        tmp_path,
        base="main",
        changed_files=["src/opensquilla/engine/agent.py"],
    )

    assert result.returncode == 1
    assert "Ordinary pull requests should target dev" in result.stderr


def test_pr_target_validator_blocks_unlabeled_docs_only_main_pull_requests(
    tmp_path: Path,
) -> None:
    result = _validate_pr_target(
        tmp_path,
        base="main",
        head="docs/agent-testing",
        title="docs: add agent testing framework guide",
        changed_files=["docs/testing/framework.md"],
    )

    assert result.returncode == 1
    assert "Ordinary pull requests should target dev" in result.stderr


def test_pr_target_validator_allows_maintainer_labeled_main_pull_requests(
    tmp_path: Path,
) -> None:
    labels = [
        "allow-main-target",
        "release",
        "hotfix",
        "main-sync",
        "release-docs",
        "sync-to-main",
        "docs-preview",
    ]
    for label in labels:
        result = _validate_pr_target(
            tmp_path,
            base="main",
            head="release/0.3.2",
            labels=[label],
            changed_files=["src/opensquilla/engine/agent.py"],
        )

        assert result.returncode == 0
        assert "Pull request targets main with maintainer approval label." in result.stdout


def test_pr_target_validator_allows_staging_branch_pull_requests(
    tmp_path: Path,
) -> None:
    for base in [
        "sandbox-optimization",
        "integration/sandbox-hardening",
        "staging/sandbox-hardening",
        "release/0.3.2",
    ]:
        result = _validate_pr_target(
            tmp_path,
            base=base,
            head="pr/sandbox-run-modes-sandbox-optimization",
            changed_files=["src/opensquilla/sandbox/backend/windows_appcontainer.py"],
        )

        assert result.returncode == 0
        assert "staging/collaboration" in result.stdout
        assert "final integration" in result.stdout


def test_pr_target_validator_allows_labeled_staging_pull_requests(
    tmp_path: Path,
) -> None:
    for label in ["maintainer-staging", "collaboration"]:
        result = _validate_pr_target(
            tmp_path,
            base="sandbox-review",
            head="feature/shared-sandbox-work",
            labels=[label],
            changed_files=["src/opensquilla/sandbox/policy.py"],
        )

        assert result.returncode == 0
        assert "staging/collaboration" in result.stdout


def test_pr_target_validator_blocks_unknown_target_branches(tmp_path: Path) -> None:
    result = _validate_pr_target(
        tmp_path,
        base="feature/private-target",
        head="feature/example",
        changed_files=["src/opensquilla/engine/agent.py"],
    )

    assert result.returncode == 1
    assert "Ordinary pull requests should target dev" in result.stderr


def test_pr_target_validator_handles_missing_event_path() -> None:
    env = os.environ.copy()
    env.pop("GITHUB_EVENT_PATH", None)
    env.pop("PR_LABELS", None)
    env["PR_BASE_REF"] = "feature/private-target"

    result = subprocess.run(
        [_bash_executable(), PR_TARGET_VALIDATOR.as_posix()],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Ordinary pull requests should target dev" in result.stderr
    assert "Traceback" not in result.stderr


def test_pr_target_branch_workflow_runs_trusted_base_validator() -> None:
    data = _workflow("pr-target-branch.yml")
    text = (WORKFLOW_DIR / "pr-target-branch.yml").read_text(encoding="utf-8")

    assert _trigger_keys(data) == {"pull_request"}
    assert "pull_request_target" not in text
    assert "Validate target branch" in text
    assert "github.event.repository.default_branch" in text
    assert "hashFiles('.github/scripts/validate-pr-target-branch.sh') == ''" in text
    assert "github.event.pull_request.head.sha" in text
    assert "pull-requests: read" in text
    assert "PR_LABELS" in text
    assert "PR_NUMBER" in text
    assert ".github/scripts/validate-pr-target-branch.sh" in text


def test_pr_body_lint_workflow_warns_from_trusted_base() -> None:
    data = _workflow("pr-body-lint.yml")
    text = (WORKFLOW_DIR / "pr-body-lint.yml").read_text(encoding="utf-8")

    assert _trigger_keys(data) == {"pull_request"}
    assert "pull_request_target" not in text
    assert "Validate PR body fields" in text
    assert "github.event.repository.default_branch" in text
    assert "hashFiles('.github/scripts/validate_pr_body.py') == ''" in text
    assert "github.event.pull_request.head.sha" in text
    assert "pull-requests: read" in text
    assert PR_BODY_LINT.as_posix() in text
    assert "PR_BODY_LINT_STRICT: \"0\"" in text


def test_issue_link_sync_tracks_open_and_closed_final_prs_from_trusted_base() -> None:
    data = _workflow("issue-link-sync.yml")
    text = (WORKFLOW_DIR / "issue-link-sync.yml").read_text(encoding="utf-8")

    pull_request_target = data["on"]["pull_request_target"]
    assert set(pull_request_target["types"]) == {"opened", "reopened", "edited", "closed"}
    assert pull_request_target["branches"] == ["main", "dev"]
    assert "ref: ${{ github.event.pull_request.base.sha }}" in text
    assert "persist-credentials: false" in text
    assert "issues: write" in text
    assert ".github/scripts/issue_link_sync.py" in text


def test_ci_change_classifier_allows_root_and_docs_markdown_only(tmp_path: Path) -> None:
    outputs = _classify_changed_files(
        tmp_path,
        [
            "README.md",
            "CHANGELOG.md",
            "docs/features/skills.md",
            ".github/pull_request_template.md",
        ],
    )

    assert outputs == {
        "docs_only": "true",
        "runtime_changed": "false",
        "test_changed": "false",
        "ci_changed": "false",
        "dependency_changed": "false",
        "release_changed": "false",
    }


def test_classifier_helper_prefers_git_bash_over_windows_wsl_bash(tmp_path: Path) -> None:
    git_bash = tmp_path / "Git" / "bin" / "bash.exe"

    result = _bash_executable(
        os_name="nt",
        path_lookup=lambda _name: r"C:\Windows\System32\bash.exe",
        exists=lambda path: path == git_bash,
        program_files=str(tmp_path),
    )

    assert result == str(git_bash)


def test_ci_change_classifier_accepts_crlf_changed_files(tmp_path: Path) -> None:
    outputs = _classify_changed_files(
        tmp_path,
        ["README.md", "docs/features/skills.md"],
        line_ending="\r\n",
    )

    assert outputs["docs_only"] == "true"
    assert outputs["runtime_changed"] == "false"


def test_ci_change_classifier_treats_runtime_markdown_as_runtime(tmp_path: Path) -> None:
    outputs = _classify_changed_files(
        tmp_path,
        ["src/opensquilla/identity/templates/bootstrap/AGENTS.md"],
    )

    assert outputs["docs_only"] == "false"
    assert outputs["runtime_changed"] == "true"
    assert outputs["test_changed"] == "false"
    assert outputs["ci_changed"] == "false"
    assert outputs["dependency_changed"] == "false"
    assert outputs["release_changed"] == "false"


def test_ci_change_classifier_tracks_test_changes_separately(tmp_path: Path) -> None:
    outputs = _classify_changed_files(
        tmp_path,
        ["tests/test_ci/test_workflows.py"],
    )

    assert outputs["docs_only"] == "false"
    assert outputs["runtime_changed"] == "false"
    assert outputs["test_changed"] == "true"
    assert outputs["ci_changed"] == "false"
    assert outputs["dependency_changed"] == "false"
    assert outputs["release_changed"] == "false"


def test_ci_change_classifier_tracks_ci_dependency_and_release_changes(tmp_path: Path) -> None:
    outputs = _classify_changed_files(
        tmp_path,
        [".github/workflows/ci.yml", ".github/scripts/classify-ci-changes.sh", "uv.lock"],
    )

    assert outputs["docs_only"] == "false"
    assert outputs["runtime_changed"] == "true"
    assert outputs["test_changed"] == "false"
    assert outputs["ci_changed"] == "true"
    assert outputs["dependency_changed"] == "true"
    assert outputs["release_changed"] == "true"


def test_ci_change_classifier_tracks_release_surface_changes(tmp_path: Path) -> None:
    outputs = _classify_changed_files(
        tmp_path,
        [
            ".github/workflows/wheelhouse-release.yml",
            "scripts/build_wheelhouse_zip.py",
            "README.release.md",
            "RELEASES.md",
            "tests/test_scripts/test_build_wheelhouse_zip.py",
        ],
    )

    assert outputs["docs_only"] == "false"
    assert outputs["runtime_changed"] == "true"
    assert outputs["test_changed"] == "true"
    assert outputs["ci_changed"] == "true"
    assert outputs["dependency_changed"] == "false"
    assert outputs["release_changed"] == "true"


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


def test_wheelhouse_release_hydrates_current_router_bundle() -> None:
    text = (WORKFLOW_DIR / "wheelhouse-release.yml").read_text(encoding="utf-8")

    assert "models/v4.2_phase3_inference" in text
    assert 'root / "bge_onnx" / "model.onnx"' in text
    assert 'root / "features" / "tfidf.pkl"' in text
    assert 'root / "lgbm_main.bin"' in text
    assert 'root / "mlp" / "model.onnx"' in text
    assert 'root / "router.runtime.yaml"' in text
    assert "intent_head.joblib" not in text
    assert "router_model.onnx" not in text
