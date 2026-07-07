"""The multi-level settings entry points: the `onboard configure` section hub
and the re-run fork in `opensquilla onboard`.

Contract under test:
- Bare `configure` on a TTY is a menu LOOP (edit a section, come back, Done
  exits); an explicit section stays a one-shot edit.
- Cancelling inside a section returns to the menu; cancelling at the menu
  itself raises like every other wizard prompt.
- Restart-required guidance survives multi-section sittings.
- A full interactive re-run over a configured install offers
  update / change-sections / start-fresh, and start-fresh backs the config
  file up instead of deleting it.

Everything is offline: prompts are faked at the questionary seam and section
runners are monkeypatched.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from opensquilla.onboarding import flow
from opensquilla.onboarding.config_store import PersistResult, load_config, persist_config
from opensquilla.onboarding.errors import UserCancelledError
from opensquilla.onboarding.flow import OnboardOptions
from opensquilla.onboarding.mutations import upsert_llm_provider


class _Answer:
    def __init__(self, value: Any) -> None:
        self.value = value

    def ask(self) -> Any:
        return self.value


class _BaseQuestionary(types.SimpleNamespace):
    def confirm(self, message: str, **_kwargs: Any) -> _Answer:
        raise AssertionError(f"unexpected confirm prompt: {message}")

    def select(self, message: str, **_kwargs: Any) -> _Answer:
        raise AssertionError(f"unexpected select prompt: {message}")

    def text(self, message: str, **_kwargs: Any) -> _Answer:
        raise AssertionError(f"unexpected text prompt: {message}")

    def password(self, message: str, **_kwargs: Any) -> _Answer:
        raise AssertionError(f"unexpected password prompt: {message}")

    def checkbox(self, message: str, **_kwargs: Any) -> _Answer:
        raise AssertionError(f"unexpected checkbox prompt: {message}")


def _persist_result(target, *, restart_required=False, warnings=()):
    return PersistResult(
        path=target,
        backup_path=None,
        restart_required=restart_required,
        warnings=list(warnings),
    )


def _pick_done(titles: list[str]) -> str:
    return next(t for t in titles if t in ("Done", "Exit (nothing changed)"))


def _seed_configured_install(target) -> None:
    cfg = load_config(target)
    res = upsert_llm_provider(
        cfg,
        provider_id="openrouter",
        model="dummy/model",
        api_key="sk-dummy-hub-test",
    )
    persist_config(res.config, path=target, restart_required=False, backup=False)


# --- the configure hub -----------------------------------------------------


def test_hub_loops_dispatching_multiple_sections_then_done(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    dispatched: list[str] = []

    def _fake_runner(name, *, restart_required=False):
        def runner(config_path=None):
            assert config_path == target
            dispatched.append(name)
            return _persist_result(target, restart_required=restart_required)

        return runner

    monkeypatch.setattr(
        flow, "run_interactive_search_configure", _fake_runner("search")
    )
    monkeypatch.setattr(
        flow,
        "run_interactive_image_generation_configure",
        _fake_runner("image-generation", restart_required=True),
    )

    menus: list[list[str]] = []

    class _Questionary(_BaseQuestionary):
        def select(self, message: str, **kwargs: Any) -> _Answer:
            assert message == "Section"
            titles = kwargs["choices"]
            menus.append(titles)
            if len(menus) == 1:
                return _Answer(next(t for t in titles if t.startswith("Web search")))
            if len(menus) == 2:
                return _Answer(
                    next(t for t in titles if t.startswith("Image generation"))
                )
            return _Answer(_pick_done(titles))

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    result = flow.run_interactive_configure(config_path=target)

    assert dispatched == ["search", "image-generation"]
    assert len(menus) == 3, "the menu must reappear after each section"
    assert result is not None
    assert result.restart_required is True, "restart flag must stay sticky"


def test_hub_menu_titles_carry_live_status_words(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    seen: dict[str, list[str]] = {}

    class _Questionary(_BaseQuestionary):
        def select(self, message: str, **kwargs: Any) -> _Answer:
            seen["titles"] = kwargs["choices"]
            return _Answer(_pick_done(kwargs["choices"]))

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    result = flow.run_interactive_configure(config_path=target)

    assert result is None
    titles = seen["titles"]
    # Fresh install: provider setup is outstanding, search is a deliberate
    # later. The exact words come from the shared SECTION_STATUS_DISPLAY map.
    assert any(t.startswith("Provider — ") for t in titles)
    assert "Provider — Missing" in titles
    assert "Channels — Later" in titles
    assert titles[-1] == "Exit (nothing changed)"
    # Audio has no configure path and must not be offered as a menu entry.
    assert not any(t.lower().startswith("voice audio") for t in titles)
    assert not any(t.lower().startswith("audio") for t in titles)


def test_hub_section_cancel_returns_to_menu_instead_of_aborting(
    tmp_path, monkeypatch
):
    target = tmp_path / "c.toml"
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    attempts: list[str] = []

    def _cancelling_runner(config_path=None):
        attempts.append("search")
        raise UserCancelledError("search")

    monkeypatch.setattr(flow, "run_interactive_search_configure", _cancelling_runner)
    menu_calls = {"n": 0}

    class _Questionary(_BaseQuestionary):
        def select(self, message: str, **kwargs: Any) -> _Answer:
            menu_calls["n"] += 1
            titles = kwargs["choices"]
            if menu_calls["n"] == 1:
                return _Answer(next(t for t in titles if t.startswith("Web search")))
            return _Answer(_pick_done(titles))

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    result = flow.run_interactive_configure(config_path=target)

    assert attempts == ["search"]
    assert menu_calls["n"] == 2, "cancel inside a section must return to the menu"
    assert result is None


def test_hub_menu_cancel_raises_user_cancelled(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setattr(flow, "_is_tty", lambda: True)

    class _Questionary(_BaseQuestionary):
        def select(self, message: str, **kwargs: Any) -> _Answer:
            return _Answer(None)  # questionary returns None on Esc/Ctrl-C

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    with pytest.raises(UserCancelledError):
        flow.run_interactive_configure(config_path=target)


def test_hub_merges_warnings_across_sections(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setattr(flow, "_is_tty", lambda: True)

    monkeypatch.setattr(
        flow,
        "run_interactive_search_configure",
        lambda config_path=None: _persist_result(target, warnings=["w-search"]),
    )
    monkeypatch.setattr(
        flow,
        "run_interactive_image_generation_configure",
        lambda config_path=None: _persist_result(target, warnings=["w-image"]),
    )
    step = {"n": 0}

    class _Questionary(_BaseQuestionary):
        def select(self, message: str, **kwargs: Any) -> _Answer:
            step["n"] += 1
            titles = kwargs["choices"]
            if step["n"] == 1:
                return _Answer(next(t for t in titles if t.startswith("Web search")))
            if step["n"] == 2:
                return _Answer(
                    next(t for t in titles if t.startswith("Image generation"))
                )
            return _Answer(_pick_done(titles))

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    result = flow.run_interactive_configure(config_path=target)

    assert result is not None
    assert result.warnings == ["w-search", "w-image"]


def test_explicit_section_stays_one_shot(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    dispatched: list[str] = []
    monkeypatch.setattr(
        flow,
        "run_interactive_search_configure",
        lambda config_path=None: (dispatched.append("search"), _persist_result(target))[1],
    )

    class _Questionary(_BaseQuestionary):
        pass  # any menu render would raise via the base class

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    result = flow.run_interactive_configure("search", config_path=target)

    assert dispatched == ["search"]
    assert result is not None


# --- the onboard re-run fork -------------------------------------------------


def test_rerun_fork_routes_change_sections_to_the_hub(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    _seed_configured_install(target)
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    monkeypatch.setattr(flow, "_wait_for_setup_start", lambda: None)
    monkeypatch.setattr(flow, "_ensure_config_dir_writable", lambda _path: None)
    hub_calls: list[Any] = []
    sentinel = _persist_result(target, restart_required=True)

    def _fake_hub(questionary, *, config_path=None):
        hub_calls.append(config_path)
        return sentinel

    monkeypatch.setattr(flow, "_run_configure_hub", _fake_hub)

    class _Questionary(_BaseQuestionary):
        def select(self, message: str, **kwargs: Any) -> _Answer:
            assert message.startswith("This install is already configured")
            assert kwargs["default"] == flow._ONBOARD_UPDATE_CHOICE
            return _Answer(flow._ONBOARD_SECTIONS_CHOICE)

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    result = flow.run_interactive_onboard(OnboardOptions(config_path=target))

    assert hub_calls == [target]
    assert result is sentinel


def test_rerun_fork_start_fresh_backs_up_config_and_restarts_walk(
    tmp_path, monkeypatch
):
    target = tmp_path / "c.toml"
    _seed_configured_install(target)
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    monkeypatch.setattr(flow, "_wait_for_setup_start", lambda: None)
    monkeypatch.setattr(flow, "_ensure_config_dir_writable", lambda _path: None)
    monkeypatch.setattr(
        flow, "_run_onboard_migration_step", lambda *_a, **_kw: None
    )

    class _Questionary(_BaseQuestionary):
        def select(self, message: str, **kwargs: Any) -> _Answer:
            if message.startswith("This install is already configured"):
                return _Answer(flow._ONBOARD_RESET_CHOICE)
            if message == "LLM provider":
                # The walk restarted from scratch; cancel here to end the test.
                return _Answer(None)
            raise AssertionError(f"unexpected select prompt: {message}")

        def confirm(self, message: str, **kwargs: Any) -> _Answer:
            assert message.startswith("Back up")
            assert kwargs["default"] is False
            return _Answer(True)

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    with pytest.raises(UserCancelledError):
        flow.run_interactive_onboard(OnboardOptions(config_path=target))

    backups = list(tmp_path.glob("c.toml.bak-*"))
    assert len(backups) == 1, "start fresh must back the old config up, not delete it"
    assert "sk-dummy-hub-test" in backups[0].read_text()
    assert not target.exists() or "sk-dummy-hub-test" not in target.read_text()


def test_start_fresh_backs_up_symlink_target_without_replacing_link(tmp_path):
    real = tmp_path / "real-config.toml"
    link = tmp_path / "config.toml"
    real.write_text("port = 18791\n")
    link.symlink_to(real)

    flow._backup_and_reset_config(link)

    assert link.is_symlink()
    assert not real.exists()
    backups = list(tmp_path.glob("real-config.toml.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == "port = 18791\n"


def test_rerun_fork_decline_reset_falls_back_to_update(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    _seed_configured_install(target)
    cfg = load_config(target)
    status = flow.get_onboarding_status(cfg)

    class _Questionary(_BaseQuestionary):
        def select(self, message: str, **kwargs: Any) -> _Answer:
            return _Answer(flow._ONBOARD_RESET_CHOICE)

        def confirm(self, message: str, **kwargs: Any) -> _Answer:
            return _Answer(False)

    action = flow._ask_existing_setup_action(
        _Questionary(), cfg, status, OnboardOptions(config_path=target)
    )

    assert action == "update"
    assert target.exists()


@pytest.mark.parametrize(
    "options",
    [
        OnboardOptions(skip_migration=True),
        OnboardOptions(skip_channels=True),
        OnboardOptions(skip_search=True),
        OnboardOptions(skip_image_generation=True),
        OnboardOptions(minimal=True),
        OnboardOptions(if_needed=True),
        OnboardOptions(provider_id="openrouter"),
        OnboardOptions(api_key="sk-headless"),
    ],
)
def test_rerun_fork_not_offered_for_scoped_or_headless_runs(
    tmp_path, monkeypatch, options
):
    target = tmp_path / "c.toml"
    _seed_configured_install(target)
    cfg = load_config(target)
    status = flow.get_onboarding_status(cfg)
    options = OnboardOptions(
        **{**options.__dict__, "config_path": target}
    )

    action = flow._ask_existing_setup_action(
        _BaseQuestionary(), cfg, status, options
    )

    assert action is None


def test_rerun_fork_not_offered_for_fresh_or_unfinished_installs(tmp_path):
    target = tmp_path / "c.toml"
    cfg = load_config(target)
    status = flow.get_onboarding_status(cfg)

    action = flow._ask_existing_setup_action(
        _BaseQuestionary(), cfg, status, OnboardOptions(config_path=target)
    )

    assert action is None
