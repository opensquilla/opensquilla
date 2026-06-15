from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla import env as env_mod


def _isolate_global_env(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    home.mkdir()
    monkeypatch.setattr(env_mod, "default_opensquilla_home", lambda: home)


def test_load_env_opensquilla_test_overrides_dotenv_before_pytest_current_test(
    monkeypatch,
    tmp_path,
) -> None:
    _isolate_global_env(monkeypatch, tmp_path / "home")
    monkeypatch.setenv("OPENSQUILLA_TEST", "1")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("OPENSQUILLA_ENV_TEST_KEY", raising=False)
    monkeypatch.delenv("OPENSQUILLA_ENV_TEST_SHARED", raising=False)
    monkeypatch.delenv("OPENSQUILLA_ENV_TEST_ONLY", raising=False)

    (tmp_path / ".env").write_text(
        "OPENSQUILLA_ENV_TEST_KEY=from-dotenv\n"
        "OPENSQUILLA_ENV_TEST_SHARED=from-dotenv\n",
        encoding="utf-8",
    )
    (tmp_path / ".env.test").write_text(
        "OPENSQUILLA_ENV_TEST_KEY=from-dotenv-test\n"
        "OPENSQUILLA_ENV_TEST_ONLY=from-dotenv-test\n",
        encoding="utf-8",
    )

    assert env_mod.load_env(tmp_path) == 3
    assert env_mod.os.environ["OPENSQUILLA_ENV_TEST_KEY"] == "from-dotenv-test"
    assert env_mod.os.environ["OPENSQUILLA_ENV_TEST_SHARED"] == "from-dotenv"
    assert env_mod.os.environ["OPENSQUILLA_ENV_TEST_ONLY"] == "from-dotenv-test"


def test_load_env_dotenv_keeps_priority_outside_test_env(monkeypatch, tmp_path) -> None:
    _isolate_global_env(monkeypatch, tmp_path / "home")
    monkeypatch.delenv("OPENSQUILLA_TEST", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("OPENSQUILLA_ENV_TEST_KEY", raising=False)
    monkeypatch.delenv("OPENSQUILLA_ENV_TEST_ONLY", raising=False)

    (tmp_path / ".env").write_text(
        "OPENSQUILLA_ENV_TEST_KEY=from-dotenv\n",
        encoding="utf-8",
    )
    (tmp_path / ".env.test").write_text(
        "OPENSQUILLA_ENV_TEST_KEY=from-dotenv-test\n"
        "OPENSQUILLA_ENV_TEST_ONLY=from-dotenv-test\n",
        encoding="utf-8",
    )

    assert env_mod.load_env(tmp_path) == 2
    assert env_mod.os.environ["OPENSQUILLA_ENV_TEST_KEY"] == "from-dotenv"
    assert env_mod.os.environ["OPENSQUILLA_ENV_TEST_ONLY"] == "from-dotenv-test"


def test_load_env_existing_environment_still_wins_in_test_env(monkeypatch, tmp_path) -> None:
    _isolate_global_env(monkeypatch, tmp_path / "home")
    monkeypatch.setenv("OPENSQUILLA_TEST", "1")
    monkeypatch.setenv("OPENSQUILLA_ENV_TEST_KEY", "from-shell")

    (tmp_path / ".env").write_text(
        "OPENSQUILLA_ENV_TEST_KEY=from-dotenv\n",
        encoding="utf-8",
    )
    (tmp_path / ".env.test").write_text(
        "OPENSQUILLA_ENV_TEST_KEY=from-dotenv-test\n",
        encoding="utf-8",
    )

    assert env_mod.load_env(tmp_path) == 0
    assert env_mod.os.environ["OPENSQUILLA_ENV_TEST_KEY"] == "from-shell"
