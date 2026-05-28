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
