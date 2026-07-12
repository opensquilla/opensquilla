# Desktop Profile Recovery Contract

## Stable profile layout

`H` is an OpenSquilla profile root. Desktop sets
`OPENSQUILLA_STATE_DIR=H`; despite its historical name, the variable does not
point to the `state/` child.

```text
H/
├── config.toml
├── workspace/
├── skills/
├── media/
├── session-archive/
├── router/
└── state/
```

The workspace contains identity, persona, and Markdown memory. Session and
scheduler databases remain under `state/`. Selecting a different workspace
must never switch, merge, or delete chat history.

Desktop's primary profile is `<userData>/opensquilla`. Persistent recovery
profiles live under `<userData>/recovery-profiles/<uuid>/opensquilla` and use
independent credentials and logs. CLI installations keep their own canonical
home and do not run Desktop layout reconciliation.

## Startup states

- `ready`: the effective workspace is safe and startup continues silently.
- `attention`: the effective workspace is safe, but a preserved legacy or
  conflicting path needs an optional user choice. Startup continues.
- `recovery_required`: writing the primary profile cannot be proven safe. Its
  gateway stays stopped and the recovery page remains available.
- `recovery_profile`: an isolated persistent recovery profile is active.

An empty new profile is safe to initialize. A non-empty profile with a missing
effective workspace, malformed or future config, or uncertain transaction
requires recovery. When both `H/workspace` and `H/state/workspace` exist,
neither is moved, deleted, nor merged; current config precedence is preserved.

The recovery page offers only identity-checked operations: choose an existing
workspace, recover a known transaction, retry the primary profile, or explicitly
create or continue an isolated recovery profile. Returning to the primary
profile always performs a fresh inspection and never deletes recovery data.

## Bootstrap and writer ownership

Python owns inspection, reconciliation, workspace selection, profile import,
restore, locks, and durable transaction receipts. Electron selects the Desktop
profile, stops or starts its gateway, invokes the offline CLI, and exposes only
validated recovery actions over preload IPC.

Desktop profile inspection occurs after resolving `H` and reading config, but
before directory creation, database open, workspace seeding, memory
initialization, or any other profile write. Runtime writers hold the same
profile lock for their lifetime. Read-only commands such as gateway status and
model listing remain usable while a writer holds that lock.

Profile locks live outside profiles under the operating-system user-state
directory:

```text
OpenSquilla/profile-locks/<sha256(normalized-H)>.lock
```

Offline mutations stop the Desktop-owned gateway and acquire that lock.
Multi-profile operations acquire normalized lock keys in sorted order. Automatic
profile moves require a platform-native no-replace rename; links, reparse
points, cross-filesystem moves, or unavailable exclusion primitives fail closed
without falling back to check-then-rename or copy-delete.

Desktop settings treat `config.toml` and the profile credential as one
crash-recoverable transaction. Secret-bearing input is sent over stdin, never
argv. Before publication, the writer compare-and-swaps the original files and
preserves owner-only permissions. Credentials, Markdown, chats, and content
hashes never enter diagnostics or journals.

## Offline recovery interface

```text
opensquilla recovery inspect --home PATH --json
opensquilla recovery reconcile \
  --home PATH --profile-kind desktop-primary --json
opensquilla recovery choose-workspace \
  --home PATH --transaction-id ID --expected-revision N \
  --workspace PATH --profile-kind desktop-primary --json
opensquilla recovery recover-transaction \
  --home PATH --transaction-id ID --expected-revision N --json
opensquilla recovery restore-profile --backup PATH --json
```

Desktop also uses the internal `apply-settings` and `recover-settings`
commands for its config/credential pair transaction. Recovery commands branch
before ordinary dotenv and runtime bootstrap. `inspect` is read-only; mutating
commands re-inspect and compare the transaction id and revision under lock.

JSON stdout has a fixed, versioned shape:
`schema_version`, `outcome`, `stable_code`, `primary_home`,
`effective_workspace`, `candidates`, `allowed_actions`, `transaction_id`, and
`revision`. Human-readable logs go to stderr and must not contain file content
or secrets.

## Complete profile import

Supported CLI and Desktop homes, plus historical Windows Portable homes, are
candidates for a complete profile import. This is separate from workspace
recovery. The user must select a source even when only one is found; previous
import receipts are advisory and never hide or auto-select a candidate.

The importer keeps the source read-only, captures a no-follow manifest, creates
read-only SQLite backups with `quick_check`, and verifies the source again after
copying. Links, junctions, reparse points, special files, and a source that
changes during the snapshot prevent publication.

An empty target receives a validated staged profile. A populated target can
only be kept or replaced as a whole after an exact target-path confirmation and
a complete UUID-named backup. File-level overlay and database merge are not
supported. External workspace, state, or media roots are copied and rebased
only after they are fully captured; the new and old installations never share a
live data root silently. Imports into a recovery profile are rejected.

Replacement advances through `prepared`, `target_parked`,
`candidate_published_unvalidated`, `validated`, and `committed`. Publication
and rollback use no-replace moves. Before `committed`, failures restore the old
target when identity can be proven; uncertain state preserves the target,
backup, staging, and journal for recovery.

Imported TOML is patched losslessly. Only validated assignments are changed;
comments, ordering, quoting, unknown fields, and unmodified bytes are retained.
If a required transform cannot be expressed safely, the complete import fails
without publishing the staging profile.

## Upgrade and downgrade boundary

RC4 keeps the RC3 canonical layout shown above. RC2's nested Desktop layout is
reconciled only when its historical source and the absence of a conflicting
target can be proven. An explicit old `workspace_dir` pin remains in use and is
reported as `attention`; it is never silently rewritten.

Running an RC4 profile with RC3 or an older binary is unsupported. A layout
compatibility marker can prevent an older relocation from running again, but it
does not make newer databases, config, credentials, or unfinished transactions
backward compatible.
