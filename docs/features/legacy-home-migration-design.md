# Legacy Home Migration Design

Date: 2026-07-10
Status: Draft

## Problem

OpenSquilla 0.5 stopped publishing Windows portable zips
(`.github/workflows/wheelhouse-release.yml` asserts that 0.5+ release assets
contain none), and the release notes direct portable users to the Electron
desktop installer or the wheel install. That guidance covers the *program*,
not the *data*: nothing imports an existing portable data directory, and the
desktop app never looks at an existing CLI home either.

Three user populations are affected:

1. **Old CLI users** — home at `~/.opensquilla`. The top-level README states
   that the desktop app reuses `~/.opensquilla/config.toml` and session data,
   but `desktop/electron/src/main.ts` contains no reference to that path: the
   desktop always creates a fresh profile under Electron `userData`.
2. **Old Windows portable users** — data at
   `%LOCALAPPDATA%\OpenSquilla\portable\<ReleaseId>` (or
   `OPENSQUILLA_PORTABLE_HOME`). Because `ReleaseId` hashes the extract path
   and the wheel, every portable upgrade already started a fresh data dir, so
   these users typically have several sibling homes, all now orphaned.
3. **Existing desktop users** — affected indirectly by the state-dir semantics
   fix this design requires (see Phase 1).

Installs whose program and data are decoupled need **no** migration: uv
tool, pipx, pip, and source checkouts share `~/.opensquilla` across upgrades
and reinstalls, and a Docker install with a persistent volume keeps
`/var/lib/opensquilla` across image updates. For those users only the
Phase 4 config-compatibility fixes apply. Migration is for changing the
*installation form*, not for upgrading in place.

The existing `opensquilla migrate` command imports foreign agent homes only:
`migration/orchestrator.py` hard-locks `SourceName` to that source list, and
`cli/migrate_cmd.py` auto-detects only those foreign home paths. There is no
OpenSquilla-to-OpenSquilla import anywhere in the codebase.

## Goals

- Import an old OpenSquilla home (CLI or Windows portable) into the current
  install with a dry-run-first, report-producing flow.
- Give desktop users a first-run entry point and a settings-level rescue
  entry point; give CLI users automatic detection in the onboarding wizard.
- Guarantee compatibility for homes written by every released version
  (v0.1.0rc1 through v0.5.0rc2), backed by fixtures and tests.
- Fix the desktop home/state-dir semantics mismatch that currently splits the
  desktop profile across two roots.

## Non-Goals

- **No shared home.** Pointing the desktop at `~/.opensquilla` is rejected:
  `writeDesktopConfig` rewrites desktop-owned config sections on every
  settings save, desktop reset deletes `config.toml`, and desktop uninstall
  enumerates the whole home — all destructive against a hand-authored CLI
  config. The gateway pid lock is an exclusive per-state-dir lock and the
  desktop has no attach-to-running-gateway flow, so a shared home would not
  deliver concurrent CLI + desktop use anyway. The migration copies.
- **No merge of two populated homes.** File-level copy cannot merge two
  `sessions.db` files. Import applies into an empty target (first run) or
  with explicit overwrite plus backups.
- **No ongoing config synchronization** between a CLI home and a desktop home
  after the copy.
- **No multi-profile fan-in.** Profile homes under
  `~/.opensquilla/profiles/<name>` are excluded from a `cli-home` copy; a
  single profile home can be imported explicitly via `--source <path>`, but
  merging several profiles into one target is out of scope.
- **No in-place Docker volume adoption flow.** A bind-mounted Docker home
  can already be adopted in place by pointing `OPENSQUILLA_STATE_DIR` at
  it; a named volume must be extracted to a local directory first and
  imported via `--source <path>`. No container orchestration is included.

## Background: What Each Release Wrote to Disk

An audit of every released tag (v0.1.0rc1, v0.2.0rc1, v0.2.0, v0.2.1,
v0.3.0, v0.3.1, v0.4.0, v0.4.1, v0.5.0rc1, v0.5.0rc2) established the
following load-bearing facts.

