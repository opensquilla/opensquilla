"""Tests covering the hermes migrator fixes:

- H1: --overwrite creates an item-level backup before destroying existing target
- H2: short source body whose stripped form appears as substring is no longer
  silently treated as duplicate
- H3: deferred CLI option ids surface as `status: deferred` records
- M1: workspace prose gets rebranded from Hermes -> OpenSquilla
- M2: skill_conflict=overwrite backs up existing skill dir before rmtree
- M3: oversized merged MEMORY.md is split and the tail archived
- M4: skill compatibility is reported (missing frontmatter / size limit)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.migration.hermes import (
    DEFERRED_OPTIONS,
    MAX_MEMORY_CHARS,
    HermesMigrationOptions,
    HermesMigrator,
    _hermes_rebrand_text,
    _load_env_file,
)


def _make_hermes_home_with_user_data(root: Path) -> Path:
    home = root / ".hermes"
    home.mkdir(parents=True)
    (home / "config.yaml").write_text("model:\n  provider: openrouter\n", encoding="utf-8")
    (home / "SOUL.md").write_text("Hermes soul\n", encoding="utf-8")
    (home / "memories").mkdir()
    (home / "memories" / "MEMORY.md").write_text("memory line\n", encoding="utf-8")
    (home / "memories" / "USER.md").write_text("user profile\n", encoding="utf-8")
    return home


def test_overwrite_creates_item_level_backup_before_replacing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_hermes_home_with_user_data(tmp_path)
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    workspace_soul = home / "workspace" / "SOUL.md"
    workspace_soul.parent.mkdir(parents=True)
    workspace_soul.write_text("pre-existing opensquilla soul to preserve\n", encoding="utf-8")

    HermesMigrator(
        HermesMigrationOptions(source=source, apply=True, overwrite=True)
    ).migrate()

    backups = list(workspace_soul.parent.glob("SOUL.md.backup.*"))
    assert len(backups) == 1, f"expected exactly one backup, found: {backups}"
    assert backups[0].read_text(encoding="utf-8") == "pre-existing opensquilla soul to preserve\n"
    # Newer content from the Hermes source replaces the file.
    assert workspace_soul.read_text(encoding="utf-8") == "Hermes soul\n"


def test_short_source_substring_match_is_not_falsely_deduped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_hermes_home_with_user_data(tmp_path)
    # source MEMORY.md contains "tea" — a short string that happens to appear
    # inside an unrelated existing destination block. Old naive `in` check
    # would silently drop the source; semantic dedupe should merge it.
    (source / "memories" / "MEMORY.md").write_text("tea\n", encoding="utf-8")
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    dest = home / "workspace" / "MEMORY.md"
    dest.parent.mkdir(parents=True)
    dest.write_text(
        "I had a long conversation about tea ceremonies in Kyoto.\n",
        encoding="utf-8",
    )

    HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()

    merged = dest.read_text(encoding="utf-8")
    # Pre-existing block kept.
    assert "Kyoto" in merged
    # Source body merged in as its own block.
    assert merged.count("tea\n") >= 1
    assert merged.endswith("tea\n")


def test_deferred_option_ids_appear_in_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_hermes_home_with_user_data(tmp_path)
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = HermesMigrator(
        HermesMigrationOptions(
            source=source,
            apply=True,
            include=("tools-config", "browser-config", "workspace-files"),
        )
    ).migrate()

    deferred = {
        item["kind"]
        for item in report["items"]
        if item["status"] == "deferred"
    }
    # All eight stub options are now selected via the default `full` preset
    # plus the explicit --include list, so each appears as a deferred record.
    assert DEFERRED_OPTIONS <= deferred
    sample = next(item for item in report["items"] if item["kind"] == "tools-config")
    assert sample["reason"] == "handler not implemented yet"


def test_workspace_prose_is_rebranded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_hermes_home_with_user_data(tmp_path)
    (source / "SOUL.md").write_text(
        # Branding tokens that should be rewritten:
        "You are a Hermes Agent assistant. The Hermes memory lives in .hermes/.\n"
        # Source-reference tokens that must be preserved for traceability:
        "Originally bootstrapped via the NousResearch/hermes-agent project, "
        "honoring HERMES_HOME.\n",
        encoding="utf-8",
    )
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()

    migrated = (home / "workspace" / "SOUL.md").read_text(encoding="utf-8")
    assert "OpenSquilla assistant" in migrated
    assert "OpenSquilla memory" in migrated
    assert ".opensquilla/" in migrated
    # Source-reference tokens are protected.
    assert "NousResearch" in migrated
    assert "hermes-agent" in migrated
    assert "HERMES_HOME" in migrated
    # Original unrebranded file archived for review.
    original = (
        Path(report["output_dir"])
        / "archive"
        / "files"
        / "workspace-original"
        / "SOUL.md"
    )
    assert "Hermes Agent assistant" in original.read_text(encoding="utf-8")
    soul_item = next(item for item in report["items"] if item["kind"] == "soul")
    assert soul_item["details"]["semantic_conversions"] == ["hermes-branding"]


def test_rebrand_helper_does_not_touch_unrelated_uses_of_hermes() -> None:
    # Bare "Hermes" without a workspace-context word is left alone — keeps
    # rebrand conservative for unrelated prose, mythology, project names, etc.
    text = "Hermes is the Greek messenger god."
    out, changed = _hermes_rebrand_text(text)
    assert out == text
    assert changed is False


def test_rebrand_helper_skips_text_that_already_mentions_opensquilla() -> None:
    # Mixed-subject prose. The user is documenting that BOTH Hermes and
    # OpenSquilla are installed; mechanical replacement would collapse the
    # two subjects into one and produce nonsense like
    # "OpenSquilla skills loadable by OpenSquilla". The helper must
    # leave the text alone in this case.
    text = (
        "Hermes Agent v0.13.0 installed at ~/.local/bin/hermes.\n"
        "OpenSquilla also installed at ~/.local/bin/opensquilla. "
        "Has `migrate hermes` subcommand.\n"
        "Only those two flat Hermes skills are loadable by OpenSquilla.\n"
    )
    out, changed = _hermes_rebrand_text(text)
    assert out == text
    assert changed is False


def test_rebrand_skip_reason_detects_opensquilla_case_insensitively() -> None:
    from opensquilla.migration.hermes import (
        REBRAND_SKIP_REASON_MIXED,
        _rebrand_skip_reason,
    )

    # CamelCase brand mention.
    assert _rebrand_skip_reason("OpenSquilla is great") == REBRAND_SKIP_REASON_MIXED
    # Lowercase path / module mention.
    assert _rebrand_skip_reason("~/.opensquilla/config") == REBRAND_SKIP_REASON_MIXED
    # ALL CAPS env var name.
    assert _rebrand_skip_reason("OPENSQUILLA_HOME") == REBRAND_SKIP_REASON_MIXED
    # No mention -> rebrand should proceed normally.
    assert _rebrand_skip_reason("Hermes Agent home and skills") is None


def test_workspace_prose_with_opensquilla_mention_is_kept_verbatim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reproduces the user-reported bug: the source MEMORY.md describes
    # both Hermes and OpenSquilla as distinct entities. Mechanical
    # replacement used to corrupt every sentence that mentioned both
    # (path mismatch, tautologies, self-referential commands). The
    # migrator must now detect this and write the text VERBATIM, with
    # `details.rebrand_skipped: "mentions-opensquilla"` so the user
    # knows to reword by hand.
    source = _make_hermes_home_with_user_data(tmp_path)
    mixed = (
        "Hermes Agent v0.13.0 installed at ~/.local/bin/hermes.\n"
        "OpenSquilla also installed at ~/.local/bin/opensquilla. "
        "Has `migrate hermes` subcommand.\n"
        "Only those two flat Hermes skills are loadable by OpenSquilla.\n"
        "Plan: migrate Hermes skills to OpenSquilla.\n"
    )
    (source / "memories" / "MEMORY.md").write_text(mixed, encoding="utf-8")
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()

    migrated = (home / "workspace" / "MEMORY.md").read_text(encoding="utf-8")
    # Verbatim: every original wording survives.
    for line in (
        "Hermes Agent v0.13.0 installed at ~/.local/bin/hermes",
        "OpenSquilla also installed at ~/.local/bin/opensquilla",
        "Only those two flat Hermes skills are loadable by OpenSquilla",
        "migrate Hermes skills to OpenSquilla",
    ):
        assert line in migrated, f"missing verbatim line: {line!r}"
    # The four broken-translation outputs we observed in the bug report
    # must NOT appear anywhere in the migrated file.
    assert "OpenSquilla v0.13.0 installed at ~/.local/bin/hermes" not in migrated
    assert "Only those two flat OpenSquilla skills" not in migrated
    assert "migrate OpenSquilla skills to OpenSquilla" not in migrated

    memory_item = next(i for i in report["items"] if i["kind"] == "memory")
    assert memory_item["details"]["rebrand_skipped"] == "mentions-opensquilla"
    # Did NOT also claim a successful rebrand.
    assert "semantic_conversions" not in memory_item["details"]


def test_rebrand_does_not_mangle_path_substrings_of_dot_hermes() -> None:
    # Prefix-substring regression: a plain string replace turned
    # ``.hermesrc`` into ``.opensquillarc`` and ``.hermes-cache`` into
    # ``.opensquilla-cache``. Both are nonsense. Only ``.hermes`` as a
    # complete path token (followed by ``/``, whitespace, quote, etc.)
    # should be rebranded.
    cases = [
        ("Path ~/.hermesrc keeps working", "Path ~/.hermesrc keeps working"),
        ("Cache .hermes-cache here", "Cache .hermes-cache here"),
        ("Backup ~/.hermes_backup", "Backup ~/.hermes_backup"),
        # Legit path forms still rebrand:
        ("Use ~/.hermes for state", "Use ~/.opensquilla for state"),
        ('Quoted "~/.hermes" works', 'Quoted "~/.opensquilla" works'),
        ("Slashed ~/.hermes/sub", "Slashed ~/.opensquilla/sub"),
    ]
    for source_text, expected in cases:
        out, _ = _hermes_rebrand_text(source_text)
        assert out == expected, f"{source_text!r} -> {out!r}, expected {expected!r}"


def test_hermes_migrate_survives_non_utf8_source_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: a source MEMORY.md containing stray non-UTF-8 bytes
    # (BOM tail, CP1252 fragment, accidental binary paste) used to crash
    # the entire migration with UnicodeDecodeError out of
    # ``read_text(encoding="utf-8-sig")``. Now the read uses
    # ``errors="replace"`` so migration completes; the bad bytes land as
    # U+FFFD replacement chars in the destination.
    source = _make_hermes_home_with_user_data(tmp_path)
    (source / "memories" / "MEMORY.md").write_bytes(
        b"\xff garbage \xff\nthen valid markdown\n"
    )
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    # The previous version raised here. Should now succeed.
    report = HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()

    memory_item = next(i for i in report["items"] if i["kind"] == "memory")
    assert memory_item["status"] == "migrated"
    written = (home / "workspace" / "MEMORY.md").read_text(encoding="utf-8")
    assert "then valid markdown" in written
    # Replacement chars survived where the bad bytes were.
    assert "�" in written


def test_hermes_mcp_enabled_false_is_preserved_when_user_has_servers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: ``cfg.mcp.enabled = True`` was set unconditionally
    # when importing MCP servers, silently re-enabling MCP for users
    # who had deliberately turned it off. Now the migrator respects an
    # explicit ``mcp.enabled = false`` if the user already had
    # configured servers (i.e. it isn't just the framework default).
    source = _make_hermes_home_with_user_data(tmp_path)
    (source / "config.yaml").write_text(
        "model:\n  provider: openrouter\n"
        "mcp:\n  servers:\n    new:\n      command: /usr/bin/x\n",
        encoding="utf-8",
    )
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.toml").write_text(
        "[mcp]\nenabled = false\n\n"
        "[[mcp.servers]]\n"
        "name = \"existing\"\ncommand = \"/usr/bin/y\"\ntransport = \"stdio\"\n",
        encoding="utf-8",
    )

    report = HermesMigrator(
        HermesMigrationOptions(
            source=source, config_path=home / "config.toml", apply=True
        )
    ).migrate()

    import tomllib
    data = tomllib.loads((home / "config.toml").read_text())
    assert data["mcp"]["enabled"] is False, (
        "explicit mcp.enabled=false must NOT be silently flipped on import"
    )
    mc = next(i for i in report["items"] if i["kind"] == "mcp-servers")
    assert mc["details"]["mcp_enabled_left_disabled"] is True
    assert "manual_steps" in mc["details"]


def test_hermes_mcp_enabled_flips_when_default_and_no_existing_servers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Symmetric regression guard: when MCP is at its framework default
    # (enabled=false because there's nothing to enable) and the user
    # imports MCP servers for the first time, we DO turn MCP on so the
    # imported servers actually work.
    source = _make_hermes_home_with_user_data(tmp_path)
    (source / "config.yaml").write_text(
        "model:\n  provider: openrouter\n"
        "mcp:\n  servers:\n    fresh:\n      command: /usr/bin/x\n",
        encoding="utf-8",
    )
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    # No pre-existing config.toml at all — MCP defaulted off.

    HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()

    import tomllib
    data = tomllib.loads((home / "config.toml").read_text())
    assert data["mcp"]["enabled"] is True


def test_pure_hermes_prose_still_rebrands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: source that does NOT mention OpenSquilla should keep
    # the original rebrand behavior.
    source = _make_hermes_home_with_user_data(tmp_path)
    (source / "memories" / "MEMORY.md").write_text(
        "Single-subject note about Hermes Agent home and Hermes skills.\n",
        encoding="utf-8",
    )
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()

    migrated = (home / "workspace" / "MEMORY.md").read_text(encoding="utf-8")
    assert "OpenSquilla home" in migrated
    assert "OpenSquilla skills" in migrated
    memory_item = next(i for i in report["items"] if i["kind"] == "memory")
    assert memory_item["details"].get("semantic_conversions") == ["hermes-branding"]
    assert "rebrand_skipped" not in memory_item["details"]


def test_skill_overwrite_creates_backup_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_hermes_home_with_user_data(tmp_path)
    skill = source / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo\ndescription: New\n---\nNew body\n", encoding="utf-8"
    )
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    # Pre-existing skill at the target with local edits the user does not want lost.
    existing = home / "skills" / "hermes-imports" / "demo"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Local\n---\nLocal edits\n", encoding="utf-8"
    )

    HermesMigrator(
        HermesMigrationOptions(
            source=source, apply=True, skill_conflict="overwrite"
        )
    ).migrate()

    backups = list(existing.parent.glob("demo.backup.*"))
    assert len(backups) == 1
    assert (backups[0] / "SKILL.md").read_text(encoding="utf-8") == (
        "---\nname: demo\ndescription: Local\n---\nLocal edits\n"
    )
    # Source skill won the overwrite.
    assert "New body" in (existing / "SKILL.md").read_text(encoding="utf-8")


def test_oversized_memory_is_split_with_overflow_archived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_hermes_home_with_user_data(tmp_path)
    huge = "block\n\n" * ((MAX_MEMORY_CHARS // 7) + 1000)
    (source / "memories" / "MEMORY.md").write_text(huge, encoding="utf-8")
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()

    merged = (home / "workspace" / "MEMORY.md").read_text(encoding="utf-8")
    assert len(merged) <= MAX_MEMORY_CHARS + 200  # only the overflow marker may push it slightly
    assert "Migration overflow" in merged

    overflow = (
        Path(report["output_dir"]) / "archive" / "memory-overflow" / "MEMORY.overflow.md"
    )
    assert overflow.is_file()
    assert overflow.read_text(encoding="utf-8").strip().startswith("block")

    overflow_item = next(
        item for item in report["items"] if item["kind"] == "memory-overflow"
    )
    assert overflow_item["status"] == "archived"


def test_repeat_migration_reports_dedupe_as_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Run the same migration twice. The second pass finds the source content
    # already present in the destination — the report should say `skipped`
    # with a clear reason, not `migrated`, because nothing was written.
    source = _make_hermes_home_with_user_data(tmp_path)
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()
    second = HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()

    soul_item = next(item for item in second["items"] if item["kind"] == "soul")
    assert soul_item["status"] == "skipped"
    assert soul_item["reason"] == "duplicate of existing destination block"
    assert soul_item["details"]["deduplicated"] is True


def test_multi_block_memory_is_correctly_deduped_on_re_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: the previous dedupe normalized the whole source into a
    # single string and compared it against each destination block. For a
    # multi-block MEMORY.md the comparison NEVER matched, so re-running the
    # migration appended duplicate blocks unboundedly.
    source = _make_hermes_home_with_user_data(tmp_path)
    multi_block = (
        "First memory entry.\n\n"
        "Second memory entry.\n\n"
        "Third memory entry.\n"
    )
    (source / "memories" / "MEMORY.md").write_text(multi_block, encoding="utf-8")
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()
    after_first = (home / "workspace" / "MEMORY.md").read_text(encoding="utf-8")
    assert after_first.count("First memory entry") == 1
    assert after_first.count("Second memory entry") == 1
    assert after_first.count("Third memory entry") == 1

    second = HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()
    after_second = (home / "workspace" / "MEMORY.md").read_text(encoding="utf-8")
    # Each entry still appears exactly once — no duplication on re-migration.
    assert after_second.count("First memory entry") == 1
    assert after_second.count("Second memory entry") == 1
    assert after_second.count("Third memory entry") == 1

    memory_item = next(i for i in second["items"] if i["kind"] == "memory")
    assert memory_item["status"] == "skipped"
    assert memory_item["details"]["deduplicated"] is True


def test_subset_dedupe_skips_when_all_source_blocks_already_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Source is a strict subset of the destination — every source block
    # already has an equivalent in the destination, so the merge is skipped.
    source = _make_hermes_home_with_user_data(tmp_path)
    (source / "memories" / "MEMORY.md").write_text(
        "Block one.\n\nBlock two.\n", encoding="utf-8"
    )
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    dest = home / "workspace" / "MEMORY.md"
    dest.parent.mkdir(parents=True)
    dest.write_text(
        "Block one.\n\nBlock two.\n\nBlock three from elsewhere.\n",
        encoding="utf-8",
    )

    report = HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()

    final = dest.read_text(encoding="utf-8")
    assert final.count("Block one.") == 1
    assert final.count("Block two.") == 1
    assert final.count("Block three from elsewhere.") == 1
    memory_item = next(i for i in report["items"] if i["kind"] == "memory")
    assert memory_item["status"] == "skipped"


def test_split_memory_overflow_helper_is_noop_when_under_limit() -> None:
    # Regression: previous helper unconditionally appended an overflow
    # marker even when the input fit, growing the trimmed output beyond
    # MAX_MEMORY_CHARS and pointing to an empty archive.
    text = "alpha\n\n" * 1000  # well under MAX_MEMORY_CHARS
    trimmed, overflow = HermesMigrator._split_memory_overflow(text)
    assert trimmed == text
    assert overflow == ""
    assert "Migration overflow" not in trimmed


def test_invalid_profile_name_is_rejected_before_path_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: `--profile "../escape"` used to be joined onto
    # ~/.hermes/profiles/ verbatim and could escape the hermes home via
    # ``..`` traversal. The migrator now rejects profile names that do not
    # match hermes' own profile-id regex.
    real_home = tmp_path / ".hermes"
    real_home.mkdir()
    (real_home / "config.yaml").write_text("model:\n  provider: openrouter\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(real_home))
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    for bad in ("../escape", "..", "with/slash", "UpperCase", " spaced ", "../../etc"):
        report = HermesMigrator(HermesMigrationOptions(profile=bad)).migrate()
        errors = [i for i in report["items"] if i["status"] == "error"]
        assert errors, f"profile {bad!r} was not rejected"
        assert errors[0]["kind"] == "profile", f"profile {bad!r} produced wrong error: {errors[0]}"
        assert "invalid profile name" in errors[0]["reason"]


def test_unknown_provider_is_not_written_to_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: an unknown provider (`bedrock`, `ollama`, `auto`, …) used
    # to be written verbatim into ``cfg.llm.provider``. That broke two
    # invariants downstream:
    #   1. GatewayConfig's enum-style validator rejects unknown providers.
    #   2. ``squilla_router.tier_profile`` must agree with
    #      ``llm.provider`` after case normalisation; a stale ``openrouter``
    #      tier-profile vs a fresh ``auto`` provider crashes persist_config.
    # The migrator now leaves ``llm.provider`` untouched and reports the
    # gap so the user can configure it manually.
    source = _make_hermes_home_with_user_data(tmp_path)
    (source / "config.yaml").write_text(
        "model:\n  provider: bedrock\n  model: claude-3-opus\n", encoding="utf-8"
    )
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()

    mc = next(i for i in report["items"] if i["kind"] == "model-config")
    assert mc["status"] == "migrated"
    assert mc["details"]["unrecognized_provider"] == "bedrock"
    assert "llm_provider_left_unchanged" in mc["details"]
    assert mc["details"]["manual_steps"]

    import tomllib
    data = tomllib.loads((home / "config.toml").read_text())
    # Provider was NOT overwritten with the unknown value. Sparse persistence
    # may omit the key entirely (it was left at the default), which satisfies
    # the same invariant. The model id still came through because that's a
    # free-form string.
    assert data["llm"].get("provider") != "bedrock"
    assert data["llm"]["model"] == "claude-3-opus"


def test_hermes_auto_provider_does_not_crash_when_tier_profile_already_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The reported user-facing crash:
    #   ValidationError: squilla_router.tier_profile requires llm.provider
    #   to match ('openrouter' != 'auto')
    # Reproduce it by pre-seeding ~/.opensquilla/config.toml with a valid
    # (openrouter, openrouter) pair, then run `migrate hermes` against a
    # config that says model.provider: "auto". The migrator must NOT
    # rewrite llm.provider to "auto" or persist_config will refuse to
    # write the file at all.
    source = _make_hermes_home_with_user_data(tmp_path)
    (source / "config.yaml").write_text(
        "model:\n  provider: auto\n  model: anthropic/claude-3-opus\n",
        encoding="utf-8",
    )
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    # Seed the existing opensquilla config with matching (provider,
    # tier_profile) — same situation the user reported on their machine.
    (home).mkdir(parents=True, exist_ok=True)
    (home / "config.toml").write_text(
        "[llm]\nprovider = \"openrouter\"\nmodel = \"anthropic/claude-opus-4-7\"\n"
        "api_key_env = \"OPENROUTER_API_KEY\"\n\n"
        "[squilla_router]\ntier_profile = \"openrouter\"\n",
        encoding="utf-8",
    )

    # Must not raise pydantic.ValidationError.
    report = HermesMigrator(
        HermesMigrationOptions(
            source=source, config_path=home / "config.toml", apply=True
        )
    ).migrate()

    mc = next(i for i in report["items"] if i["kind"] == "model-config")
    assert mc["status"] == "migrated"
    assert mc["details"]["unrecognized_provider"] == "auto"
    assert mc["details"]["llm_provider_left_unchanged"] == "openrouter"

    import tomllib
    data = tomllib.loads((home / "config.toml").read_text())
    # Pre-existing provider preserved; tier_profile still agrees with it.
    assert data["llm"]["provider"] == "openrouter"
    assert data["squilla_router"]["tier_profile"] == "openrouter"
    # The migrator did pick up the model id, which is a free-form string.
    assert data["llm"]["model"] == "anthropic/claude-3-opus"


def test_known_provider_differing_from_tier_profile_does_not_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Same crash class as the "auto" case, but with a provider that IS in
    # PROVIDER_ENV_KEYS (so the old fix's "unknown branch" doesn't catch it).
    # Hermes config: provider=anthropic. Existing opensquilla home: tier_profile
    # already pinned to openrouter. Writing llm.provider=anthropic would
    # violate GatewayConfig._validate_squilla_router_tier_profile_provider and
    # abort the whole migration with pydantic ValidationError.
    source = _make_hermes_home_with_user_data(tmp_path)
    (source / "config.yaml").write_text(
        "model:\n  provider: anthropic\n  model: claude-3-5-sonnet\n",
        encoding="utf-8",
    )
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    (home).mkdir(parents=True, exist_ok=True)
    (home / "config.toml").write_text(
        "[llm]\nprovider = \"openrouter\"\nmodel = \"anthropic/claude-opus-4-7\"\n"
        "api_key_env = \"OPENROUTER_API_KEY\"\n\n"
        "[squilla_router]\ntier_profile = \"openrouter\"\n",
        encoding="utf-8",
    )

    # Must not raise pydantic.ValidationError.
    report = HermesMigrator(
        HermesMigrationOptions(
            source=source, config_path=home / "config.toml", apply=True
        )
    ).migrate()

    mc = next(i for i in report["items"] if i["kind"] == "model-config")
    assert mc["status"] == "migrated"
    # Report surfaces the conflict explicitly so the user can act on it.
    assert mc["details"]["tier_profile_conflict"] == "openrouter"
    assert mc["details"]["llm_provider_left_unchanged"] == "openrouter"
    assert "manual_steps" in mc["details"]
    # Crucially we did NOT mislabel this as "unrecognized" — anthropic IS a
    # known provider, it just clashes with the pinned tier_profile.
    assert "unrecognized_provider" not in mc["details"]

    import tomllib
    data = tomllib.loads((home / "config.toml").read_text())
    # Pre-existing provider preserved; tier_profile still agrees with it.
    assert data["llm"]["provider"] == "openrouter"
    assert data["squilla_router"]["tier_profile"] == "openrouter"
    # The model id was still picked up.
    assert data["llm"]["model"] == "claude-3-5-sonnet"


def test_model_id_extracted_from_nested_dict_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: a hermes config whose `model.model` is a dict
    # (`{primary: ..., fallback: ...}`) used to write the Python repr of
    # the dict as the model id, producing garbage in opensquilla config.
    source = _make_hermes_home_with_user_data(tmp_path)
    (source / "config.yaml").write_text(
        "model:\n  provider: openrouter\n  model:\n    primary: anthropic/claude-3-opus\n"
        "    fallback: openai/gpt-4o\n",
        encoding="utf-8",
    )
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()

    import tomllib
    data = tomllib.loads((home / "config.toml").read_text())
    assert data["llm"]["model"] == "anthropic/claude-3-opus"
    assert "{" not in data["llm"]["model"]  # not a stringified dict


def test_env_file_with_export_prefix_is_parsed_correctly(tmp_path: Path) -> None:
    # Regression: `export FOO=bar` is common in hand-written .env files. The
    # previous parser kept "export " in the key, so secrets like
    # `export OPENROUTER_API_KEY=...` failed to match SECRET_ENV_KEYS and
    # were silently dropped on `--migrate-secrets`.
    env_path = tmp_path / ".env"
    env_path.write_text(
        "export OPENROUTER_API_KEY=sk-or-123\n"
        "OPENAI_API_KEY=sk-oa-456\n"
        "export   ANTHROPIC_API_KEY=sk-an-789\n",
        encoding="utf-8",
    )
    parsed = _load_env_file(env_path)
    assert parsed == {
        "OPENROUTER_API_KEY": "sk-or-123",
        "OPENAI_API_KEY": "sk-oa-456",
        "ANTHROPIC_API_KEY": "sk-an-789",
    }


def test_export_prefixed_secret_is_actually_migrated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_hermes_home_with_user_data(tmp_path)
    (source / ".env").write_text(
        "export OPENROUTER_API_KEY=sk-or-from-export-form\n", encoding="utf-8"
    )
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    HermesMigrator(
        HermesMigrationOptions(source=source, apply=True, migrate_secrets=True)
    ).migrate()

    written = (home / ".env").read_text(encoding="utf-8")
    assert "OPENROUTER_API_KEY=sk-or-from-export-form" in written


def test_mcp_servers_as_list_of_dicts_are_migrated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Hermes config.yaml accepts both dict-of-dicts and list-of-dicts forms
    # for mcp.servers. The migrator used to silently drop the list form.
    source = _make_hermes_home_with_user_data(tmp_path)
    (source / "config.yaml").write_text(
        """model:
  provider: openrouter
