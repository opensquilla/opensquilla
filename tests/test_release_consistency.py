from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

CURRENT_VERSION = "0.5.0rc3"
CURRENT_DESKTOP_VERSION = "0.5.0-rc3"
CURRENT_TAG = f"v{CURRENT_VERSION}"
HISTORICAL_PREVIEW_VERSION = "0.2.0rc1"
HISTORICAL_PREVIEW_TAG = f"v{HISTORICAL_PREVIEW_VERSION}"


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
    lock = json.loads(Path("desktop/electron/package-lock.json").read_text(encoding="utf-8"))
    build = package["build"]

    assert package["version"] == CURRENT_DESKTOP_VERSION
    assert lock["version"] == CURRENT_DESKTOP_VERSION
    assert lock["packages"][""]["version"] == CURRENT_DESKTOP_VERSION
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", package["version"])
    assert not re.search(r"(?<=\d)(?:a|b|rc)\d+$", package["version"])
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
    assert "desktop_asset_version" in workflow
    assert "OpenSquilla-{desktop_version}-mac-arm64.dmg" in workflow
    assert "OpenSquilla-{desktop_version}-win-x64.exe" in workflow
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
        if job_name == "build-desktop-macos":
            assert 'OPENSQUILLA_GATEWAY_SMOKE_TIMEOUT_MS: "240000"' in job
        else:
            assert "OPENSQUILLA_GATEWAY_SMOKE_TIMEOUT_MS" not in job


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


def test_release_workflow_keeps_windows_build_unsigned_until_signing_is_available() -> None:
    workflow = Path(".github/workflows/wheelhouse-release.yml").read_text(encoding="utf-8")
    windows_step = workflow.split("- name: Build unsigned Windows installer", 1)[1].split(
        "- name: Verify Electron package", 1
    )[0]

    assert "npx electron-builder --win --publish never" in windows_step
    assert 'CSC_IDENTITY_AUTO_DISCOVERY: "false"' in windows_step
    assert not Path("desktop/electron/electron-builder.release.cjs").exists()

    for env_name in [
        "OPENSQUILLA_WINDOWS_AZURE_SIGNING",
        "AZURE_TENANT_ID",
        "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
        "AZURE_TRUSTED_SIGNING_PUBLISHER_NAME",
        "AZURE_TRUSTED_SIGNING_ENDPOINT",
        "AZURE_TRUSTED_SIGNING_ACCOUNT_NAME",
        "AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE_NAME",
    ]:
        assert env_name not in windows_step

    assert "azureSignOptions" not in workflow
    assert "forceCodeSigning: true" not in workflow
    assert "timestampRfc3161: 'http://timestamp.acs.microsoft.com'" not in workflow


def test_release_docs_describe_unsigned_windows_policy() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    localized_readmes = {
        "zh-Hans": Path("README.zh-Hans.md").read_text(encoding="utf-8"),
        "ja": Path("README.ja.md").read_text(encoding="utf-8"),
        "fr": Path("README.fr.md").read_text(encoding="utf-8"),
        "de": Path("README.de.md").read_text(encoding="utf-8"),
        "es": Path("README.es.md").read_text(encoding="utf-8"),
    }
    releases = Path("RELEASES.md").read_text(encoding="utf-8")
    release_notes = Path(f"docs/releases/{CURRENT_VERSION}.md").read_text(encoding="utf-8")
    signing_policy = Path("docs/code-signing-policy.md").read_text(encoding="utf-8")
    privacy_policy = Path("PRIVACY.md").read_text(encoding="utf-8")

    assert "Code signing policy:" in readme
    assert "Windows builds are currently unsigned" in readme
    assert "Windows desktop installer is currently unsigned" in releases
    assert "Windows release builds are currently unsigned" in signing_policy
    assert "claim Windows code signing" in signing_policy
    assert "[`PRIVACY.md`](../PRIVACY.md)" in signing_policy
    assert "[@Open-Squilla](https://github.com/Open-Squilla)" in signing_policy
    assert "Initial SignPath approvers" in signing_policy
    assert "network observability" in signing_policy

    for text in [readme, releases, release_notes]:
        assert "code-signing-policy.md" in text

    assert "PRIVACY.md" in readme
    assert "THIRD_PARTY_NOTICES.md" in readme
    assert "Installation Telemetry" in privacy_policy
    assert "OPENSQUILLA_TELEMETRY_DISABLED=true" in privacy_policy
    assert "future signing plan" not in readme

    for text in [readme, releases]:
        assert "signed desktop installers" not in text

    for locale, phrase in {
        "zh-Hans": "已签名的桌面",
        "ja": "署名済みのデスクトップ",
        "fr": "installateurs de bureau signés",
        "de": "signierten Desktop",
        "es": "instaladores de escritorio firmados",
    }.items():
        assert phrase not in localized_readmes[locale]


