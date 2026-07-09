"""Golden legacy-config fixtures: every released era loads on current code.

The fixture homes under ``fixtures/homes/`` freeze what each released line
actually wrote to disk (generated from each tag's own ``GatewayConfig``
full dump, with synthetic paths), plus adversarial variants for the known
compatibility gaps. The matrix test pins the era set, so shipping a new
release line means extending the fixtures — old-config upgrade behavior is
tested mechanically, not just fresh installs.

Design: docs/features/legacy-home-migration-design.md (compatibility
guarantee strategy).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

import opensquilla.gateway.config as config_module
from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.config_migration import migrate_config_payload

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "homes"

# One era per released line and install form. A new minor release (or a new
# install form) must add its era here AND as a fixture home.
RELEASED_ERAS = frozenset(
    {
        "cli-0.1",
        "cli-0.2",
        "cli-0.3",
        "cli-0.4",
        "cli-0.5",
        "portable-0.4",
        "desktop-0.4",
        "desktop-0.5rc",
    }
)

ERA_DIRS = sorted(
    p.name for p in FIXTURES_ROOT.iterdir() if p.is_dir() and p.name != "adversarial"
)
ADVERSARIAL_FILES = sorted((FIXTURES_ROOT / "adversarial").glob("*.toml"))


def _load_fixture(path: Path) -> GatewayConfig:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    result = migrate_config_payload(data)
    return GatewayConfig(**result.payload)


def test_fixture_matrix_covers_every_released_era() -> None:
    assert set(ERA_DIRS) == set(RELEASED_ERAS), (
        "Fixture homes and RELEASED_ERAS diverged. A new release line must "
        "ship a golden config fixture (see the legacy-home-migration design)."
    )


@pytest.mark.parametrize("era", ERA_DIRS)
def test_every_released_era_config_loads_on_current_code(era: str) -> None:
    config_path = FIXTURES_ROOT / era / "config.toml"
    cfg = _load_fixture(config_path)
    assert cfg is not None


def test_cli_01_era_migrates_with_expected_strips() -> None:
    data = tomllib.loads(
        (FIXTURES_ROOT / "cli-0.1" / "config.toml").read_text(encoding="utf-8")
    )
    result = migrate_config_payload(data)
    assert result.changed
    removed = set(result.removed_fields)
    assert "memory.index_captured_turns" in removed
    assert any(f.startswith("agent_token_saving.") for f in removed)
    # The 0.1 line pinned the pre-0.2 gateway port; loading must preserve it
    # (relocating it to the current default is the data migrator's transform,
    # not the config loader's).
    cfg = GatewayConfig(**result.payload)
    assert cfg.port == 18790


def test_modern_era_configs_load_without_changes() -> None:
    for era in ("cli-0.3", "cli-0.4", "cli-0.5"):
        data = tomllib.loads(
            (FIXTURES_ROOT / era / "config.toml").read_text(encoding="utf-8")
        )
        result = migrate_config_payload(data)
        assert not result.changed, (era, result.changes, result.removed_fields)


def test_desktop_eras_canonicalize_legacy_tier_keys() -> None:
    for era in ("desktop-0.4", "desktop-0.5rc"):
        cfg = _load_fixture(FIXTURES_ROOT / era / "config.toml")
        tiers = cfg.squilla_router.tiers or {}
        # Pre-rc2 desktops persisted t0-t3 tier keys; validation canonicalizes
        # them to c0-c3 (profile expansion may add non-text tiers like
        # image_model — only the legacy t-spellings must be gone).
        assert not set(tiers) & {"t0", "t1", "t2", "t3"}, (era, sorted(tiers))
        assert {"c0", "c1", "c2", "c3"} <= set(tiers), (era, sorted(tiers))


@pytest.mark.parametrize(
    "fixture", ADVERSARIAL_FILES, ids=[p.stem for p in ADVERSARIAL_FILES]
)
def test_adversarial_gap_fixture_loads(fixture: Path) -> None:
    cfg = _load_fixture(fixture)
    assert cfg is not None


def test_dream_model_override_is_stripped() -> None:
    data = tomllib.loads(
        (FIXTURES_ROOT / "adversarial" / "dream-model-override.toml").read_text(
            encoding="utf-8"
        )
    )
    result = migrate_config_payload(data)
    assert "memory.dream.model_override" in result.removed_fields
    assert "model_override" not in result.payload.get("memory", {}).get("dream", {})


def test_unregistered_channel_entry_is_parked_not_fatal() -> None:
    data = tomllib.loads(
        (FIXTURES_ROOT / "adversarial" / "msteams-channel.toml").read_text(
            encoding="utf-8"
        )
    )
    result = migrate_config_payload(data)
    assert any("msteams" in field for field in result.removed_fields)
    cfg = GatewayConfig(**result.payload)
    kept = [entry.type for entry in cfg.channels.channels]
    assert kept == ["telegram"]


def test_mismatched_tier_profile_is_cleared_not_fatal() -> None:
    data = tomllib.loads(
        (FIXTURES_ROOT / "adversarial" / "tier-profile-mismatch.toml").read_text(
            encoding="utf-8"
        )
    )
    result = migrate_config_payload(data)
    assert any("tier_profile" in change for change in result.changes)
    cfg = GatewayConfig(**result.payload)
    assert cfg.squilla_router.tier_profile is None


def test_matching_tier_profile_is_untouched() -> None:
    result = migrate_config_payload(
        {
            "llm": {"provider": "openrouter", "model": "dummy/model"},
            "squilla_router": {"tier_profile": "openrouter"},
        }
    )
    assert not result.changed


def test_out_of_range_search_max_results_is_clamped() -> None:
    data = tomllib.loads(
        (FIXTURES_ROOT / "adversarial" / "search-max-results-over.toml").read_text(
            encoding="utf-8"
        )
    )
    result = migrate_config_payload(data)
    cfg = GatewayConfig(**result.payload)
    assert cfg.search_max_results <= 20


def test_readonly_config_location_degrades_to_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A migrated-but-unwritable config must boot from memory, not fail."""
    import tomli_w

    config_path = tmp_path / "config.toml"
    with config_path.open("wb") as fh:
        tomli_w.dump({"memory": {"dream": {"model_override": "dummy"}}}, fh)

    def _raise(*args: object, **kwargs: object) -> None:
        raise PermissionError("read-only filesystem")

    monkeypatch.setattr(config_module, "backup_and_write_migrated_config", _raise)
    cfg = GatewayConfig.load_from_toml(config_path)
    assert cfg is not None
    # The original file is untouched (no partial rewrite).
    original = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert original["memory"]["dream"]["model_override"] == "dummy"
