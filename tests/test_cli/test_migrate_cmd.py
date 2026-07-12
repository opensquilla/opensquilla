from __future__ import annotations

import json
import tomllib
from pathlib import Path

from typer.testing import CliRunner

from opensquilla.cli.main import app

runner = CliRunner()


def _set_fake_home(monkeypatch, home: Path) -> None:
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))


def _make_source(root: Path) -> Path:
    source = root / ".openclaw"
    workspace = source / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "SOUL.md").write_text("soul\n", encoding="utf-8")
    (workspace / "MEMORY.md").write_text("memory\n", encoding="utf-8")
    (source / "openclaw.json").write_text(
        json.dumps({"agents": {"defaults": {"model": "deepseek-chat"}}}),
        encoding="utf-8",
    )
    return source


def test_migrate_openclaw_json_dry_run(tmp_path: Path, monkeypatch) -> None:
    source = _make_source(tmp_path)
    home = tmp_path / "opensquilla-home"
    target = tmp_path / "config.toml"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    result = runner.invoke(
        app,
        [
            "migrate",
            "openclaw",
            "--source",
            str(source),
            "--config",
            str(target),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["apply"] is False
    assert not target.exists()
    assert any(item["status"] == "planned" for item in payload["items"])


def test_migrate_openclaw_apply_writes_config_and_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = _make_source(tmp_path)
    home = tmp_path / "opensquilla-home"
    target = tmp_path / "config.toml"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    result = runner.invoke(
        app,
        [
            "migrate",
            "openclaw",
            "--source",
            str(source),
            "--config",
            str(target),
            "--apply",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "OpenClaw migration complete" in result.stdout
    assert (home / "workspace" / "SOUL.md").read_text(encoding="utf-8") == "soul\n"
    config = tomllib.loads(target.read_text(encoding="utf-8"))
    assert config["llm"]["model"] == "deepseek-chat"


def test_migrate_openclaw_missing_source_exits_nonzero(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "migrate",
            "openclaw",
            "--source",
            str(tmp_path / "missing"),
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["items"][0]["status"] == "error"


def test_migrate_openclaw_exclude_skips_workspace_item(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = _make_source(tmp_path)
    home = tmp_path / "opensquilla-home"
    target = tmp_path / "config.toml"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    result = runner.invoke(
        app,
        [
            "migrate",
            "openclaw",
            "--source",
            str(source),
            "--config",
            str(target),
            "--apply",
            "--exclude",
            "soul",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert not (home / "workspace" / "SOUL.md").exists()
    config = tomllib.loads(target.read_text(encoding="utf-8"))
    assert config["llm"]["model"] == "deepseek-chat"


def test_migrate_openclaw_rejects_unknown_include(tmp_path: Path) -> None:
    source = _make_source(tmp_path)

    result = runner.invoke(
        app,
        [
            "migrate",
            "openclaw",
            "--source",
            str(source),
            "--include",
            "not-a-real-option",
        ],
    )

    assert result.exit_code != 0
    assert "Unknown migration option" in result.stdout


def test_migrate_openclaw_rejects_unknown_preset(tmp_path: Path) -> None:
    source = _make_source(tmp_path)

    result = runner.invoke(
        app,
        [
            "migrate",
            "openclaw",
            "--source",
            str(source),
            "--preset",
            "everything",
        ],
    )

    assert result.exit_code != 0
    assert "Unknown migration preset" in result.stdout


def test_migrate_openclaw_rejects_unknown_skill_conflict(tmp_path: Path) -> None:
    source = _make_source(tmp_path)

    result = runner.invoke(
        app,
        [
            "migrate",
            "openclaw",
            "--source",
            str(source),
            "--skill-conflict",
            "merge",
        ],
    )

    assert result.exit_code != 0
    assert "Unknown skill conflict behavior" in result.stdout


# ---------------------------------------------------------------------------
# OpenSquilla self-migration CLI contract
# ---------------------------------------------------------------------------


def test_migrate_opensquilla_plain_error_reports_failure(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["migrate", "opensquilla", "--source", str(tmp_path / "missing")],
    )

    assert result.exit_code == 1
    assert "OpenSquilla self-migration failed" in result.stdout
    assert "error: 1" in result.stdout
    assert "complete" not in result.stdout.lower()


def test_migrate_opensquilla_json_error_is_parseable_and_exits_nonzero(
    tmp_path: Path,
) -> None:
    result = runner.invoke(
        app,
        [
            "migrate",
            "opensquilla",
            "--source",
            str(tmp_path / "missing"),
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["items"][0]["status"] == "error"


def test_migrate_opensquilla_rejects_config_with_target_home_guidance(
    tmp_path: Path,
) -> None:
    result = runner.invoke(
        app,
        [
            "migrate",
            "opensquilla",
            "--source",
            str(tmp_path / "source"),
            "--config",
            str(tmp_path / "config.toml"),
        ],
    )

    assert result.exit_code == 2
    assert "--config is not supported for OpenSquilla self-migration" in result.stdout
    assert "OPENSQUILLA_STATE_DIR" in result.stdout
    assert "target home" in result.stdout


# ---------------------------------------------------------------------------
# Auto-detect entry point: ``opensquilla migrate`` (no subcommand)
# ---------------------------------------------------------------------------


def _seed_openclaw(home: Path) -> Path:
    source = home / ".openclaw"
    workspace = source / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "SOUL.md").write_text("openclaw soul\n", encoding="utf-8")
    (workspace / "MEMORY.md").write_text("openclaw memory\n", encoding="utf-8")
    (source / "openclaw.json").write_text("{}", encoding="utf-8")
    return source


def _seed_opensquilla(home: Path) -> Path:
    source = home / ".opensquilla"
    source.mkdir(parents=True)
    (source / "config.toml").write_text("port = 18790\n", encoding="utf-8")
    return source


def _seed_portable(base: Path) -> Path:
    source = base / "OpenSquilla" / "portable" / "dummy-release"
    source.mkdir(parents=True)
    (source / "config.toml").write_text("port = 18790\n", encoding="utf-8")
    return source


def test_migrate_batch_rejects_config_when_opensquilla_is_selected(
    tmp_path: Path, monkeypatch
) -> None:
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    _seed_opensquilla(fake_home)
    _set_fake_home(monkeypatch, fake_home)
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "desktop-home"))

    result = runner.invoke(
        app,
        [
            "migrate",
            "--source",
            "opensquilla",
            "--config",
            str(tmp_path / "custom-config.toml"),
        ],
    )

    assert result.exit_code == 2, result.stdout
    assert "--config is not supported for OpenSquilla self-migration" in result.stdout


def _seed_hermes(home: Path) -> Path:
    source = home / ".hermes"
    source.mkdir(parents=True)
    (source / "config.yaml").write_text(
        "model:\n  provider: openrouter\n", encoding="utf-8"
    )
    (source / "SOUL.md").write_text("hermes soul\n", encoding="utf-8")
    return source


def test_migrate_auto_detect_no_source_reports_nothing(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "fake_home"
    home.mkdir()
    _set_fake_home(monkeypatch, home)
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "opensquilla"))

    result = runner.invoke(app, ["migrate", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["detected"] == []
    assert "No migration source detected" in payload["message"]
    assert "CLI, desktop, and portable locations" in payload["message"]


def test_migrate_auto_detect_single_source_auto_picks(
    tmp_path: Path, monkeypatch
) -> None:
    # Only hermes present: don't prompt, just run it.
    home = tmp_path / "fake_home"
    home.mkdir()
    _seed_hermes(home)
    _set_fake_home(monkeypatch, home)
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "opensquilla"))

    result = runner.invoke(app, ["migrate", "--apply", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["selected"] == ["hermes"]
    assert "hermes" in payload["reports"]


def test_migrate_auto_detect_single_portable_preserves_source_kind(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "fake_home"
    home.mkdir()
    portable_base = tmp_path / "local-app-data"
    portable = _seed_portable(portable_base)
    _set_fake_home(monkeypatch, home)
    monkeypatch.setenv("LOCALAPPDATA", str(portable_base))
    monkeypatch.delenv("TEMP", raising=False)
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "opensquilla"))

    result = runner.invoke(app, ["migrate", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["selected"] == ["opensquilla"]
    report = payload["reports"]["opensquilla"]
    assert report["source"] == str(portable)
    assert report["source_kind"] == "windows-portable"


def test_migrate_auto_detect_multiple_sources_non_tty_lists_and_exits(
    tmp_path: Path, monkeypatch
) -> None:
    # Both sources present and no --source filter: in non-TTY (CliRunner)
    # the user must opt in explicitly. We print the discovered sources
    # and exit 0 so CI doesn't silently migrate things.
    home = tmp_path / "fake_home"
    home.mkdir()
    _seed_openclaw(home)
    _seed_hermes(home)
    _set_fake_home(monkeypatch, home)
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "opensquilla"))

    result = runner.invoke(app, ["migrate", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    detected_names = [entry["name"] for entry in payload["detected"]]
    assert detected_names == ["openclaw", "hermes"]
    assert "Re-run with" in payload["message"]


def test_migrate_auto_detect_source_filter_runs_only_selected(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "fake_home"
    home.mkdir()
    _seed_openclaw(home)
    _seed_hermes(home)
    _set_fake_home(monkeypatch, home)
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "opensquilla"))

    result = runner.invoke(
        app, ["migrate", "--source", "hermes", "--apply", "--json"]
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["selected"] == ["hermes"]
    assert "openclaw" not in payload["reports"]


def test_migrate_auto_detect_source_filter_runs_both_in_order(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "fake_home"
    home.mkdir()
    _seed_openclaw(home)
    _seed_hermes(home)
    _set_fake_home(monkeypatch, home)
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "opensquilla"))

    result = runner.invoke(
        app,
        ["migrate", "--source", "hermes,openclaw", "--apply", "--json"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    # Order is canonical (openclaw first, then hermes) regardless of how
    # the user wrote the --source flag, so the second migrator sees
    # whatever the first one wrote.
    assert payload["selected"] == ["openclaw", "hermes"]
    assert set(payload["reports"]) == {"openclaw", "hermes"}


def test_migrate_auto_detect_rejects_unknown_source_name(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "fake_home"
    home.mkdir()
    _seed_openclaw(home)
    _set_fake_home(monkeypatch, home)
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "opensquilla"))

    result = runner.invoke(app, ["migrate", "--source", "bogus", "--json"])

    assert result.exit_code == 2, result.stdout
    assert "Unknown migration source" in result.stdout


def test_migrate_auto_detect_rejects_requested_but_undetected_source(
    tmp_path: Path, monkeypatch
) -> None:
    # ``--source hermes`` when hermes is not on disk should fail loudly
    # rather than silently no-op.
    home = tmp_path / "fake_home"
    home.mkdir()
    _seed_openclaw(home)
    _set_fake_home(monkeypatch, home)
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "opensquilla"))

    result = runner.invoke(app, ["migrate", "--source", "hermes", "--json"])

    assert result.exit_code == 2, result.stdout
    assert "not detected" in result.stdout


def test_migrate_auto_detect_tty_prompt_path_is_invoked(
    tmp_path: Path, monkeypatch
) -> None:
    # When both sources are present and stdin is a TTY (real interactive
    # use), we should reach the questionary prompt instead of the
    # non-TTY exit branch. Patch the prompt helper so the test doesn't
    # need a real terminal. ``--json`` short-circuits to the non-TTY
    # branch on purpose (scripting context), so this test uses plain
    # text output and checks that the migration actually ran via the
    # files it wrote.
    home = tmp_path / "fake_home"
    home.mkdir()
    _seed_openclaw(home)
    _seed_hermes(home)
    state = tmp_path / "opensquilla"
    _set_fake_home(monkeypatch, home)
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(state))

    from opensquilla.cli import migrate_cmd

    monkeypatch.setattr("opensquilla.cli.migrate_cmd._stdin_is_tty", lambda: True)
    captured: list[list[object]] = []

    def fake_prompt(detected):
        captured.append(list(detected))
        # User picks only hermes.
        return ["hermes"]

    monkeypatch.setattr(migrate_cmd, "_prompt_source_selection", fake_prompt)

    result = runner.invoke(app, ["migrate", "--apply"])

    assert result.exit_code == 0, result.stdout
    assert "hermes migration complete" in result.stdout
    # openclaw was offered but the fake prompt only picked hermes, so
    # the openclaw migrator must NOT have run.
    assert "openclaw migration complete" not in result.stdout
    assert len(captured) == 1
    assert {source.name for source in captured[0]} == {"openclaw", "hermes"}


def test_migrate_auto_detect_validates_all_selected_before_running_any(
    tmp_path: Path, monkeypatch
) -> None:
    # Pre-validate so an invalid flag for the second migrator never
    # half-applies the first one. ``persona_conflict`` is the openclaw-only
    # flag, so a bogus value for it must error out even though hermes
    # would happily ignore it.
    home = tmp_path / "fake_home"
    home.mkdir()
    _seed_openclaw(home)
    _seed_hermes(home)
    state = tmp_path / "opensquilla"
    _set_fake_home(monkeypatch, home)
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(state))

    result = runner.invoke(
        app,
        [
            "migrate",
            "--source",
            "openclaw,hermes",
            "--persona-conflict",
            "absolutely-bogus",
            "--apply",
        ],
    )

    assert result.exit_code == 2, result.stdout
    assert "Unknown persona conflict behavior" in result.stdout
    # Neither migrator should have left state behind: the workspace dir
    # is created by the first migrator's apply, so its absence is proof
    # we bailed before running anything.
    assert not (state / "workspace").exists()


def test_migrate_auto_detect_tty_prompt_cancellation_exits_cleanly(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "fake_home"
    home.mkdir()
    _seed_openclaw(home)
    _seed_hermes(home)
    _set_fake_home(monkeypatch, home)
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "opensquilla"))

    from opensquilla.cli import migrate_cmd

    monkeypatch.setattr("opensquilla.cli.migrate_cmd._stdin_is_tty", lambda: True)
    monkeypatch.setattr(migrate_cmd, "_prompt_source_selection", lambda _detected: [])

    result = runner.invoke(app, ["migrate"])

    assert result.exit_code == 0, result.stdout
    assert "No source selected" in result.stdout