def test_privacy_docs_describe_network_observability_controls() -> None:
    docs = {
        "README.md": Path("README.md").read_text(encoding="utf-8"),
        "README.zh-Hans.md": Path("README.zh-Hans.md").read_text(encoding="utf-8"),
        "PRIVACY.md": Path("PRIVACY.md").read_text(encoding="utf-8"),
        "RELEASES.md": Path("RELEASES.md").read_text(encoding="utf-8"),
        f"docs/releases/{CURRENT_VERSION}.md": Path(
            f"docs/releases/{CURRENT_VERSION}.md"
        ).read_text(encoding="utf-8"),
        "docs/code-signing-policy.md": Path("docs/code-signing-policy.md").read_text(
            encoding="utf-8"
        ),
    }

    for path, text in docs.items():
        assert "OPENSQUILLA_PRIVACY_DISABLE_NETWORK_OBSERVABILITY=true" in text, path
        assert "disable_network_observability = true" in text, path
        assert "OPENSQUILLA_TELEMETRY_DISABLED=true" in text, path
        assert "OPENSQUILLA_UPDATE_CHECK_DISABLED=true" in text, path

    privacy = docs["PRIVACY.md"]
    assert "automatic install telemetry" in privacy
    assert "passive update checks" in privacy
    assert "desktop startup auto-update checks" in privacy
    assert "Manual user-initiated actions may still contact network services" in privacy


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
    assert (
        HISTORICAL_PREVIEW_TAG in text
    ), f"RELEASES.md must retain the historical tag '{HISTORICAL_PREVIEW_TAG}'"
    assert f"OpenSquilla-{CURRENT_DESKTOP_VERSION}-mac-arm64.dmg" in text
    assert f"OpenSquilla-{CURRENT_DESKTOP_VERSION}-win-x64.exe" in text
    assert "do not publish Windows portable zips" in text
    assert "legacy Windows portable downloads" in text
    assert "separately branded macOS or Linux portable bundles" in text
    assert "macOS `.zip` is the Electron desktop and updater artifact" in text
    assert "macOS portable zips" not in text
    assert "`0.5.0rc4` /\n    `v0.5.0rc4`" in text
    assert "tracks the most recently pushed release tag" in text


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

    assert f"OpenSquilla-{CURRENT_DESKTOP_VERSION}-mac-arm64.dmg" in readme
    assert f"OpenSquilla-{CURRENT_DESKTOP_VERSION}-win-x64.exe" in readme
    assert "Simplified release assets" in readme
    assert "Electron installers" in readme
    assert "versioned Python wheel" in readme
    assert "releases/latest/download/OpenSquilla-windows-x64-portable.zip" not in readme
    assert (
        f"releases/download/{CURRENT_TAG}/opensquilla-{CURRENT_VERSION}-py3-none-any.whl"
        in readme
    )
    assert "opensquilla-latest-py3-none-any.whl" not in readme
    assert "Python wheel installs use versioned wheel filenames" in readme
    assert "Release install commands use published GitHub release assets" in readme


def test_all_readmes_default_install_paths_to_the_current_preview() -> None:
    wheel_url = (
        f"releases/download/{CURRENT_TAG}/opensquilla-{CURRENT_VERSION}-py3-none-any.whl"
    )
    readmes = [
        Path("README.md"),
        Path("README.zh-Hans.md"),
        Path("README.ja.md"),
        Path("README.fr.md"),
        Path("README.de.md"),
        Path("README.es.md"),
    ]

    for path in readmes:
        text = path.read_text(encoding="utf-8")
        assert f"OpenSquilla-{CURRENT_DESKTOP_VERSION}-mac-arm64.dmg" in text, path
        assert f"OpenSquilla-{CURRENT_DESKTOP_VERSION}-win-x64.exe" in text, path
        assert wheel_url in text, path
        assert "ghcr.io/opensquilla/opensquilla:latest" in text, path
        assert "0.5.0-Preview-2-Desktop" not in text, path


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
    assert "0.5+ release assets must not include Windows portable zips" in workflow
    assert "OpenSquilla-windows-x64-portable.zip" not in workflow
    assert "opensquilla-latest-py3-none-any.whl" not in workflow


