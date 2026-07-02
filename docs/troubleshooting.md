# Troubleshooting

Start with:

```sh
opensquilla doctor
opensquilla doctor --json
opensquilla gateway status
```

The Web UI health view at <http://127.0.0.1:18791/control/> also reports
readiness and recovery steps when the gateway is running.

## `opensquilla` Command Not Found

After `uv tool install`, open a new terminal or run:

```sh
uv tool update-shell
```

Check the executable:

```sh
command -v opensquilla
```

On Windows PowerShell:

```powershell
where.exe opensquilla
```

## Gateway Is Not Running

Start it:

```sh
opensquilla gateway run
```

Or use the managed background process:

```sh
opensquilla gateway start --json
opensquilla gateway status
```

Open:

```text
http://127.0.0.1:18791/control/
```

For a focused gateway guide, see [`gateway.md`](gateway.md).

## Desktop Gateway Startup Reports a Migration Lock

During first run, the desktop app starts a local gateway and applies pending
SQLite migrations before opening the Control UI. If startup is interrupted, the
gateway may report a yoyo migration lock for `sessions.db`.

Recent versions recover automatically when the lock row points only to dead or
invalid process ids. The gateway keeps the migration failure loud and does not
clear the lock when any recorded pid is still alive.

Check the desktop gateway log for these events:

```text
migrator.lock_timeout
migrator.stale_lock_cleared
migrator.lock_held_by_live_process
migrator.stale_lock_retry_failed
```

If the log says the lock is held by a live process, wait for that gateway to
finish starting or stop the process cleanly. Do not remove `yoyo_lock` rows or
run yoyo break-lock unless you have verified the recorded process is no longer
running.

## Port Already In Use

Use another port:

```sh
opensquilla gateway run --port 18792
```

Or stop the managed gateway:

```sh
opensquilla gateway stop
```

## Provider Not Configured

Run:

```sh
opensquilla onboard
opensquilla providers list
opensquilla providers configure openrouter
```

Use environment-variable secrets:

```sh
export OPENAI_API_KEY="sk-..."
opensquilla configure provider --provider openai --api-key-env OPENAI_API_KEY
```

## Router Dependency Problems

If SquillaRouter cannot load, OpenSquilla can still run with direct model
routing. To disable the router:

```sh
opensquilla configure router --router disabled
opensquilla gateway restart
```

On Windows, ONNX Runtime may need the Visual C++ Redistributable for Visual
Studio 2015-2022 x64. Install it, then restart the shell and gateway.

On macOS terminal installs, LightGBM may need the system OpenMP runtime. If
startup logs `Library not loaded: @rpath/libomp.dylib` from
`lightgbm/lib/lib_lightgbm.dylib`, install it and restart the gateway:

```sh
brew install libomp
opensquilla gateway restart
```

The desktop app bundles the native runtime it needs; this recovery step
is for terminal or source installs.

## Search Does Not Work

Inspect search providers:

```sh
opensquilla search list
opensquilla search status
```

Use DuckDuckGo for a no-key path:

```sh
opensquilla configure search --search-provider duckduckgo
```

Use Brave with a key:

```sh
export BRAVE_SEARCH_API_KEY="..."
opensquilla configure search --search-provider brave --api-key-env BRAVE_SEARCH_API_KEY
```

Use Bocha, Tavily, or Exa when your workflow needs freshness or richer source
content:

```sh
export BOCHA_SEARCH_API_KEY="..."
opensquilla configure search --search-provider bocha --api-key-env BOCHA_SEARCH_API_KEY

export TAVILY_API_KEY="..."
opensquilla configure search --search-provider tavily --api-key-env TAVILY_API_KEY

export EXA_API_KEY="..."
opensquilla configure search --search-provider exa --api-key-env EXA_API_KEY
```

For no-key, partial-key, or all-key setups, inspect the effective runtime state:

```sh
opensquilla search status --json
```

## Channel Config Saved but Channel Is Offline

Restart the gateway after editing channel config:

```sh
opensquilla gateway restart
opensquilla channels status <name> --json
```

For webhook channels, confirm the gateway is reachable from the provider and
that callback secrets match.

## A Tool Was Denied

Check sandbox and permission state:

```sh
opensquilla sandbox status
opensquilla doctor
```

For one-shot runs, choose an explicit permission posture:

```sh
opensquilla agent --permissions restricted -m "Read only"
opensquilla agent --permissions full -m "Trusted local automation"
```

## The Agent Seems to Forget Old Context

Long sessions may compact old history. This is expected under context pressure.

Inspect sessions:

```sh
opensquilla sessions show <session-key>
opensquilla sessions export <session-key>
```

If exact old text matters, keep it in a file, memory note, or exported session.

## A Turn Is Too Expensive or Too Slow

Try:

```sh
opensquilla configure router --router recommended
opensquilla diagnostics on
opensquilla cost
```

For automation:

```sh
opensquilla agent --max-iterations 20 --timeout 600 -m "Bounded task"
```

For large tool outputs, see
[`features/tool-compression.md`](features/tool-compression.md).

---

[Docs index](README.md) · [Product guide](../README.product.md) · [Improve this page](contributing-docs.md) · [Report a docs issue](https://github.com/opensquilla/opensquilla/issues/new?template=docs_report.yml)
