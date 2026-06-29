from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

CURRENT_VERSION = "0.4.1"
CURRENT_TAG = f"v{CURRENT_VERSION}"
PREVIEW_VERSION = "0.2.0rc1"
PREVIEW_TAG = f"v{PREVIEW_VERSION}"


def test_pyproject_version_matches_current_release() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    version = config["project"]["version"]
    assert version == CURRENT_VERSION, (
        f"pyproject.toml version must match the current release; got '{version}'"
    )


def test_lockfile_version_matches_current_release() -> None:
    lock = tomllib.loads(Path("uv.lock").read_text(encoding="utf-8"))
    package = next(item for item in lock["package"] if item["name"] == "opensquilla")

    assert package["version"] == CURRENT_VERSION


def test_desktop_electron_release_config_matches_current_release() -> None:
    package = json.loads(Path("desktop/electron/package.json").read_text(encoding="utf-8"))
    build = package["build"]

    assert package["version"] == CURRENT_VERSION
    assert package["repository"] == {
        "type": "git",
        "url": "https://github.com/opensquilla/opensquilla.git",
    }
    assert build["artifactName"] == "OpenSquilla-${version}-${os}-${arch}.${ext}"
    assert build["mac"]["target"] == ["dmg", "zip"]
    assert build["mac"].get("identity", "auto") is not None
    assert build["win"]["target"] == ["nsis"]
    assert build["nsis"]["oneClick"] is False
    assert build["nsis"]["allowToChangeInstallationDirectory"] is True


def test_release_workflow_builds_desktop_installers() -> None:
    workflow = Path(".github/workflows/wheelhouse-release.yml").read_text(encoding="utf-8")

    assert "name: Release Assets" in workflow
    assert "build-desktop-macos:" in workflow
    assert "build-desktop-windows:" in workflow
    assert "npx electron-builder --mac --publish never" in workflow
    assert "npx electron-builder --win --publish never" in workflow
    assert "OpenSquilla-{version}-mac-arm64.dmg" in workflow
    assert "OpenSquilla-{version}-win-x64.exe" in workflow
    assert "latest-mac.yml" in workflow
    assert "latest.yml" in workflow
    assert "NOTES_FILE=\"docs/releases/${TAG#v}.md\"" in workflow
    assert "--notes-file \"${NOTES_FILE}\"" in workflow
    assert "gh release upload \"${TAG}\" dist/* --clobber" in workflow


def test_release_workflow_hydrates_and_smokes_desktop_router_runtime() -> None:
    workflow = Path(".github/workflows/wheelhouse-release.yml").read_text(encoding="utf-8")

    for job_name in ["build-desktop-macos", "build-desktop-windows"]:
        start = workflow.index(f"  {job_name}:")
        end = len(workflow)
        for next_job in ["build-desktop-windows", "publish-release"]:
            marker = f"\n  {next_job}:"
            pos = workflow.find(marker, start + 1)
            if pos != -1:
                end = min(end, pos)
        job = workflow[start:end]
        assert "lfs: true" in job
        assert 'git lfs pull --include="src/opensquilla/squilla_router/models/**"' in job
        assert "npm run build:gateway" in job
        assert "npm run verify:package" in job
        assert "npm run verify:gateway-smoke" in job
        assert 'OPENSQUILLA_REQUIRE_PACKAGED_GATEWAY_SMOKE: "1"' in job


def test_release_workflow_keeps_macos_signing_identity_auto_selected() -> None:
    workflow = Path(".github/workflows/wheelhouse-release.yml").read_text(encoding="utf-8")
    mac_step = workflow.split("- name: Build signed macOS installer", 1)[1].split(
        "- name: Verify Electron package", 1
    )[0]

    assert "CSC_LINK: ${{ secrets.MAC_CSC_LINK }}" in mac_step
    assert "CSC_KEY_PASSWORD: ${{ secrets.MAC_CSC_KEY_PASSWORD }}" in mac_step
    assert "APPLE_ID: ${{ secrets.APPLE_ID }}" in mac_step
    assert "CSC_NAME" not in mac_step
    assert "GH_TOKEN" not in mac_step


