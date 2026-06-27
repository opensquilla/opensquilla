"""Unit tests for opensquilla.contrib.swebench.config."""

import sys
from pathlib import Path

import pytest

from opensquilla.contrib.swebench import config


class TestImageNaming:
    def test_harness_image_name(self):
        assert (
            config.instance_id_to_image("django__django-16429")
            == "sweb.eval.x86_64.django__django-16429:latest"
        )

    def test_sweagent_image_name(self):
        assert (
            config.instance_id_to_image_sweagent("django__django-16429")
            == "swebench/sweb.eval.x86_64.django_1776_django-16429:latest"
        )

    def test_sweagent_image_name_lowercases(self):
        assert (
            config.instance_id_to_image_sweagent("PrestaShop__PrestaShop-123")
            == "swebench/sweb.eval.x86_64.prestashop_1776_prestashop-123:latest"
        )

    def test_container_name(self):
        assert (
            config.instance_id_to_container("django__django-16429")
            == "opensquilla-swe-django__django-16429"
        )


class TestDerivedPaths:
    def test_env_path_defaults_to_prefix(self, monkeypatch):
        monkeypatch.delenv("OPENSQUILLA_SWEBENCH_ENV_PATH", raising=False)
        assert config.env_path() == sys.prefix

    def test_env_path_override(self, monkeypatch):
        monkeypatch.setenv("OPENSQUILLA_SWEBENCH_ENV_PATH", "/opt/some-env")
        assert config.env_path() == "/opt/some-env"

    def test_python_home_defaults_to_base_prefix(self, monkeypatch):
        monkeypatch.delenv("OPENSQUILLA_SWEBENCH_PYTHON_HOME", raising=False)
        assert config.python_home() == sys.base_prefix

    def test_python_bin_follows_home_override(self, monkeypatch):
        monkeypatch.delenv("OPENSQUILLA_SWEBENCH_PYTHON_BIN", raising=False)
        monkeypatch.setenv("OPENSQUILLA_SWEBENCH_PYTHON_HOME", "/opt/py")
        assert config.python_bin() == f"/opt/py/bin/python3.{sys.version_info.minor}"

    def test_site_packages_for_overridden_env(self, monkeypatch):
        monkeypatch.delenv("OPENSQUILLA_SWEBENCH_SITE_PACKAGES", raising=False)
        monkeypatch.setenv("OPENSQUILLA_SWEBENCH_ENV_PATH", "/opt/some-env")
        assert (
            config.site_packages()
            == f"/opt/some-env/lib/python3.{sys.version_info.minor}/site-packages"
        )

    def test_artifacts_root_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OPENSQUILLA_SWEBENCH_ARTIFACTS_DIR", str(tmp_path))
        assert config.artifacts_root() == tmp_path
        assert config.get_artifact_dir("run1", "inst1") == tmp_path / "run1" / "inst1"
        assert config.get_state_path("run1") == tmp_path / "run1" / "state.jsonl"
        assert config.get_predictions_path("run1") == tmp_path / "run1" / "predictions.jsonl"

    @pytest.mark.skipif(sys.platform == "win32", reason="code-task Windows support is WIP")
    def test_container_pythonpath_ends_with_site_packages(self, monkeypatch):
        monkeypatch.delenv("OPENSQUILLA_SWEBENCH_SITE_PACKAGES", raising=False)
        monkeypatch.delenv("OPENSQUILLA_SWEBENCH_ENV_PATH", raising=False)
        parts = config.container_pythonpath().split(":")
        assert parts[-1] == config.site_packages()
        # Editable installs prepend the source tree; either way every part
        # must be an absolute path.
        assert all(Path(p).is_absolute() for p in parts)


class TestPackagedData:
    def test_prompt_template_shipped(self, monkeypatch):
        monkeypatch.delenv("OPENSQUILLA_SWEBENCH_PROMPT_TEMPLATE", raising=False)
        path = config.prompt_template_path()
        assert path.exists()
        content = path.read_text()
        assert "{problem_statement}" in content
        assert "{base_commit}" in content

    def test_container_config_shipped(self, monkeypatch):
        monkeypatch.delenv("OPENSQUILLA_SWEBENCH_CONFIG_DIR", raising=False)
        config_dir = config.container_config_dir()
        assert (config_dir / "config.toml").exists()
