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
| `output_dir` | `str` | Report/snapshot directory under `<target>/migration/opensquilla/<transaction-uuid>`. Always `""` on a dry-run (a dry-run writes nothing anywhere). |
| `apply` | `bool` | Whether this run applied changes (`false` = dry-run). |
| `items` | `list[dict]` | Per-item results: `kind`, `source`, `destination`, `status`, `reason`, `details`. `status` is one of `migrated`, `planned`, `skipped`, `error`. User errors are recorded here — the migrator never raises for them. |
| `candidates` | `list[dict]` | Candidate profiles returned by source discovery, with privacy-narrow display metadata: `kind`, full `path`, `version`, explicitly advisory `estimated_activity_at`, read-only SQLite `session_count`, bounded `size_bytes`, and `previously_imported`. CLI and Desktop candidates are supported installations; Windows Portable is a historical source. `last_used_iso` and `era_hint` remain compatibility aliases. Unavailable or safety-bounded values are `null`. A caller must explicitly confirm a path even when this list has one entry. |
| `config_transforms` | `list[str]` | Human-readable record of every lossless config patch: rebased path pins, the legacy port coercion, and secret relocations. Unknown or future keys block the import without changing or quarantining them. |
| `secret_relocations` | `list[dict]` | One entry per inline config secret moved to the target `.env`: `{config_path, env_key, moved}`. |
| `paused_jobs` | `list[dict]` | Imported scheduler jobs, all paused: `{id, name, cron_expr}`. On dry-run this is the read-only preview from the source `scheduler.db`. |
| `preflight` | `dict` | Check results: `source_gateway_running` (bool), `target_gateway_running` (bool), `schema_ahead` (bool), `disk_required_bytes` (int), `disk_free_bytes` (int), and privacy-safe `session_count` (`int` or `null`). |
| `notes` | `list[str]` | Free-form advisories that are not per-item results. |

## Redaction Guarantee

`secret_relocations` entries carry the config path and the destination env
var **name** only — never the secret value, in any field, on any code path.
Item `details` and `notes` are likewise secret-value-free. The interactive
stdout report may contain scheduler ids, names, and cron expressions so the
user can review what was paused; consumers must not persist that detailed
report by default.

The durable `<output_dir>/report.json` is a separate counts-only diagnostic:
transaction id, normalized source and target paths, source kind, timestamp,
item counts, and paused-job count. It has `authority: false` and contains no
item rows, scheduler ids, scheduler names, cron expressions, Markdown, chats,
or content hashes. `summary.md` likewise contains counts only.

## RC4 Transaction Contract

- The source is strictly read-only. RC4 never creates or updates
  `.opensquilla-imported.json`. An old source marker or a previously committed
  target receipt may only produce a `previously_imported` hint; neither may
  hide or auto-select a valid source.
- The sole completion authority is
  `<target>/migration/opensquilla/<transaction-uuid>/layout-receipt.json`.
  Its narrow schema records transaction, normalized path and filesystem
  identity, source kind/version, validation outcome, and layout contract. It
  contains no content hash, Markdown, chat, or scheduler row. `report.json`
  and `summary.md` are never completion authority.
- A retry with a valid matching layout receipt is idempotent and synthesizes
  the normal wire report without writing either profile. An unrelated receipt
  is rejected by transaction, path, kind, target identity, recovery, and layout
  checks.
- Apply captures a no-follow manifest containing filesystem identity, type,
  size, mtime, and an in-process-only content digest. A second scan must match
  before staging can be published. Digests are never persisted or logged.
- Source traversal and copying pin parent directories with no-follow native
  handles. A renamed parent, symlink, junction, reparse point, active SQLite
  writer, or unavailable platform primitive cancels publication.
- `config.toml` is patched from its validated original bytes. Comments,
  ordering, quoting, unknown formatting, and unmodified bytes are retained; a
  transform that cannot be expressed losslessly blocks the import.
- An empty target receives a validated staged profile. A non-empty target is
  never overlaid or merged: `--replace-target` (or deprecated `--overwrite`)
  and `--confirm-replace-target <resolved-target>` back up and replace the
  whole profile.
- Replacement uses the external `.<target-name>.profile-replace.json` journal
  and phases `prepared`, `target_parked`, `candidate_published_unvalidated`,
  `validated`, and `committed`. Publication and rollback use native
  no-replace moves.
- Every journal and replacement-history record has an exact schema. Before
  `committed`, identity-proven failures roll back; an uncertain phase preserves
  every path for offline recovery. Only a validated receipt and history may
  finalize a committed transaction.

## Stability Promise

- Changes to this report are **additive only**: new keys may appear, existing
  keys keep their type and meaning.
- Removing or renaming a key, changing a type, or narrowing a value set is a
  breaking change and needs a migration note in the release notes plus an
  update to the wire-shape test before it ships.
- The `items` status vocabulary (`migrated`, `planned`, `skipped`, `error`)
  is shared with the other migration sources and equally pinned.
