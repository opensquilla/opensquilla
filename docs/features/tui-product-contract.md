# TUI product contract

`opensquilla chat` is OpenSquilla's interactive terminal client. The Web UI is
the control plane for configuration, monitoring, and multi-session management;
the TUI is a first-class client for working in one current session. Both clients
project the same Gateway-owned session rather than copying or owning it.

## Ownership

- The Gateway owns sessions, turns, history, queues, tool execution, usage, and
  approval decisions.
- TUI and Web UI share canonical messages and task state. Draft text, cursor,
  scroll position, theme, and local attachment staging remain client-local.
- A turn records its origin surface and reply target. A session's previous
  channel must never determine where a new TUI turn is delivered.
- `--standalone` is an explicit isolated runtime. A Gateway failure never
  silently changes a normal chat into standalone mode.

## UI selection

`opensquilla chat --ui auto|tui|plain` selects presentation only:

- `auto` prefers the packaged OpenTUI host and may fall back to plain only
  before the alternate screen starts.
- `tui` requires OpenTUI and fails with a diagnostic when it is unavailable.
- `plain` is a minimal terminal rescue surface over the same runtime contracts,
  not a separately evolving chat product.

Once a full-screen session starts, a renderer crash restores the terminal and
exits. It does not hot-switch renderers mid-turn.

## Legacy policy

Legacy chat is frozen during the TUI transition. It receives no new product
features or parity work. Only security, data-loss, and migration-critical fixes
are accepted until the supported TUI rollout gate passes, after which
legacy-only entrypoints, implementation, documentation, and tests are removed.

## macOS and Linux rollout gate

The first supported macOS and Linux RC installs an architecture-specific
companion but keeps bare `opensquilla chat` on `plain`; `--ui tui` is the
supported opt-in and explicit `--ui auto` exercises the final selection policy.
Release installs use self-contained hosts and do not require Bun, source, or a
first-run binary download. Upgrade, reinstall, and rollback keep core and host
on the same version. The next release may change the omitted policy to `auto`
only after:

- the packaged-host macOS release gate passes on arm64 and x86_64;
- the packaged-host Linux release gate passes on arm64 and x86_64;
- at least seven calendar days of RC observation complete; and
- no unresolved P0/P1 data, approval, input, or terminal-restoration issue
  remains.

The default switch and legacy alias deletion are a dedicated rollout change,
not part of the opt-in RC artifact build. Existing redacted diagnostics, release
test evidence, and issue reports are the decision inputs; the TUI does not add
anonymous runtime telemetry.

Native Windows remains a separate platform release for its host artifact,
ConPTY terminal lifecycle, process-tree cleanup, signing, installer, and native
terminal evidence. It reuses these additive product and Gateway contracts and
must not require macOS/Linux-specific behavior changes.
