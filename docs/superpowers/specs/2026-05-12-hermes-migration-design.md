# Hermes Agent to OpenSquilla Migration Design

Date: 2026-05-12
Status: Reviewed for implementation planning

## Purpose

OpenSquilla already has a native OpenClaw migration path. This design adds a native
Hermes Agent migration path so users can run one command to move a Hermes home into
an OpenSquilla home without manually rewriting configuration, copying skills, or
extracting memory files.

The migration should preserve valuable user-authored data, convert compatible
runtime configuration into OpenSquilla's TOML schema, and archive unsupported or
risky Hermes artifacts with clear notes.

## Goals

- Add `opensquilla migrate hermes`.
- Default to dry-run behavior; require `--apply` before writing files.
- Detect Hermes homes from `--source`, `HERMES_HOME`, `~/.hermes`, and profile
  directories under `~/.hermes/profiles/<name>`.
- Migrate compatible config, environment variables, persona files, memory files,
  user profile files, skills, channels, provider settings, model settings, MCP
  servers, and selected tool policy settings.
- Require `--migrate-secrets` before copying secret values.
- Preserve existing OpenSquilla config and workspace data unless `--overwrite` or
  a specific conflict policy allows replacement.
- Generate a migration report, human summary, notes file, and archive of
  unsupported source artifacts.
- Reuse the structure and safety model of the existing OpenClaw migrator.

## Non-Goals

- Do not import Hermes active sessions or conversation history into OpenSquilla
  runtime state in the first version.
- Do not copy Hermes OAuth token stores, logs, caches, checkpoints, browser session
  state, `state.db`, `kanban.db`, or transient process artifacts into active
  OpenSquilla locations.
- Do not attempt lossy two-hop conversion through OpenClaw.
- Do not change OpenSquilla's runtime config model solely to match Hermes fields
  unless a field is already supported conceptually by OpenSquilla.

## User Interface

Add a `hermes` subcommand to `src/opensquilla/cli/migrate_cmd.py`.

Supported options:

```text
opensquilla migrate hermes
opensquilla migrate hermes --apply
opensquilla migrate hermes --source ~/.hermes --apply
opensquilla migrate hermes --config ~/.opensquilla/config.toml --apply
opensquilla migrate hermes --profile work --apply
opensquilla migrate hermes --migrate-secrets --apply
opensquilla migrate hermes --preset user-data
opensquilla migrate hermes --preset full
opensquilla migrate hermes --include memory --exclude channels
opensquilla migrate hermes --skill-conflict skip|overwrite|rename
opensquilla migrate hermes --overwrite
opensquilla migrate hermes --json
```

Dry-run output should list planned writes, conflicts, skipped items, unsupported
items, and warnings. JSON output should be stable enough for tests and scripting.

## Architecture

Create `src/opensquilla/migration/hermes.py`.

The main class should mirror the existing OpenClaw migrator:

- `HermesMigrationOptions`: source path, profile, config path, apply flag,
  migrate-secrets flag, overwrite flag, preset, include/exclude filters, skill
  conflict policy, and json flag.
- `HermesMigrator`: loads source files, plans migration items, applies writes,
  records conflicts, writes reports, and returns a structured result.
- `MigrationItem`: reuse or align with the existing migration item shape.

Common behavior from the OpenClaw migrator should be reused or factored into a
small shared helper module only when that avoids duplication without changing
OpenClaw behavior. The first implementation can keep Hermes-specific mapping in
one file, but report writing, redaction, conflict handling, and archive writing
should stay consistent with the OpenClaw path.

## Source Detection

Detection order:

1. `--source`
2. `--profile <name>` under `~/.hermes/profiles/<name>`
3. `HERMES_HOME`
4. `~/.hermes`

A valid Hermes source should contain at least one of:

- `config.yaml`
- `.env`
- `SOUL.md`
- `memories/`
- `skills/`

If multiple profile candidates exist and the user did not provide `--profile`,
the migrator should migrate the root home by default and report available
profiles as suggestions.

## Target Locations

Use OpenSquilla's existing config store and path helpers:

- Config: `resolve_config_path()` and `persist_config()`
- OpenSquilla home: `default_opensquilla_home()`
- Workspace: configured `workspace_dir`, or the current OpenSquilla default
  workspace when unset
- Migration output:
  `~/.opensquilla/migration/hermes/<timestamp>/`
- Imported skills:
  `~/.opensquilla/skills/hermes-imports/`
- Unsupported artifact archive:
  `~/.opensquilla/migration/hermes/<timestamp>/archive/`

## Data Mapping

### Config

Read Hermes `config.yaml` with a YAML parser. Map compatible fields into
OpenSquilla's TOML config model:

- Hermes model/provider/base URL/API key references -> OpenSquilla `[llm]`
- Hermes provider routing where compatible -> OpenSquilla provider routing
- Hermes workspace or terminal cwd -> OpenSquilla `workspace_dir` when explicit
- Hermes skills external dirs/template vars where compatible -> OpenSquilla
  `[skills]`
- Hermes memory source settings where compatible -> OpenSquilla `[memory]`
- Hermes search/web keys where compatible -> OpenSquilla search settings
- Hermes sandbox/tool policy where compatible -> OpenSquilla sandbox/tools
- Hermes dashboard/gateway config where compatible -> OpenSquilla gateway config

Unknown config sections should not be dropped silently. They should be written to
the migration archive and summarized in `MIGRATION_NOTES.md`.

### Environment Variables

Read Hermes `.env` with a dotenv parser. Migrate recognized non-secret references
by default. Copy secret values only when `--migrate-secrets` is set.

Recognized keys should include provider and channel keys such as:

- `OPENAI_API_KEY`
- `OPENROUTER_API_KEY`
- `OPENROUTER_BASE_URL`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_BASE_URL`
- `ELEVENLABS_API_KEY`
- `BRAVE_API_KEY`
- `BRAVE_SEARCH_API_KEY`
- `TAVILY_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `DISCORD_BOT_TOKEN`
- `SLACK_BOT_TOKEN`
- `SLACK_APP_TOKEN`

Where Hermes uses `BRAVE_API_KEY`, the migrator should write the same value under
the OpenSquilla search key that the target runtime expects, preferring
`BRAVE_SEARCH_API_KEY` when configuring `search_provider = "brave"`.

Reports must redact secret values.

### Persona, Memory, and User Profile

Migrate:

- `SOUL.md` -> workspace `SOUL.md`
- `memories/MEMORY.md` -> workspace `MEMORY.md`
- `memories/USER.md` -> workspace `USER.md`
- daily or archived memory files -> migration archive unless OpenSquilla has an
  active equivalent

The migrator should merge with existing OpenSquilla files instead of overwriting
by default. It should dedupe obvious duplicate sections and preserve overflow in
the archive when a configured size limit is exceeded.

### Skills

Copy Hermes user skills from `skills/` into
`~/.opensquilla/skills/hermes-imports/`. Add that directory to
`skills.extra_dirs` if needed.

Conflict policy:

- `skip`: leave existing target skills unchanged
- `overwrite`: replace target skill files
- `rename`: import as a unique suffixed directory

The migrator should validate skill frontmatter enough to warn about Hermes-only
metadata that OpenSquilla may ignore. It should not modify skill content beyond
safe name/reference rebranding in copied text files.

### Channels

First-class migration should cover channels that OpenSquilla already supports
with compatible config semantics. The initial priority is:

- Telegram
- Discord
- Slack

OpenSquilla also has config models for Feishu, DingTalk, WeCom, QQ, MS Teams,
and Matrix. These should be migrated in the first version only when Hermes source
fields can be mapped without guessing required credentials or transport
semantics. Otherwise they should be archived and reported.

Hermes-only or currently unsupported channel families such as WhatsApp, Signal,
Mattermost, SMS, or platform-specific gateway adapters should be archived and
reported unless a compatible OpenSquilla schema is added before implementation.

### MCP Servers

Map compatible MCP server fields:

- `command`
- `args`
- `env`
- `url`
- timeout values where supported

Unsupported fields such as advanced auth, headers, cwd, include/exclude filters,
or tool policy extensions should be preserved in the archive and notes.

### Runtime State

Do not activate Hermes runtime databases or transient files in OpenSquilla.
Archive or ignore:

- `state.db`
- `state.db-wal`
- `state.db-shm`
- `kanban.db`
- `sessions/`
- `logs/`
- caches
- checkpoints
- browser profiles
- OAuth token stores such as `auth.json`

The report should explain that these are not imported by the first version.

## Presets

`user-data` should include:

- persona
- memory
- user profile
- skills
- direct user-authored workspace files explicitly recognized by the migrator,
  excluding runtime databases, logs, caches, checkpoints, generated artifacts,
  and hidden control directories

`full` should include all `user-data` items plus:

- compatible config
- environment variables
- channels
- MCP servers
- tool policy
- archived unsupported artifacts

Users can refine either preset with `--include` and `--exclude`.

## Safety and Error Handling

- Dry-run is the default.
- `--apply` is required for writes.
- Existing OpenSquilla config should be backed up before mutation.
- Existing target files should not be overwritten unless `--overwrite` or the
  conflict policy allows it.
- Secret values should never appear in terminal output, JSON output, reports, or
  notes.
- Malformed YAML, TOML, dotenv, or Markdown should produce item-level errors
  while allowing unrelated migration items to continue.
- If OpenSquilla is running, warn before applying config or channel changes.
- If Hermes appears to be running, warn before reading mutable runtime files.

## Reports

Each run should write or plan:

- `report.json`: machine-readable result
- `summary.md`: human-readable summary
- `MIGRATION_NOTES.md`: warnings, unsupported fields, manual follow-up
- `archive/`: copied unsupported source config and artifacts

The summary should include item status counts:

- planned
- migrated
- skipped
- conflict
- archived
- error

## Testing

Add unit and integration coverage for:

- Source detection from explicit path, `HERMES_HOME`, default home, and profile
- Dry-run producing no writes
- Apply mode writing config, env, memory, persona, and skills
- Secret opt-in and redaction
- Existing OpenSquilla config preservation
- Skill conflict policies
- Memory merge, dedupe, and overflow archive
- Unsupported config archival
- Malformed config item-level errors
- CLI `--json` shape
- End-to-end migration from a realistic synthetic Hermes home

Existing OpenClaw migration tests should continue to pass unchanged.

## Implementation Sequence

1. Add Hermes migration options, result structures, and source detection.
2. Add dry-run planning for config, env, persona, memory, and skills.
3. Add apply behavior with backup, conflict handling, and reports.
4. Add channel, MCP, tool policy, and archive handling.
5. Add CLI wiring and JSON output.
6. Add focused tests, then an end-to-end synthetic Hermes home test.
7. Run existing migration tests and the new Hermes migration suite.

## Open Decisions Resolved for First Version

- The first version is native Hermes -> OpenSquilla, not Hermes -> OpenClaw ->
  OpenSquilla.
- Runtime session import is excluded from the first version.
- Unsupported Hermes fields are archived and documented instead of silently
  dropped.
- Secrets require explicit opt-in.
- Dry-run remains the default command behavior.