### Layout stability

- The home layout has been stable since the first release: home root holding
  `config.toml`, `.env`, `workspace/`, `skills/`, `media/`, `logs/`, with
  runtime state under the `state/` subdirectory. `paths.py` was byte-identical
  from v0.1.0rc1 through v0.4.1; the only released change is the profile mode
  added in v0.5.0rc1.
- The portable data-dir scheme is byte-identical across all portable-shipping
  tags (v0.1.0rc1 through v0.4.1): `ReleaseId` is derived from
  SHA-256 of `"<extract path>|<wheel hash prefix>"`, the base directory is
  `%LOCALAPPDATA%` with a `%TEMP%` fallback, and `OPENSQUILLA_PORTABLE_HOME`
  overrides both. The launcher exports `OPENSQUILLA_STATE_DIR=<data dir>`,
  so a portable data dir **is** a relocated CLI home, shape-identical.
- The desktop home path is byte-identical from v0.4.0 (the first desktop
  release) through current `main`: `userData/opensquilla` with
  `userData/opensquilla/state` and `userData/desktop-credential.json`.
  One locator suffices, but four credential schema cohorts exist (see
  Secrets below). Desktop builds ship for macOS and Windows only; the
  locator is Electron `userData` resolution (which covers Linux dev builds
  for free), and Python-side code must not hardcode the platform paths.
  Note that OS-level desktop uninstall leaves this data in place on both
  shipped platforms — only the in-app cleanup removes it.

### The state-dir semantics mismatch

`OPENSQUILLA_STATE_DIR` names the OpenSquilla **home root** on the Python
side (`paths.py: default_opensquilla_home()`), and runtime state goes into
the `state/` subdirectory beneath it. The desktop gateway spawn sets it to
the state *subdirectory* (`desktopStateDir()`), while the desktop uninstall
spawn deliberately sets it to `desktopHome()` — the code comment beside the
uninstall spawn documents the inconsistency. Consequences today:

- Everything the gateway derives from the env home root — managed skills and
  `skills-taps.json`, the default workspace (including `MEMORY.md` and
  markdown memory notes), `session-archive/`, router self-learning data,
  logs, a user-created `.env` — lands under `<desktopHome>/state/...`, one
  level deeper than intended, including a nested `state/state/` tree for the
  direct `paths.state_dir()` consumers (router calibration, sandbox user
  grants, approval queue, safety log).
- Databases are unaffected because the desktop-written `config.toml` pins
  `state_dir` explicitly and boot honors the config value for `sessions.db`,
  `scheduler.db`, and per-agent `memory.db`.
- No test pins the gateway spawn's `OPENSQUILLA_STATE_DIR` value; the only
  assertion in `tests/test_desktop/test_electron_startup_contract.py` covers
  the uninstall spawn.

A config-only fix is impossible: the `.env` location, config-file discovery,
log dir, default managed-skills dir, and the direct `paths.state_dir()`
consumers have no config knobs.

### Database upgrade guarantees (verified per tag)

- **sessions.db — auto-upgrades from every released tag.** Schema migrations
  ran at gateway boot in every release, so any released database carries a
  migration ledger that is a strict subset of the current set;
  `apply_pending` applies the delta and the schema-ahead guard cannot fire
  for released data. Columns added outside the migration set are covered by
  connect-time conditional ALTERs in `session/storage.py`. The
  meta-skill-run, router-decision, and turn-error tables are created only by
  the boot-time migrator, so import must let boot (or `apply_pending`) run
  before any subsystem writes.
- **scheduler.db — auto-upgrades from every released tag** via
  `scheduler/persistence.py`: `CREATE TABLE IF NOT EXISTS` plus
  PRAGMA-guarded conditional column adds over the full column superset, plus
  datetime normalization, at every open. Verified dynamically: a database in
  the v0.1.0rc1 shape opens on current `main` with jobs intact.
- **memory.db — auto-upgrades.** The store schema version string has been
  the same at every tag, so the drop-and-rebuild path is unreachable for
  released data. An embedding provider/model change clears only the index
  tables, keeps the embedding cache, and re-syncs from markdown (the durable
  source of truth); the loss bound is re-embedding cost.