mcp:
  servers:
    - name: srv-one
      command: node
      args: ["server-one.js"]
    - name: srv-two
      url: https://example.test/mcp
""",
        encoding="utf-8",
    )
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()

    mcp_item = next(i for i in report["items"] if i["kind"] == "mcp-servers")
    assert mcp_item["status"] == "migrated"
    assert mcp_item["details"]["server_count"] == 2

    import tomllib
    cfg = tomllib.loads((home / "config.toml").read_text())
    server_names = sorted(s["name"] for s in cfg["mcp"]["servers"])
    assert server_names == ["srv-one", "srv-two"]
    transports = {s["name"]: s["transport"] for s in cfg["mcp"]["servers"]}
    assert transports["srv-one"] == "stdio"
    assert transports["srv-two"] == "sse"


def test_mcp_servers_malformed_entries_are_reported_as_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_hermes_home_with_user_data(tmp_path)
    (source / "config.yaml").write_text(
        """mcp:
  servers:
    valid:
      command: node
    broken: "not a dict"
""",
        encoding="utf-8",
    )
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()

    mcp_item = next(i for i in report["items"] if i["kind"] == "mcp-servers")
    assert mcp_item["status"] == "migrated"
    assert mcp_item["details"]["server_count"] == 1
    assert mcp_item["details"]["dropped_entries"] == ["broken"]


def test_mcp_migration_preserves_existing_opensquilla_servers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: the migrator used to assign cfg.mcp.servers = imported,
    # silently destroying any MCP servers the user already had configured.
    # New behavior is upsert-by-name: same-name entries are replaced (with
    # the hermes definition winning), unrelated entries are preserved.
    source = _make_hermes_home_with_user_data(tmp_path)
    (source / "config.yaml").write_text(
        """model:
  provider: openrouter
