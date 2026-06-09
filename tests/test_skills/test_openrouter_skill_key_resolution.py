"""Regression tests for bundled OpenRouter skill key fallback.

The bundled scripts are intentionally imported by file path here because the
skill directories contain hyphens and run as standalone subprocess scripts.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE_SCRIPT = (
    REPO_ROOT
    / "src/opensquilla/skills/bundled/nano-banana-pro/scripts/generate_image.py"
)
VIDEO_SCRIPT = (
    REPO_ROOT
    / "src/opensquilla/skills/bundled/seedance-2-prompt/scripts/generate_video.py"
)


def _load_script(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def image_script() -> ModuleType:
    return _load_script(IMAGE_SCRIPT, "_opensquilla_test_generate_image")


@pytest.fixture(scope="module")
def video_script() -> ModuleType:
    return _load_script(VIDEO_SCRIPT, "_opensquilla_test_generate_video")


@pytest.fixture
def isolated_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for name in (
        "OPENROUTER_API_KEY",
        "OPENSQUILLA_LLM_API_KEY",
        "OPENSQUILLA_LLM_PROVIDER",
        "OPENSQUILLA_GATEWAY_CONFIG_PATH",
        "OPENSQUILLA_STATE_DIR",
        "CUSTOM_OPENROUTER_KEY",
        "ARK_API_KEY",
        "VOLC_ARK_API_KEY",
        "BYTEPLUS_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    home.mkdir()
    workspace.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(workspace)
    return tmp_path


def _write_toml(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.strip() + "\n", encoding="utf-8")
    return path


def _resolve_video_openrouter(video_script: ModuleType) -> str | None:
    return video_script._resolve_api_key(
        None,
        ("OPENROUTER_API_KEY",),
        provider_name="openrouter",
    )


def test_openrouter_skills_use_explicit_gateway_config_path(
    image_script: ModuleType,
    video_script: ModuleType,
    isolated_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_toml(
        isolated_runtime / "custom" / "gateway.toml",
        """
        [llm]
        provider = "openrouter"
        api_key = "explicit-config-key"
        """,
    )
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(config_path))

    assert image_script.resolve_api_key(None) == "explicit-config-key"
    assert _resolve_video_openrouter(video_script) == "explicit-config-key"


def test_openrouter_skills_use_configured_api_key_env(
    image_script: ModuleType,
    video_script: ModuleType,
    isolated_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_toml(
        Path.cwd() / "opensquilla.toml",
        """
        [llm]
        provider = "openrouter"
        api_key_env = "CUSTOM_OPENROUTER_KEY"
        """,
    )
    monkeypatch.setenv("CUSTOM_OPENROUTER_KEY", "custom-env-key")

    assert image_script.resolve_api_key(None) == "custom-env-key"
    assert _resolve_video_openrouter(video_script) == "custom-env-key"


def test_openrouter_skills_do_not_treat_other_provider_llm_env_as_openrouter(
    image_script: ModuleType,
    video_script: ModuleType,
    isolated_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("OPENSQUILLA_LLM_API_KEY", "anthropic-key")

    assert image_script.resolve_api_key(None) is None
    assert _resolve_video_openrouter(video_script) is None


def test_selected_config_provider_beats_conflicting_env_provider(
    image_script: ModuleType,
    video_script: ModuleType,
    isolated_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_toml(
        Path.cwd() / "opensquilla.toml",
        """
        [llm]
        provider = "anthropic"
        """,
    )
    monkeypatch.setenv("OPENSQUILLA_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENSQUILLA_LLM_API_KEY", "generic-env-key")

    assert image_script.resolve_api_key(None) is None
    assert _resolve_video_openrouter(video_script) is None


def test_missing_config_provider_can_use_openrouter_env_provider(
    image_script: ModuleType,
    video_script: ModuleType,
    isolated_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_toml(
        Path.cwd() / "opensquilla.toml",
        """
        [llm]
        api_key = "toml-key"
        """,
    )
    monkeypatch.setenv("OPENSQUILLA_LLM_PROVIDER", "openrouter")

    assert image_script.resolve_api_key(None) == "toml-key"
    assert _resolve_video_openrouter(video_script) == "toml-key"


def test_openrouter_skills_do_not_fall_back_to_home_when_state_dir_config_exists(
    image_script: ModuleType,
    video_script: ModuleType,
    isolated_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = isolated_runtime / "state-profile"
    _write_toml(
        state_dir / "config.toml",
        """
        [llm]
        provider = "anthropic"
        api_key = "state-anthropic-key"
        """,
    )
    _write_toml(
        isolated_runtime / "home" / ".opensquilla" / "config.toml",
        """
        [llm]
        provider = "openrouter"
        api_key = "global-openrouter-key"
        """,
    )
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(state_dir))

    assert image_script.resolve_api_key(None) is None
    assert _resolve_video_openrouter(video_script) is None


def test_openrouter_specific_env_still_wins_for_openrouter_skills(
    image_script: ModuleType,
    video_script: ModuleType,
    isolated_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-env-key")
    monkeypatch.setenv("OPENSQUILLA_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("OPENSQUILLA_LLM_API_KEY", "anthropic-key")

    assert image_script.resolve_api_key(None) == "openrouter-env-key"
    assert _resolve_video_openrouter(video_script) == "openrouter-env-key"


def test_non_openrouter_video_provider_uses_only_its_provider_env(
    video_script: ModuleType,
    isolated_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_API_KEY", "ark-key")
    monkeypatch.setenv("OPENSQUILLA_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENSQUILLA_LLM_API_KEY", "openrouter-key")

    assert (
        video_script._resolve_api_key(
            None,
            ("ARK_API_KEY", "VOLC_ARK_API_KEY"),
            provider_name="volcengine",
        )
        == "ark-key"
    )
