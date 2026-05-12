from __future__ import annotations

import tomllib
from pathlib import Path


def test_pyproject_version_matches_preview_release() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    version = config["project"]["version"]
    assert version == "0.1.0rc1", (
        f"pyproject.toml version must match the preview release; got '{version}'"
    )


def test_recommended_extra_uses_onnx_tokenizers_without_transformers() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    recommended = config["project"]["optional-dependencies"]["recommended"]

    assert any(dep.startswith("onnxruntime") for dep in recommended)
    assert any(dep.startswith("tokenizers") for dep in recommended)
    assert not any(dep.startswith("transformers") for dep in recommended)


def test_recommended_extra_supports_default_pptx_skill() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    recommended = config["project"]["optional-dependencies"]["recommended"]

    assert any(dep.startswith("python-pptx") for dep in recommended)


def test_releases_md_exists_and_references_preview_tag() -> None:
    releases = Path("RELEASES.md")
    assert releases.is_file(), "RELEASES.md must exist at the repository root"
    text = releases.read_text(encoding="utf-8")
    assert "v0.1.0rc1" in text, "RELEASES.md must reference the tag 'v0.1.0rc1'"


def test_changelog_has_preview_section_and_unreleased() -> None:
    changelog = Path("CHANGELOG.md")
    assert changelog.is_file(), "CHANGELOG.md must exist at the repository root"
    text = changelog.read_text(encoding="utf-8")
    assert "[0.1.0rc1]" in text, "CHANGELOG.md must contain a [0.1.0rc1] section"
    assert "[Unreleased]" in text, "CHANGELOG.md must retain an [Unreleased] section"
