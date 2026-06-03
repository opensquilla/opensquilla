from __future__ import annotations

import tomllib
from pathlib import Path

CURRENT_VERSION = "0.3.1"
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