def _dep_names(specs: list[str]) -> set[str]:
    names: set[str] = set()
    for spec in specs:
        head = spec.strip()
        for sep in ("[", " ", ";", "=", ">", "<", "~", "!"):
            head = head.split(sep, 1)[0]
        if head:
            names.add(head.lower())
    return names


def test_recommended_extra_uses_onnx_tokenizers_without_transformers() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    recommended = config["project"]["optional-dependencies"]["recommended"]

    assert any(dep.startswith("onnxruntime") for dep in recommended)
    assert any(dep.startswith("tokenizers") for dep in recommended)
    assert not any(dep.startswith("transformers") for dep in recommended)


def test_default_recommended_install_contract_covers_router_and_channels() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    project = config["project"]
    dependencies = _dep_names(project["dependencies"])
    extras = project["optional-dependencies"]
    recommended = _dep_names(extras["recommended"])

    assert {
        "lightgbm",
        "numpy",
        "onnxruntime",
        "scikit-learn",
        "tokenizers",
    } <= recommended
    assert {
        "cryptography",  # WeCom callback crypto
        "dingtalk-stream",
        "httpx",  # Slack, Telegram, Feishu, WeCom HTTP calls
        "lark-oapi",
        "python-telegram-bot",
        "qq-botpy",
        "websockets",  # Discord gateway and Feishu SDK transport
    } <= dependencies
    for alias in ("feishu", "telegram", "dingtalk", "wecom", "qq"):
        assert alias not in extras

    assert "matrix-nio" in "\n".join(extras["matrix"])


def test_core_dependencies_support_default_pptx_skill() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = config["project"]["dependencies"]

    assert any(dep.startswith("python-pptx") for dep in dependencies)


def test_releases_md_exists_and_references_current_and_preview_tags() -> None:
    releases = Path("RELEASES.md")
    assert releases.is_file(), "RELEASES.md must exist at the repository root"
    text = releases.read_text(encoding="utf-8")
    assert CURRENT_TAG in text, f"RELEASES.md must reference the tag '{CURRENT_TAG}'"
    assert PREVIEW_TAG in text, f"RELEASES.md must reference the tag '{PREVIEW_TAG}'"
    assert f"OpenSquilla-{CURRENT_VERSION}-mac-arm64.dmg" in text
    assert f"OpenSquilla-{CURRENT_VERSION}-win-x64.exe" in text
    assert "legacy Windows portable" in text


def test_changelog_has_current_release_section_and_unreleased() -> None:
    changelog = Path("CHANGELOG.md")
    assert changelog.is_file(), "CHANGELOG.md must exist at the repository root"
    text = changelog.read_text(encoding="utf-8")
    assert (
        f"[{CURRENT_VERSION}]" in text
    ), f"CHANGELOG.md must contain a [{CURRENT_VERSION}] section"
    assert "[Unreleased]" in text, "CHANGELOG.md must retain an [Unreleased] section"


def test_readme_release_install_uses_latest_assets_and_pinned_alternative() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert f"OpenSquilla-{CURRENT_VERSION}-mac-arm64.dmg" in readme
    assert f"OpenSquilla-{CURRENT_VERSION}-win-x64.exe" in readme
    assert "legacy compatibility package" in readme
    assert (
        "releases/latest/download/OpenSquilla-windows-x64-portable.zip"
        in readme
    )
    assert (
        f"releases/download/{CURRENT_TAG}/opensquilla-{CURRENT_VERSION}-py3-none-any.whl"
        in readme
    )
    assert "opensquilla-latest-py3-none-any.whl" not in readme
    assert "Python wheel installs use versioned wheel filenames" in readme
    assert "Release install commands use published GitHub release assets" in readme