- **approval_queue.sqlite** and **sandbox grants** — conditional ALTERs cover
  every shipped shape.
- All stores run WAL mode. A copy must include `-wal`/`-shm` sidecars or
  checkpoint first, or the newest writes are silently lost.

### Config upgrade guarantees and hard gaps

Every released tag persisted `config.toml` as a **full schema dump**
(`exclude_defaults=False`), so old files carry every then-current key at its
then-current value. Round-tripping each tag's default dump through
`gateway/config_migration.py` plus current validation was verified for all
ten tags: v0.1/v0.2-era files load with strips/renames and a timestamped
backup; v0.3.0+ files load unchanged. Provider ids are strictly additive and
provider env-var names never changed.

Because root validation is fail-closed (`extra='forbid'`), four verified
gaps brick or degrade an import today:

1. `memory.dream.model_override` — a legal, settable field in
   v0.1.0rc1–v0.2.1, removed in v0.3.0 with no migration strip. A config
   that carries it fails validation entirely. (Default dumps omit it; only
   users who set it are affected.)
2. A channel entry with a type that is no longer registered (configurable in
   v0.1.0rc1 only) raises during validation even when the entry is disabled,
   rejecting the whole file.
3. A hand-edited `llm.provider` that no longer matches
   `squilla_router.tier_profile` hard-fails validation with a message that
   does not point at the import.
4. The first-load backup-and-rewrite path for pre-v0.3.0 configs has no
   error handling for read-only locations; importing must copy into a
   writable target before first boot.

### Migrator-only obligations (nothing auto-heals these)

- **Portable absolute-path pinning.** Every portable `config.toml` pins
  `state_dir`, `workspace_dir`, and the media root as absolute paths inside
  the old portable tree, and v0.1.0rc1-era dumps also pin the old default
  gateway port. Config migration renames keys but never relocates paths; the
  importer must rewrite or drop these values.
- **Secrets live inside config.toml.** No released tag ever wrote `.env`;
  onboarding stored typed API keys inline (`llm.api_key` at every tag, audio
  provider keys from v0.3.1, `llm_profiles.*.api_key` from v0.5.0rc1, and
  channel tokens throughout). The importer must treat inline config values as
  the primary secret source, relocate them per current hygiene, and redact
  them from reports and logs.
- **Portable multi-home reality.** One home exists per (extract path × wheel)
  pair with no carry-forward, so sibling homes are the norm. `ReleaseId` is
  not re-derivable; enumeration plus era detection (install receipt from
  v0.4.1+, update-check state from v0.5.0rc2+, mtime) plus a user-facing
  chooser is required. `%TEMP%`-fallback homes may be partially collected;
  `OPENSQUILLA_PORTABLE_HOME` is accepted as explicit CLI input only, since
  a GUI first run cannot see shell-profile env vars.
- **Structural traps.** Profile homes (v0.5.0rc1+) nest *inside*
  `~/.opensquilla/profiles/<name>` and must be excluded from a recursive
  copy of the legacy home. Homes with a customized `state_dir` split runtime
  state across two roots (config-derived vs env-derived); both must be
  collected.
- **Desktop credentials.** Four cohorts exist (v0.4.0, v0.4.1, v0.5.0rc1,
  v0.5.0rc2+). The current normalization in `main.ts` reads all of them; a
  Python-side reader must mirror it. Credentials marked for OS-keychain
  encryption cannot be decrypted outside the originating Electron app and
  OS user — the importer carries the file but must re-prompt for the key and
  say so explicitly.

## Design

### Phase 1 — Desktop home/state alignment (ships first, atomic)

1. Change the desktop gateway spawn to `OPENSQUILLA_STATE_DIR=desktopHome()`,
   keeping the TOML-pinned `state_dir` and the `--config` argument unchanged
   so databases never move.