def test_container_workflow_gates_latest_promotion() -> None:
    workflow = Path(".github/workflows/docker-image.yml").read_text(encoding="utf-8")

    assert 'tags:\n      - "v*"' in workflow
    assert 'tag_version="${GITHUB_REF_NAME#v}"' in workflow
    assert 'project["project"]["version"]' in workflow
    assert "does not match project version" in workflow
    assert "packages: write" in workflow
    assert "platforms: linux/amd64,linux/arm64" in workflow
    assert "type=ref,event=tag" in workflow
    assert "type=raw,value=latest" not in workflow
    assert "provenance: false" in workflow
    assert "most recently pushed release tag" in workflow
    assert '["docker", "buildx", "imagetools", "inspect", image_ref, "--raw"]' in workflow
    assert 'expected = {"linux/amd64", "linux/arm64"}' in workflow
    assert 'docker run --detach --pull=always "${IMAGE_REF}"' in workflow
    assert ".State.Health.Status" in workflow
    assert '[[ "${health}" == "healthy" ]]' in workflow
    assert "docker buildx imagetools create" in workflow

    build = workflow.index("- name: Build multi-arch image")
    verify = workflow.index("- name: Verify pushed manifest platforms")
    smoke = workflow.index("- name: Smoke pushed image HEALTHCHECK")
    promote = workflow.index("- name: Promote verified release image to latest")
    assert build < verify < smoke < promote


def test_historical_040_release_notes_remain_available() -> None:
    notes = Path("docs/releases/0.4.0.md").read_text(encoding="utf-8")

    assert "# OpenSquilla 0.4.0" in notes
    assert "OpenSquilla-0.4.0-mac-arm64.dmg" in notes


def test_current_release_notes_cover_migration_upgrade_and_containers() -> None:
    notes = Path(f"docs/releases/{CURRENT_VERSION}.md").read_text(encoding="utf-8")

    assert "## Downloads" in notes
    assert f"OpenSquilla-{CURRENT_DESKTOP_VERSION}-mac-arm64.dmg" in notes
    assert f"OpenSquilla-{CURRENT_DESKTOP_VERSION}-mac-arm64.zip" in notes
    assert f"OpenSquilla-{CURRENT_DESKTOP_VERSION}-win-x64.exe" in notes
    assert f"opensquilla-{CURRENT_VERSION}-py3-none-any.whl" in notes
    assert notes.index("### Legacy home migration and upgrade safety") < notes.index(
        "### Providers, models, and routing"
    )
    assert notes.index("### Providers, models, and routing") < notes.index(
        "### Desktop, terminal, and Control UI"
    )
    assert notes.index("### Runtime, safety, and data reliability") < notes.index(
        "### Container deployment"
    )
    assert "No Windows portable assets are published for 0.5.0 preview releases" in notes
    assert "0.5.0rc3 portable zip" in notes
    assert "## Upgrading from Preview 2, Preview 1, or 0.4.1" in notes
    assert "should not wait for an in-app RC3\nnotification" in notes
    assert "ghcr.io/opensquilla/opensquilla:v0.5.0rc3" in notes
    assert "Docker `latest` follows the most recently pushed release tag" in notes
    assert (
        "Configuration\nformats from every released OpenSquilla version remain supported"
        in notes
    )
    assert "Synthetic fixtures" not in notes
    assert "release gate" not in notes
    assert "## Acknowledgements" in notes
    for login in [
        "@ab2ence",
        "@JarvisPei",
        "@labulalala",
        "@Liu-RK",
        "@lyteen",
        "@nice-code-la",
        "@TUOXI293",
    ]:
        assert login in notes
    assert "CONTRIBUTORS.md" in notes


def test_docs_index_links_current_release_notes() -> None:
    index = Path("docs/README.md").read_text(encoding="utf-8")

    assert f"releases/{CURRENT_VERSION}.md" in index
    assert "releases/0.4.0.md" in index


def test_current_contributor_ledger_records_050rc3_attribution() -> None:
    ledger = Path("CONTRIBUTORS.md").read_text(encoding="utf-8")
    section = ledger.split("## OpenSquilla 0.5.0rc3", 1)[1].split(
        "## OpenSquilla 0.5.0rc2", 1
    )[0]

    expected = {
        "@ab2ence": "#491",
        "@JarvisPei": "#550",
        "@labulalala": "#502",
        "@Liu-RK": "#486",
        "@lyteen": "#212",
        "@nice-code-la": "#560",
        "@TUOXI293": "#487",
    }
    for login, evidence in expected.items():
        assert login in section
        assert evidence in section
    assert "Codex" not in section
    assert "Claude Code" not in section
