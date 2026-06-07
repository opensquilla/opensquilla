---
name: multi-profile-setup
description: "Use when the operator asks to set up, add, or batch-initialise OpenSquilla agent profiles — multi-instance side-by-side gateways, MiniMax-M3 first-class provider, per-profile logon autostart on Windows / macOS / Linux, or `opensquilla profiles init-all` to bring every profile under $OPENSQUILLA_HOME up at once."
always: false
triggers:
  - multi-profile
  - multi instance
  - side-by-side
  - 多 profile
  - 多实例
  - 多实例
  - 多个 agent
  - 多个 agent
  - 多 agent
  - 多个 profile
  - 多个 profile
  - profiles init-all
  - profiles list
  - profile 列表
  - 批量初始化
  - 批量 init
  - 一键初始化
  - 一键 init
  - 新建 profile
  - 新建 agent
  - 开机启动
  - 开机自启
  - 开机自动启动
  - autostart
  - login item
  - launch agent
  - systemd
  - task scheduler
  - 注册开机启动
  - 注册 autostart
  - minmax
  - minimax m3
  - minimax-m3
  - 秘塔
  - 秘塔 M3
provenance:
  origin: opensquilla-contrib
  license: Apache-2.0
  upstream_url: https://github.com/opensquilla/opensquilla
  maintained_by: tqangxl
metadata:
  opensquilla:
    requires_tools:
      - bash
      - powershell
---

# Multi-profile setup, MiniMax-M3, and per-profile logon autostart

This skill covers the operator-facing workflow for the features
landed in PR #194 (multi-instance profile mode), the related
follow-ups (MiniMax-M3 in init / control-setup, dev-install
wrapper, `--autostart` on init), and the per-profile autostart +
`profiles init-all` follow-up. Reach for this skill whenever the
operator mentions multiple gateways on one host, MiniMax / 秘塔
as a provider, or wanting agent profiles to come back up at logon
without manual intervention.

## When to use

Reach for this skill when the operator:

- Wants to run more than one OpenSquilla gateway on the same
  machine (separate state, separate `.env`, separate ports).
- Mentions MiniMax / 秘塔 / `minimax/MiniMax-M3` as their LLM
  provider, especially for a new install or a re-init.
- Asks for a profile to start automatically at user logon
  (Task Scheduler on Windows, LaunchAgent on macOS, systemd
  --user on Linux).
- Asks to "initialise every profile" or "set up all of them at
  once" — i.e. the new `opensquilla profiles init-all` workflow.
- Is following the README "Multi-instance profiles" / "Per-profile
  logon autostart" / "Initialising every profile in one go" sections.

If the operator just wants a single-agent install, do **not**
use this skill — point them at `opensquilla --install-completion`
and the default install path; multi-instance is opt-in.

## Core workflows

### 1. Multi-instance profile mode (`OPENSQUILLA_HOME` + `OPENSQUILLA_PROFILE`)

- Resolution precedence: `OPENSQUILLA_STATE_DIR` (full override,
  back-compat) → `OPENSQUILLA_HOME` + `OPENSQUILLA_PROFILE`
  (multi-instance) → `$HOME/.opensquilla` (single-instance default).
- The CLI has a top-level `--profile` flag that mirrors
  `OPENSQUILLA_PROFILE`. Either form is fine.
- For a fresh multi-instance host, set
  `OPENSQUILLA_HOME=D:\ai\opensquilla\profiles` (Windows) or
  `export OPENSQUILLA_HOME=/home/me/profiles` (POSIX), then create
  per-profile subdirs (`mkdir coder default test`).
- `OPENSQUILLA_STATE_DIR` still wins when set — leave it unset on
  multi-instance hosts.

### 2. MiniMax-M3 first-class provider

- `init` wizard lists `minimax` (plus `minimax_openai`,
  `minimax_cn`, `minimax_global`) in the provider dropdown.
  Default model for all four is `minimax/MiniMax-M3`.
