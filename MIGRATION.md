# Migration Guide

OpenSquilla can import state from OpenClaw and Hermes Agent into OpenSquilla
native files. The migration commands are designed to be previewed first, then
applied explicitly.

Supported migration paths:

- OpenClaw -> OpenSquilla: `opensquilla migrate openclaw`
- Hermes Agent -> OpenSquilla: `opensquilla migrate hermes`

If you are running from a source checkout instead of an installed
`opensquilla` command, prefix the examples with `uv run`:

```sh
uv run opensquilla migrate openclaw --json
uv run opensquilla migrate hermes --json
```

## Before You Start

1. Stop any running OpenSquilla gateway if it is using the target home.
2. Make a manual backup of your OpenSquilla home if you need whole-home
   rollback. The migrators can back up overwritten items, but they do not yet
   create a complete pre-migration snapshot of `~/.opensquilla`.
3. Run a dry run first and inspect the report.
4. Do not pass `--migrate-secrets` until you have reviewed what will be copied.

Default locations:

- OpenSquilla home: `~/.opensquilla`
- OpenClaw source home: `~/.openclaw`
- Hermes Agent source home: `~/.hermes`

On Windows, these are under your user profile, for example
`C:\Users\<you>\.opensquilla`.

## Common Options

Both migration commands support the same main controls:

| Option | Meaning |
| --- | --- |
| `--source PATH` | Source OpenClaw or Hermes Agent home. |
| `--config PATH` | OpenSquilla config path to preview or write. |
| `--apply` | Apply the migration. Without this, the command is a dry run. |
| `--migrate-secrets` | Copy recognized secrets such as API keys and channel tokens. Defaults to false. |
| `--overwrite` | Allow replacing existing targets. Existing overwritten items are backed up where supported. |
| `--preset user-data` | Migrate only user-facing data such as persona, memory, and skills. |
| `--preset full` | Migrate user data plus supported config/runtime artifacts. This is the default. |
| `--include IDS` | Include only selected migration option ids. Comma-separated. |
| `--exclude IDS` | Exclude selected migration option ids. Comma-separated. |
| `--skill-conflict MODE` | Handle imported skill name conflicts: `skip`, `overwrite`, or `rename`. |
| `--json` | Print a machine-readable report. Recommended for dry runs. |

## OpenClaw -> OpenSquilla

Use this path if your existing agent state is in an OpenClaw home.

Preview first:

```sh
opensquilla migrate openclaw --json
```

Preview a custom OpenClaw home:

```sh
opensquilla migrate openclaw --source /path/to/.openclaw --json
```

Apply without secrets:

```sh
opensquilla migrate openclaw --apply
```

Apply and copy recognized secrets:

```sh
opensquilla migrate openclaw --apply --migrate-secrets
```

Apply and rename imported skill conflicts instead of skipping them:

```sh
opensquilla migrate openclaw --apply --skill-conflict rename
```

### What Is Migrated From OpenClaw

OpenSquilla currently maps OpenClaw data into OpenSquilla-native locations:

- Workspace persona files such as `SOUL.md`, `AGENTS.md`, and `USER.md`.
- Long-term memory and daily memory where supported.
- User skills and shared skills, imported under `~/.opensquilla/skills/openclaw-imports/`.
- TTS assets, while unsupported TTS configuration is archived for review.
- Command allowlists.
- Model config, including string, object, and alias/catalog forms.
- Provider keys from `.env` or provider config when `--migrate-secrets` is set.
- MCP server definitions where OpenSquilla has native fields.
- Telegram, Discord, and Slack channel config where OpenSquilla has native channel support.
- Selected agent and tool settings with OpenSquilla-native equivalents.
- Unsupported or unsafe OpenClaw artifacts are archived for manual review.

The OpenClaw migrator also rewrites OpenClaw branding in migrated user-facing
workspace text to OpenSquilla branding and archives the original changed text
for review.

### MEMORY.md Merge Semantics

OpenClaw memory is additive by nature: every imported daily-memory file is
its own ``## Imported daily memory: <name>`` section. The OpenClaw migrator
therefore handles ``MEMORY.md`` differently from other workspace files: it
will never silently overwrite existing user-curated memory and it will
never silently drop the imported memory either.

Behaviour matrix (without ``--overwrite``):