2. Ship, in the same change, a one-time in-place relocation for existing
   desktop installs, run by the Electron main process before the first spawn
   with the new env and with the gateway confirmed down: move
   `state/skills`, `state/skills-taps.json`, `state/skills-lock.json`,
   `state/workspace`, `state/session-archive`, `state/router`, `state/.env`,
   and flatten `state/state/*` up one level. Do not touch `state/sessions.db`
   (with sidecars), `state/scheduler.db`, or `state/agents/` — those are
   config-pinned and already correct. Write an idempotency marker; leave the
   old nested dirs as renamed backups rather than deleting.
3. Add gateway-spawn env assertions to
   `tests/test_desktop/test_electron_startup_contract.py` (currently the
   value is unpinned) so neither the fix nor a regression ships silently.
4. Note the downgrade hazard in release notes: an older desktop build
   re-spawned after relocation will not see the moved data.

Without Phase 1, "migrate into the desktop home" has two different answers
for where `.env`, skills, and workspace belong.

### Phase 2 — Self-migration source

Add an `opensquilla` source to the migration orchestrator (extending the
source literal, detection, and per-source option validation), with three
source kinds:

- `cli-home` — default `~/.opensquilla`, excluding `profiles/`. Accepts an
  explicit `--source <path>` (matching the existing migrate convention for
  foreign homes), which also covers Docker volumes and bind mounts
  (extracted or mounted locally), homes relocated via
  `OPENSQUILLA_STATE_DIR`, restored backups, and individual profile homes —
  all shape-identical to a CLI home.
- `windows-portable` — enumerate `%LOCALAPPDATA%\OpenSquilla\portable\*` and
  the `%TEMP%` fallback base, pair with wheelhouse venv markers, era-detect,
  and present a chooser showing size, era, and last-used derived from
  `config.toml` mtime or the newest `sessions.db` row (directory mtime can
  mislead), with an optional read-only session count reusing the read-only
  open pattern required for the ledger pre-flight.
- `desktop-home` — the platform Electron `userData/opensquilla` directory,
  for users moving from the desktop app to a CLI install or to a new
  machine (OS-level desktop uninstall strands this data on both shipped
  platforms). Reuses the credential-cohort reader described above;
  keychain-bound credential values cannot be decrypted outside the
  originating app and OS user and are always flagged for re-entry. This
  kind ships after the first two.

Copy protocol:

1. **Pre-flight**: refuse (or require explicit acknowledgement) when the
   source home's gateway pid lock is held; read the source `sessions.db`
   migration ledger read-only and reject newer-than-binary homes before
   copying anything; verify free space — sum the source home size (already
   computed for the chooser) and refuse when it exceeds the target volume's
   free space minus a margin, surfacing the shortfall in the report; and
   pre-validate the source config through `migrate_config_payload` plus
   schema validation in a sandbox pass, quarantining unknown keys instead
   of letting fail-closed validation brick the first boot.