- `control/setup` page also lists the four variants with the same
  M3 default; the Web UI's `api_key` and `api_key_env` fields are
  mutually exclusive (a `Save failed: configure either api_key or
  api_key_env, not both` is a UI bug, not a real conflict — the
  setup page submits the api_key XOR api_key_env guard on the
  user's behalf).
- Three ways to put a key on the wire, in increasing security:
  - `init --api-key-env MINIMAX_API_KEY` and source the env var
    elsewhere. Nothing sensitive lands in `.env`.
  - `init --api-key <token>` writes the value into `.env`.
  - Paste the token into the WebUI's API key field; the form
    auto-clears the matching `api_key_env` so the server-side
    guard is never tripped.

### 3. Per-profile logon autostart (issue #193)

- `opensquilla --profile <name> init --autostart` registers a
  per-profile startup entry after the env / config files are
  written. Off by default; opt in per profile.
- `opensquilla profiles init-all --provider <id> [--api-key |
  --api-key-env]` runs autostart by default; pass `--no-autostart`
  to opt out (e.g. on a dev box that should not auto-start).
- Platform contract: Task Scheduler on Windows, LaunchAgent on
  macOS, systemd --user on Linux. Each is a one-task-per-profile
  entry, independent of the host's other profiles.
- Requires the `opensquilla` binary on `PATH`. If
  `uv tool install` is the install path, `bash
  scripts/dev-install.sh` from the repo checkout wires the
  editable shim; for release installs, `uv tool install
  opensquilla` does the same without the checkout.
- Rollback: `uninstall-autostart.ps1` (Windows), `launchctl unload
  -w ~/Library/LaunchAgents/com.opensquilla.<profile>.plist`
  (macOS), `systemctl --user disable --now
  opensquilla-<profile>.service` (Linux).

### 4. `opensquilla profiles init-all`

- Scans `$OPENSQUILLA_HOME/profiles/*/`, writes the same provider
  / API-key / model triple to every uninitialised profile, and
  registers the per-profile logon autostart entry. Skips
  already-initialised profiles by default (`--all` overrides).
- Idempotent: re-running with the same flags is a no-op for
  profiles that already have both `.env` and `config.toml`.
- Failures inside the autostart dispatcher on one profile are
  surfaced per-row and do not abort the loop — the remaining
  profiles are still initialised.

### 5. Dev install (so `opensquilla` is on `PATH`)

- Release path: `bash install.sh` (POSIX) or
  `powershell -File install.ps1` (Windows). Both default to
  `OPENSQUILLA_INSTALL_PROFILE=recommended`, which pulls in
  numpy / joblib / scikit-learn / onnxruntime / lightgbm etc. so
  the SquillaRouter loads cleanly.
- Source / dev path: `bash scripts/dev-install.sh` /
  `powershell -File scripts/dev-install.ps1`. These wrap
  `uv tool install -e ".[recommended]" --force --upgrade` so you
  do not have to remember the PEP 508 extras form.
- A bare `uv tool install -e .` will succeed but the gateway will
  start with "bundled ONNX router failed to load" and fall back
  to safe-routing mode. Always use the recommended extra or
  the wrapper.

### 6. Profile `[llm]` audit & repair

A fleet-wide init can land every profile with `provider` and
`model` set but the **`api_key_env`** line blank, the
**`base_url`** missing, or the env-var name not matching the key
that actually lives in `<profile>/.env`. Symptom: `gateway start`
succeeds, the WS `chat.send` returns `ok: true, status: accepted`,
`opensquilla --profile X agent --message "ping"` shows the
provider ready line, then nothing — the LLM is never called.
There is **no error in the daemon debug log** because
`build_services.provider_ready` runs at startup, not on the first
chat.

Authoritative provider registry lives in
`src/opensquilla/provider/registry.py`. The four MiniMax variants
all have a `runtime_supported` adapter there. Per-provider defaults
(verified directly from `_spec(...)` calls in `registry.py`, not
guessed):

| `provider`        | `env_key` (spec)         | `default_base_url`                        |
|-------------------|--------------------------|-------------------------------------------|
| `minimax`         | `MINIMAX_API_KEY`        | `https://api.minimaxi.com/anthropic`      |
| `minimax_openai`  | `MINIMAX_API_KEY`        | `https://api.minimaxi.com/v1`             |
| `minimax_cn`      | `MINIMAX_CN_API_KEY`     | `https://api.minimaxi.com/anthropic`      |
| `minimax_global`  | `MINIMAX_API_KEY`        | `https://api.minimax.io/anthropic`        |

> **Heads-up**: the four adapters share the same `provider_kind`
> ("minimax") but the cn variant uses a *different* env-var name
> (`MINIMAX_CN_API_KEY`). A profile initialised with
> `provider = "minimax_cn"` plus a `.env` line `MINIMAX_API_KEY=...`
> will silently read the wrong key. Always cross-check
> `config.toml` `api_key_env` against the table above.

**Quick audit** — load each profile, compare the `[llm]` block
to the table, list the diffs. A 30-line script in
`_scan_profiles.py` (this session) does it in Python with
`tomllib` so we do not depend on `tomli` being installed.

**Repair recipe** (idempotent, backup-before-write):

1. Read every `<profile>/config.toml` and find the `[llm]` block.
2. If `api_key_env` is missing or empty, write the default from
   the table above (key based on the `provider` value).
3. If `base_url` is missing, write the default from the table.
4. Back up to `<profile>/config.toml.bak.batch` on first edit
   per run, then write the patched config.
5. Stop the affected gateway (`opensquilla --profile X gateway
   stop --json`), trash the orphan `state/gateway.pid` and
   `state/gateway.pid.lock` (the on-main pidlock doesn't auto-
   recover; PR #217 will), and `opensquilla --profile X
   gateway start --json`.
6. Single-shot reply smoke test:

   ```sh
   opensquilla --profile <name> agent --message "ping - reply with one short sentence" --unattended
   ```

   You should see `build_services.provider_ready
   model=…/MiniMax-M3 provider=…` and a one-line reply
   ("Pong" or similar) within 10s on MiniMax-M3.

7. For the gateway (WS) path, reconnect with the
   `chat.send → /v1/chat` frame and confirm a `chat.done`
   event with a `text` payload arrives within `agent_stream_
   heartbeat_interval_seconds` (default 15s).

**Why this happens.** The bug is in
`src/opensquilla/cli/init_cmd.py::persist_profile` — the function
shared by both the WebUI / wizard `init` and the batch
`profiles init-all` command. Pre-fix, it only wrote `provider` and
`model` to `<profile>/config.toml`; `api_key_env` and `base_url`
were left blank, and the env-var name in `<profile>/.env` was
derived from `f"{provider.upper()}_API_KEY"` (which got `minimax_cn`
wrong — the spec uses `MINIMAX_CN_API_KEY`, not
`MINIMAX_CN_API_KEY`... wait, that *is* what the spec uses, but
older versions of the helper wrote `MINIMAXI_API_KEY` for the cn
and openai variants, which is why legacy profiles have a
non-canonical env name). Empty strings are not the same as
missing keys, and `provider_ready` does not require the key to be
present in `os.environ` — it just confirms the adapter can be built.

The fix landed in the `fix/persist-profile-llm-fields` branch:
`persist_profile` now pulls `env_key` and `default_base_url` from
`ProviderSpec` (`opensquilla.provider.registry.get_provider_spec`)
instead of guessing, and writes all four fields atomically. The
caller's `api_key_env` label is treated as a *delivery channel*
("here is the env-var I want to pass the key in") and is never
written into the persisted config — the persisted name is always
the spec's canonical one. For local providers (`ollama`, `vllm`,
`lm_studio`, `ovms`) the `api_key_env` line is omitted entirely
because `requires_api_key()` returns `False`. New regression tests
in `tests/test_cli/test_init_cmd.py` lock the four-field write
behaviour, the caller-label-drop behaviour, the local-provider
skip, and the `UnknownProviderError` raise.

## Reference commands

```sh
# Show every profile under $OPENSQUILLA_HOME/profiles with state
opensquilla profiles list

# Initialise every uninitialised profile with OpenRouter
opensquilla profiles init-all \
    --provider openrouter \
    --api-key-env OPENROUTER_API_KEY

# Same, with autostart registration turned on (default) and
# every profile re-written (skip the "already initialised" filter)
opensquilla profiles init-all \
    --provider openrouter \
    --api-key-env OPENROUTER_API_KEY \
    --all

# Initialise a single profile with MiniMax-M3 + logon autostart
opensquilla --profile coder init \
    --provider minimax \
    --api-key-env MINIMAX_API_KEY \
    --autostart
```

## Pitfalls

- `OPENSQUILLA_STATE_DIR` set on a multi-instance host silently
  bypasses profile mode. Leave it unset unless you are
  intentionally pinning the legacy single-instance home.
- `--api-key` and `--api-key-env` are mutually exclusive on the
  server side. The CLI / Web UI now translates the form
  automatically; older commits of `control/setup` may still trip
  the server-side guard if a user pastes into both fields
  simultaneously. In that case, clear one of the fields and save
  again.
- The first `opensquilla` install on a fresh Windows host needs
  the Microsoft Visual C++ Redistributable 2015-2022 (x64) for
  the bundled ONNX router. `install_source.ps1` installs it
  automatically via `winget`; on a host without winget the
  operator has to install it manually.
- The per-profile autostart task name is `OpenSquilla_<profile>`.
  `Unregister-ScheduledTask -TaskName "OpenSquilla_<profile>"`
  / `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.opensquilla.<profile>.plist` /
  `systemctl --user disable --now opensquilla-<profile>.service`
  removes the per-profile entry. The legacy
  `OpenSquillaProfileSupervisor` task from
  `install-autostart.ps1` is a separate, single-task entry and is
  not affected.

## When NOT to use this skill

- Single-agent install on one host, no need for per-profile
  isolation — point the operator at the default install path.
- Operator wants to migrate an existing single-instance
  deployment to multi-instance — that is `paths.py`'s
  `maybe_migrate_legacy_home()` which runs automatically on the
  first call to `default_opensquilla_home()` after they set
  `OPENSQUILLA_HOME`; no CLI flag required.
- The operator only needs a one-off web search / document
  generation / file reading — that is `deep-research` /
  `text-file-read` / `docx` / `pdf-toolkit`, not this skill.