| Destination state | What happens |
| --- | --- |
| ``MEMORY.md`` does not exist | Imported memory is written fresh. |
| Pristine OpenSquilla bootstrap template | Template is backed up, imported memory replaces it. ``details.replaced_bootstrap_template: true``. |
| Real user-curated content | Imported blocks that are not already present (after a whitespace-normalised, header-stripped comparison) are appended below the existing content. The pre-existing file is backed up first. ``details.appended_to_existing: true``, ``new_blocks_appended: N``, ``deduplicated_blocks_vs_existing: M``. |
| All imported blocks already present | The file is left untouched. ``status: skipped, reason: "all openclaw memory blocks already present in destination"``, ``details.deduplicated_against_existing: true``. No backup created. |

``--overwrite`` is the explicit "replace, do not merge" escape hatch — the
destination is backed up and replaced wholesale regardless of its current
contents.

### OpenSquilla Bootstrap-Template Handling

`ensure_agent_workspace` seeds placeholder ``SOUL.md`` / ``USER.md`` /
``AGENTS.md`` / ``MEMORY.md`` files when an OpenSquilla home is first
initialised. Without special handling those placeholders would block every
workspace-file migration with a silent ``conflict: target exists`` —
including the imported daily memory the user is migrating for in the first
place.

The OpenClaw migrator detects a destination that still holds the pristine
bootstrap template (byte-identical to the shipped placeholder after a
trailing-whitespace normalisation) and treats it as overwrite-safe:

- The pristine template is backed up to
  ``<name>.backup.<timestamp>`` next to the destination so the placeholder
  guidance can be recovered on demand.
- The imported content replaces the template.
- The migration report marks the item with
  ``details.replaced_bootstrap_template: true`` so the special case is
  visible rather than silent.

A destination file that the user has truly edited (i.e. no longer matches
the canonical template byte-for-byte) still gets the normal
``status: conflict`` treatment — only the pristine placeholder is treated
as overwrite-safe. To accept user edits being overwritten as well, pass
``--overwrite``.

### OpenClaw Limits

Some OpenClaw runtime behavior is not fully mapped yet:

- WhatsApp and Signal settings are detected, but OpenSquilla does not yet create
  native migrated channel entries for them.
- Some advanced MCP fields such as headers/auth/cwd/include/exclude are not
  native mapped.
- Some gateway, session, browser, approval, logging, plugin, cron, hook, memory
  backend, skills registry, and UI settings are archived rather than applied.
- OpenSquilla does not widen channel privileges: ordinary OpenClaw allowlists
  are not treated as OpenSquilla admin senders.

Review `MIGRATION_NOTES.md` after an applied migration for partial mappings and
manual follow-up.

## Hermes Agent -> OpenSquilla

Use this path if your existing agent state is in a Hermes Agent home.

Preview first:

```sh
opensquilla migrate hermes --json
```

Preview a custom Hermes Agent home:

```sh
opensquilla migrate hermes --source /path/to/.hermes --json
```

Preview a Hermes profile:

```sh
opensquilla migrate hermes --profile work --json
```

Apply without secrets:

```sh
opensquilla migrate hermes --apply
```

Apply and copy recognized secrets:

```sh
opensquilla migrate hermes --apply --migrate-secrets
```

Apply and rename imported skill conflicts instead of skipping them:

```sh
opensquilla migrate hermes --apply --skill-conflict rename
```

### What Is Migrated From Hermes Agent

OpenSquilla currently maps the common Hermes Agent home surface:

- Persona and user data files such as `SOUL.md`, `MEMORY.md`, and `USER.md`.
- Hermes skills, imported under `~/.opensquilla/skills/hermes-imports/`.
- Hermes model/provider config where there is an OpenSquilla-native equivalent.
- Hermes custom providers with `base_url`, mapped to OpenAI-compatible provider config.
- Environment values and recognized provider keys when `--migrate-secrets` is set.
- Search config where supported.
- MCP server definitions where supported.
- Telegram, Discord, and Slack channel tokens when `--migrate-secrets` is set.
- Selected plugin, cron, and unsupported runtime artifacts are archived for review.

### Hermes Agent Limits

The Hermes Agent migrator is newer than the OpenClaw migrator and has a smaller
coverage surface. Review the dry-run report carefully before applying.

Current limits:

- Live runtime state, active sessions, process state, and gateway state are not imported.
- Some Hermes runtime config option ids are accepted but currently deferred:
  `workspace-files`, `tools-config`, `browser-config`, `session-config`,
  `gateway-config`, `approvals-config`, `logging-config`, and `memory-backend`.
  Each appears in the migration report as `status: deferred` with reason
  `handler not implemented yet`. Selecting them via `--include` is not an
  error; the migrator just records the gap so it is visible.
- Browser, tool, session, gateway, approval, and logging settings may require manual review.
- A full pre-apply snapshot of `~/.opensquilla` is not created automatically.

### Hermes Agent Migration Behavior

The Hermes migrator now mirrors the OpenClaw migrator on a few correctness
behaviors that were previously documented but not implemented:

- **Item-level backups.** When `--overwrite` replaces an existing
  workspace file (`SOUL.md`, `MEMORY.md`, `USER.md`) or skill directory, the
  prior contents are written to `<name>.backup.<timestamp>` next to the
  original before the new content is applied.
- **Semantic deduplication on merge.** Existing destination content is split
  into paragraph blocks and compared after whitespace normalization. A new
  source body is appended unless an equivalent block already exists. The
  previous naive substring check could silently drop short source bodies.
- **Memory overflow archival.** If the merged `MEMORY.md` would exceed
  OpenSquilla's per-file size limit, the overflow is split at a paragraph
  boundary and archived to
  `~/.opensquilla/migration/hermes/<timestamp>/archive/memory-overflow/MEMORY.overflow.md`.
  A short pointer is left at the end of `MEMORY.md`.
- **Branding rewrite.** Hermes branding in imported workspace prose
  (`SOUL.md`, `MEMORY.md`, `USER.md`) is rewritten to OpenSquilla. Bare
  `Hermes` is only rewritten when it is followed by a workspace-context word
  (e.g. `home`, `workspace`, `memory`, `config`). Source-reference tokens
  such as `HERMES_HOME`, `NousResearch`, and `hermes-agent` are preserved so
  the migration archive still points back at the original source. The
  unrebranded original is copied to
  `<output_dir>/archive/files/workspace-original/<name>.md` for review.
- **Skill compatibility reporting.** Each imported skill's
  report record now includes `details.compatibility` (`loadable` /
  `needs_review` / `not_loadable`) and `details.compatibility_issues` listing
  missing frontmatter, oversize bodies, or invalid YAML. Skills are still
  copied; the field is informational so you can find ones that may need
  attention before activating.

## Reports

Use `--json` for dry-run automation:

```sh
opensquilla migrate openclaw --json
opensquilla migrate hermes --json
```

Applied migrations write report files under:

```text
~/.opensquilla/migration/openclaw/<timestamp>/
~/.opensquilla/migration/hermes/<timestamp>/
```

Typical files:

- `report.json`: structured item-level report.
- `summary.md`: human-readable count summary.
- `MIGRATION_NOTES.md`: OpenClaw migration notes when semantic conversions or
  partial mappings are present.
- `archive/`: unsupported or review-only artifacts.

Hermes dry runs also write report files. OpenClaw dry runs are best inspected
with `--json`; apply mode writes the report files.

## Validate After Migration

After applying a migration, start the gateway and run a small chat check:

```sh
opensquilla gateway start --json
opensquilla chat
```

Or use a one-shot prompt:

```sh
opensquilla agent -m "Briefly summarize your active persona and available memory."
```

Also check:

- `~/.opensquilla/workspace/` for migrated persona and memory files.
- `~/.opensquilla/skills/openclaw-imports/` or `~/.opensquilla/skills/hermes-imports/`.
- `~/.opensquilla/migration/<source>/<timestamp>/summary.md`.
- `~/.opensquilla/migration/<source>/<timestamp>/MIGRATION_NOTES.md` when present.

If behavior does not look right, stop the gateway, review the migration report,
and re-run with a narrower `--preset`, `--include`, or `--exclude` selection.

## Examples

Migrate only user data from OpenClaw:

```sh
opensquilla migrate openclaw --preset user-data --apply
```

Migrate only Hermes skills and persona files:

```sh
opensquilla migrate hermes --include soul,skills --apply
```

Preview OpenClaw migration while excluding channel settings:

```sh
opensquilla migrate openclaw --exclude telegram-settings,discord-settings,slack-settings --json
```

Apply Hermes migration to a custom config file:

```sh
opensquilla migrate hermes --config /path/to/opensquilla.toml --apply
```

