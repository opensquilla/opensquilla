# Self-Migration Report Contract

This document pins the report dict returned by the OpenSquilla self-migration
source (`opensquilla migrate opensquilla`, and the `opensquilla` entry in the
migration orchestrator). Entry points — the CLI `--json` output, the
onboarding wizard, and the desktop import flows — render from these fields,
so the shape is a stable wire contract, not an implementation detail.

The producing code is `migration/opensquilla_home.py`
(`OpenSquillaHomeMigrator.migrate()`); the wire shape is tested in
`tests/test_contracts/test_migration_report_wire.py`.

## Top-Level Keys

Every report contains exactly these keys.

| Key | Type | Meaning |
| --- | --- | --- |
| `source` | `str` | Resolved source home path (`""` when resolution itself failed). |
| `source_kind` | `str` | One of `cli-home`, `windows-portable`, `desktop-home`. |
| `target` | `str` | Target home path the import lands in. |
| `output_dir` | `str` | Report/snapshot directory under `<target>/migration/opensquilla/<timestamp>`. Always `""` on a dry-run (a dry-run writes nothing anywhere). |
| `apply` | `bool` | Whether this run applied changes (`false` = dry-run). |
| `items` | `list[dict]` | Per-item results: `kind`, `source`, `destination`, `status`, `reason`, `details`. `status` is one of `migrated`, `planned`, `skipped`, `error`. User errors are recorded here — the migrator never raises for them. |
| `candidates` | `list[dict]` | Enumerated portable homes (`path`, `last_used_iso`, `size_bytes`, `era_hint`), newest first, so non-interactive callers can choose. Empty for other source kinds. |
| `config_transforms` | `list[str]` | Human-readable record of every config rewrite: dropped absolute path pins, the legacy port coercion, quarantined unknown keys, and secret relocations. |
| `secret_relocations` | `list[dict]` | One entry per inline config secret moved to the target `.env`: `{config_path, env_key, moved}`. |
| `paused_jobs` | `list[dict]` | Imported scheduler jobs, all paused: `{id, name, cron_expr}`. On dry-run this is the read-only preview from the source `scheduler.db`. |
| `preflight` | `dict` | Check results: `source_gateway_running` (bool), `target_gateway_running` (bool), `schema_ahead` (bool), `disk_required_bytes` (int), `disk_free_bytes` (int). |
| `notes` | `list[str]` | Free-form advisories that are not per-item results. |

## Redaction Guarantee

`secret_relocations` entries carry the config path and the destination env
var **name** only — never the secret value, in any field, on any code path.
Item `details` and `notes` are likewise value-free. Consumers may log or
display the report verbatim.

## Stability Promise

- Changes to this report are **additive only**: new keys may appear, existing
  keys keep their type and meaning.
- Removing or renaming a key, changing a type, or narrowing a value set is a
  breaking change and needs a migration note in the release notes plus an
  update to the wire-shape test before it ships.
- The `items` status vocabulary (`migrated`, `planned`, `skipped`, `error`)
  is shared with the other migration sources and equally pinned.