def test_user_facing_install_docs_use_current_release_wheel() -> None:
    current_wheel_url = (
        f"releases/download/{CURRENT_TAG}/opensquilla-{CURRENT_VERSION}-py3-none-any.whl"
    )
    wheel_url_pattern = re.compile(
        r"releases/download/v(?P<tag_version>[^/]+)/"
        r"opensquilla-(?P<file_version>[^/]+)-py3-none-any\.whl"
    )
    install_docs = [
        Path("README.md"),
        Path("README.product.md"),
        Path("docs/quickstart.md"),
        Path("docs/cli.md"),
        Path("docs/mcp-server.md"),
        Path("docs/operations.md"),
    ]

    for path in install_docs:
        text = path.read_text(encoding="utf-8")
        wheel_urls = list(wheel_url_pattern.finditer(text))

        assert wheel_urls, f"{path} must include a pinned release wheel URL"
        assert current_wheel_url in text, f"{path} must install from {CURRENT_TAG}"
        for match in wheel_urls:
            assert match.group("tag_version") == CURRENT_VERSION
            assert match.group("file_version") == CURRENT_VERSION


def test_release_installers_default_to_current_tag() -> None:
    for path in [Path("install.sh"), Path("install.ps1")]:
        text = path.read_text(encoding="utf-8")
        assert CURRENT_TAG in text
        assert "opensquilla-$releaseVersion-py3-none-any.whl" in text or (
            "opensquilla-${release_version}-py3-none-any.whl" in text
        )
        assert "opensquilla-latest-py3-none-any.whl" not in text


def test_release_workflow_marks_preview_tags_as_prereleases() -> None:
    workflow = Path(".github/workflows/wheelhouse-release.yml").read_text(encoding="utf-8")

    assert "IS_PRERELEASE" in workflow
    assert "--prerelease" in workflow
    assert "OpenSquilla {match.group(1)} Preview {match.group(2)}" in workflow
    assert "is_prerelease = bool(re.search" in workflow
    assert "if not is_prerelease:" in workflow
    assert "expected.add(\"OpenSquilla-windows-x64-portable.zip\")" in workflow
    assert "opensquilla-latest-py3-none-any.whl" not in workflow


def test_historical_040_release_notes_remain_available() -> None:
    notes = Path("docs/releases/0.4.0.md").read_text(encoding="utf-8")

    assert "# OpenSquilla 0.4.0" in notes
    assert "OpenSquilla-0.4.0-mac-arm64.dmg" in notes


def test_current_release_notes_prioritize_desktop_and_legacy_portable() -> None:
    notes = Path(f"docs/releases/{CURRENT_VERSION}.md").read_text(encoding="utf-8")

    assert "## Downloads" in notes
    assert f"OpenSquilla-{CURRENT_VERSION}-mac-arm64.dmg" in notes
    assert f"OpenSquilla-{CURRENT_VERSION}-mac-arm64.zip" in notes
    assert f"OpenSquilla-{CURRENT_VERSION}-win-x64.exe" in notes
    assert f"opensquilla-{CURRENT_VERSION}-py3-none-any.whl" in notes
    assert "Legacy Windows portable" in notes
    assert "legacy compatibility" in notes
    assert "## Upgrading from 0.4.0" in notes
    assert "## Acknowledgements" in notes
    assert "@ab2ence" in notes


def test_docs_index_links_current_release_notes() -> None:
    index = Path("docs/README.md").read_text(encoding="utf-8")

    assert f"releases/{CURRENT_VERSION}.md" in index
    assert "releases/0.4.0.md" in index


def test_current_contributor_ledger_records_041_attribution_without_repeating_040() -> None:
    ledger = Path("CONTRIBUTORS.md").read_text(encoding="utf-8")
    section = ledger.split("## OpenSquilla 0.4.1", 1)[1].split("## OpenSquilla 0.4.0", 1)[0]

    assert "@ab2ence" in section
    assert "#348" in section
    assert "#355" in section
    assert "@nice-code-la" not in section
    assert "Codex" not in section
    assert "Claude Code" not in section