mcp:
  servers:
    fresh-from-hermes:
      command: /usr/bin/new-tool
    shared-name:
      command: /override/from/hermes
""",
        encoding="utf-8",
    )
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    home.mkdir(parents=True)
    (home / "config.toml").write_text(
        "[mcp]\nenabled = true\n\n"
        "[[mcp.servers]]\n"
        "name = \"shared-name\"\ncommand = \"/usr/local/bin/old\"\ntransport = \"stdio\"\n\n"
        "[[mcp.servers]]\n"
        "name = \"opensquilla-only\"\ncommand = \"/usr/local/bin/keep-me\"\n"
        "transport = \"stdio\"\n",
        encoding="utf-8",
    )

    report = HermesMigrator(
        HermesMigrationOptions(
            source=source, config_path=home / "config.toml", apply=True
        )
    ).migrate()

    mcp_item = next(i for i in report["items"] if i["kind"] == "mcp-servers")
    assert mcp_item["status"] == "migrated"
    assert mcp_item["details"]["added"] == ["fresh-from-hermes"]
    assert mcp_item["details"]["replaced"] == ["shared-name"]
    assert mcp_item["details"]["preserved_existing"] == ["opensquilla-only"]

    import tomllib
    data = tomllib.loads((home / "config.toml").read_text())
    by_name = {s["name"]: s for s in data["mcp"]["servers"]}
    # Pre-existing unrelated server still here.
    assert by_name["opensquilla-only"]["command"] == "/usr/local/bin/keep-me"
    # Same-name conflict: hermes version wins (the user invoked migrate;
    # they asked for the import).
    assert by_name["shared-name"]["command"] == "/override/from/hermes"
    # New hermes server added.
    assert by_name["fresh-from-hermes"]["command"] == "/usr/bin/new-tool"


def test_repeated_migrate_secrets_does_not_duplicate_env_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: re-running --migrate-secrets used to append duplicate env
    # entries each run, growing .env unboundedly.
    source = _make_hermes_home_with_user_data(tmp_path)
    (source / ".env").write_text(
        "OPENROUTER_API_KEY=sk-stable\n", encoding="utf-8"
    )
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    for _ in range(3):
        HermesMigrator(
            HermesMigrationOptions(source=source, apply=True, migrate_secrets=True)
        ).migrate()

    env_text = (home / ".env").read_text(encoding="utf-8")
    assert env_text.count("OPENROUTER_API_KEY=") == 1


def test_env_write_updates_existing_key_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If the user already has an unrelated key in ~/.opensquilla/.env, the
    # migrator should keep it and only update / add migrated keys.
    source = _make_hermes_home_with_user_data(tmp_path)
    (source / ".env").write_text(
        "OPENROUTER_API_KEY=sk-new\n", encoding="utf-8"
    )
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    (home).mkdir(parents=True)
    (home / ".env").write_text(
        "# user existing config\nUNRELATED_KEY=keep-me\nOPENROUTER_API_KEY=sk-old\n",
        encoding="utf-8",
    )

    HermesMigrator(
        HermesMigrationOptions(source=source, apply=True, migrate_secrets=True)
    ).migrate()

    text = (home / ".env").read_text(encoding="utf-8")
    assert "# user existing config" in text
    assert "UNRELATED_KEY=keep-me" in text
    assert "OPENROUTER_API_KEY=sk-new" in text
    assert "OPENROUTER_API_KEY=sk-old" not in text
    assert text.count("OPENROUTER_API_KEY=") == 1


def test_malformed_config_yaml_does_not_crash_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: a hand-edited config.yaml with a YAML syntax error used to
    # bubble a yaml.YAMLError out of the whole migration. Now the migrator
    # records an `error` item for config.yaml and continues — user-data
    # items still migrate.
    source = _make_hermes_home_with_user_data(tmp_path)
    (source / "config.yaml").write_text(
        "model:\n  provider: openrouter\nfoo: [unclosed\n", encoding="utf-8"
    )
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()

    config_errors = [
        i for i in report["items"]
        if i["kind"] == "config.yaml" and i["status"] == "error"
    ]
    assert len(config_errors) == 1
    assert "could not parse" in config_errors[0]["reason"]
    # User data still migrated despite the broken config.yaml.
    assert (home / "workspace" / "SOUL.md").is_file()


def test_empty_skills_dir_emits_skipped_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An empty `skills/` directory used to produce no record at all, leaving
    # users unable to distinguish "checked but empty" from "never checked".
    source = _make_hermes_home_with_user_data(tmp_path)
    (source / "skills").mkdir()
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()

    skill_items = [i for i in report["items"] if i["kind"] == "skills"]
    assert len(skill_items) == 1
    assert skill_items[0]["status"] == "skipped"
    assert skill_items[0]["reason"] == "no skills to migrate"


def test_skills_path_is_file_does_not_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: when `skills` is a regular file (misconfiguration, leftover
    # artifact, etc.) the migrator used to crash with NotADirectoryError on
    # iterdir(). It now records a clean skipped status and continues.
    source = _make_hermes_home_with_user_data(tmp_path)
    (source / "skills").write_text("this is a file, not a directory", encoding="utf-8")
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()

    skill_items = [i for i in report["items"] if i["kind"] == "skills"]
    assert len(skill_items) == 1
    assert skill_items[0]["status"] == "skipped"
    assert "not a directory" in skill_items[0]["reason"]


def test_migrate_secrets_with_no_env_still_records_channels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: a `--migrate-secrets` run against a hermes source with no
    # `.env` file (or no channel tokens) used to emit zero `channels`
    # records, leaving the user unsure whether channels were considered.
    source = _make_hermes_home_with_user_data(tmp_path)
    # Explicitly remove .env to simulate the no-secrets case.
    env_path = source / ".env"
    if env_path.exists():
        env_path.unlink()
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = HermesMigrator(
        HermesMigrationOptions(source=source, apply=True, migrate_secrets=True)
    ).migrate()

    channels_items = [i for i in report["items"] if i["kind"] == "channels"]
    assert len(channels_items) == 1
    assert channels_items[0]["status"] == "skipped"
    assert "no channel tokens" in channels_items[0]["reason"]


def test_rebrand_handles_whitespace_variants_of_hermes_agent() -> None:
    cases = [
        ("Built with Hermes Agent for power users.",         "single space"),
        ("Built with Hermes  Agent today.",                  "double space"),
        ("Built with Hermes\tAgent today.",                  "tab"),
        ("Built with Hermes\nAgent today.",                  "newline"),
    ]
    for text, label in cases:
        out, changed = _hermes_rebrand_text(text)
        assert "OpenSquilla" in out, f"{label}: rebrand did not fire for {text!r}"
        assert "Hermes" not in out.replace("HERMES_HOME", ""), (
            f"{label}: residual Hermes after rebrand: {out!r}"
        )
        assert changed is True


def test_skill_with_missing_frontmatter_is_reported_not_loadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_hermes_home_with_user_data(tmp_path)
    skill = source / "skills" / "broken"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("just plain markdown, no frontmatter\n", encoding="utf-8")
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()

    item = next(
        i for i in report["items"]
        if i["kind"] == "skills" and "broken" in (i["source"] or "")
    )
    assert item["details"]["compatibility"] == "not_loadable"
    assert "missing YAML frontmatter" in item["details"]["compatibility_issues"]


def test_skill_with_empty_frontmatter_does_not_crash_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: an empty YAML frontmatter block (``---\n\n---\n``) parses
    # to None, and the migrator used to call ``.get(...)`` on it,
    # crashing the entire migration with AttributeError. The skill should
    # be reported as not_loadable, not propagate as an unhandled exception.
    source = _make_hermes_home_with_user_data(tmp_path)
    skill = source / "skills" / "empty-fm"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\n\n---\nbody\n", encoding="utf-8")
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()

    item = next(
        i for i in report["items"]
        if i["kind"] == "skills" and "empty-fm" in (i["source"] or "")
    )
    assert item["details"]["opensquilla_loadable"] is False
    assert item["details"]["compatibility"] == "not_loadable"
    assert "missing frontmatter name" in item["details"]["compatibility_issues"]


def test_skill_with_list_frontmatter_does_not_crash_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Non-dict frontmatter (e.g. a YAML list) used to crash with
    # AttributeError on .get; report it as not_loadable instead.
    source = _make_hermes_home_with_user_data(tmp_path)
    skill = source / "skills" / "list-fm"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\n- one\n- two\n---\nbody\n", encoding="utf-8")
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()

    item = next(
        i for i in report["items"]
        if i["kind"] == "skills" and "list-fm" in (i["source"] or "")
    )
    assert item["details"]["compatibility"] == "not_loadable"