2. **Copy**: whole-home copy (completeness over curation — the layouts are
   shape-identical), deriving scope from the uninstall inventory bucket list
   plus the home-root router self-learning directory, including
   `-wal`/`-shm` sidecars for all five SQLite stores (or checkpoint first),
   and snapshotting all five databases before first open. The write is
   **transactional**: copy into a temporary sibling directory of the target
   and atomically rename into place, so an interrupted or cancelled import
   never leaves a partial target — and never trips the non-empty-target
   refusal on re-run. On Windows, normalize source and destination paths to
   extended-length (`\\?\`) form before copy operations; deep portable
   workspace trees routinely exceed the 260-character default limit. Refuse
   a non-empty target state unless `--overwrite` is given (per-item
   timestamped backups, matching the existing migration convention).
3. **Transform (the part that is not a copy)**:
   - rewrite or drop absolute `state_dir` / `workspace_dir` / media-root
     config values; coerce a pinned legacy default port to the current
     default;
   - open the copied `scheduler.db` and disable all jobs
     (`UPDATE ... SET enabled = 0`) before the first gateway boot, so
     migrated autonomous jobs cannot fire against freshly configured
     credentials before the user reviews them;
   - relocate inline config secrets: the primary provider key feeds the
     desktop credential / onboarding prefill; everything else moves to the
     target home `.env`; document that desktop-owned config sections are
     regenerated from the desktop credential.
4. **Report**: dry-run by default, emitting a machine-readable report —
   discovered homes (with the candidate list, so non-interactive callers
   can choose), per-data-kind verdict, path-rewrite plan, secret
   relocation plan, and unrecoverable items (keychain-bound credentials)
   flagged for re-prompt. The contract covers the **apply result** too:
   per-bucket applied/failed/backed-up status and an enumeration of
   imported scheduler jobs (id, name, schedule) so entry points can tell
   the user what was paused. In overwrite mode, a partially failed apply
   reports which buckets failed and were restored from their timestamped
   backups; failed buckets are retryable once the cause is fixed. The
   report shape is pinned as a contract (documented next to the
   session-view contract, tested in `tests/test_contracts/`).

### Phase 3 — Entry points

- **CLI**: wire the new source into **both** detection sites — the
  orchestrator's default detection *and* the migrate command's own
  duplicated detection list (or fold the latter onto the former as part of
  this change) — so it surfaces in the onboarding wizard's existing
  migration pre-step and in bare `opensquilla migrate`. Non-interactive
  selection is explicit: `--source windows-portable --home <path>` names
  one of the enumerated candidate homes, and the JSON dry-run report lists
  the candidates so scripts can choose without a prompt.
- **Desktop onboarding (primary)**: a migration step at the *start* of the
  onboarding window flow, before provider setup — the only interaction point
  before the gateway first boots (import must precede first boot because
  boot creates `sessions.db` and the scheduler-pause transform must land
  before jobs are scanned). Detecting a legacy home offers dry-run → apply,
  then prefills the provider step from the imported config. The copy
  streams per-bucket progress to the onboarding window over a desktop IPC
  event channel (modeled on the existing update-state events) with a cancel
  action; cancellation or a crash leaves no partial target thanks to the
  transactional write. Unrecoverable credentials surface per class: the
  primary provider key lands in the (empty) provider step, while secondary
  keys and channel tokens are listed in a post-import notice pointing at
  Settings / the target `.env`. The completion screen states how many
  scheduler jobs were imported paused (linking to the Cron view) and that
  the source home was left untouched at its original path, including how
  to reclaim that space later.
- **Desktop settings (rescue)**: an "Import legacy data" action beside the
  existing desktop settings IPC handlers, for users past first run. Stricter
  semantics: stop the gateway, dry-run, explicit overwrite confirmation with
  backups, apply, restart. It combines two existing precedents: the
  uninstall flow's stop → dry-run → confirm → apply-via-bundled-CLI shape,
  and the settings-reset flow's restart-with-boot-splash pattern (the
  uninstall flow deliberately leaves the gateway down). The Electron main
  process orchestrates lifecycle and spawns the bundled CLI
  (`opensquilla migrate ...`) so the migration logic exists exactly once,
  in Python. Because the gateway is stopped during the operation, the
  rescue flow's UI runs over desktop IPC — the Web UI console's RPC
  transport dies with the gateway.
- **Web UI console (advisory only)**: executing the migration stays at the
  Electron/CLI layer because it requires a quiesced gateway — but
  *detection* is a read-only path scan that is safe under a running
  gateway. The onboarding status payload (or a doctor finding) gains a
  legacy-data block, rendered in the Web UI setup flow as "legacy
  OpenSquilla data found at `<path>` — stop the gateway and run
  `opensquilla migrate`". This is the route that reaches ex-portable users
  who wheel-install per the release notes and onboard via the browser.
- **Headless and channels-first users**: a one-line gateway boot warning
  when the active home looks freshly created and detection finds a legacy
  home, plus an `opensquilla doctor` finding recommending the migrate
  command — both read-only reuses of the Phase 2 detection code. TUI and
  channels-first setups have no wizard of their own and funnel through
  `opensquilla onboard` or these surfaces.
- Execution always lives at the Electron/CLI layer: migration requires a
  quiesced gateway, and only the Electron main process (or the user's own
  shell) owns the gateway lifecycle. The Web UI's role is detection and
  advice only.
- **Localization**: every new user-facing string (onboarding step, settings
  action, progress, report and error text) ships in all desktop locale
  table entries, and the Web UI advisory strings in the Web UI locale
  files; the machine-readable report is rendered to localized text on the
  Electron side rather than shown raw.

### Phase 4 — Compatibility fixes in product code

Convert the verified hard gaps into auto-handled cases, independent of the
migrator (they also fix in-place upgrades):

1. Strip `memory.dream.model_override` in the always-run config migration.
2. Park (drop with a logged warning) channel entries whose type is no longer
   registered instead of failing validation.
3. Clear `squilla_router.tier_profile` when it no longer matches
   `llm.provider`, with a warning.
4. Degrade the config backup-and-rewrite path to warn-and-continue when the
   config location is not writable.

## Compatibility Guarantee Strategy

1. **Golden fixture homes per era** (synthetic data only, per repository
   data-hygiene policy) under `tests/test_migration/fixtures/homes/<era>/`:
   one miniature home per source era (CLI per minor line, portable, desktop),
   with config fixtures frozen from each tag's real default full dump plus
   adversarial variants for every named gap (the four config gaps, the
   legacy port pin, legacy tier spellings, absolute portable paths, inline
   keys, and a Windows fixture with a nested workspace path exceeding 260
   characters). Database fixtures are built at test time from each tag's
   schema DDL with a few synthetic rows.
2. **Upgrade tests in existing shapes**: parametrized
   load-every-golden-config-on-current-code tests beside the existing config
   legacy tests; end-to-end import tests in `tests/test_migration/` (copy
   fixture home → import → boot components → assert latest sessions schema,
   scheduler opens with jobs paused, memory relocation shims fire, approval
   queue backfills); a WAL-safety test asserting the checkpoint step
   prevents loss; an interrupted-copy test asserting the transactional
   write leaves no partial target; and an apply-failure test asserting the
   overwrite-mode backup restore reaches a consistent state.
3. **Report contract**: the dry-run report schema is documented and pinned
   by a wire-shape test in `tests/test_contracts/`.
4. **Matrix as contract**: a test asserts the fixture set enumerates every
   released tag, so a new release cannot ship without extending the
   fixtures — the mechanical form of the existing policy to test old-config
   upgrade behavior, not just fresh installs.

## Post-Migration Usability Checklist

- Gateway boots; imported `sessions.db` reaches the latest schema via the
  boot-time migrator.
- Web UI lists imported sessions (already true: the session list RPC does
  not filter by origin) and can resume one.
- Provider usable via the prefilled credential; secondary providers resolve
  from the migrated `.env`.
- Markdown memory and the memory index agree (no stranded index entries);
  skills and taps load.
- Migrated scheduler jobs are present and paused; the completion surfaces
  say how many were paused and link to the Cron view to re-enable them.
- Imported non-desktop config sections survive a desktop settings save.
- Keychain-bound desktop credentials are reported as requiring re-entry, not
  silently dropped.
- The user is told where the untouched source home remains on disk and how
  to reclaim the space (manual removal for CLI/portable/Docker homes — the
  desktop cannot uninstall a foreign home).

## Documentation Corrections (ship with any phase)

- Top-level README (and localized variants): replace the claim that the
  desktop reuses `~/.opensquilla` with a description of the import flow.
- Release notes: correct the "config and session data are reused" claim for
  ex-portable users, whose data was never at `~/.opensquilla`.

## Delivery Order

1. Phase 1 (desktop alignment + relocation + contract-test pins).
2. Phase 4 compatibility fixes + golden fixtures (independently valuable).
3. Phase 2 self-migration source + CLI entry (`cli-home` and
   `windows-portable` first; the `desktop-home` source kind follows).
4. Phase 3 desktop onboarding and settings entries, Web UI advisory, and
   the boot/doctor detection surfaces.
5. Documentation corrections ride along with the first phase that lands.
