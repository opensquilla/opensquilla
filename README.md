# OpenSquilla — Token-Efficient AI Agent

<p align="center">
  <img src="assets/opensquilla-long-logo.png" alt="OpenSquilla logo" width="500">
</p>

<p align="center">
  <a href="https://opensquilla.ai/"><img src="https://img.shields.io/badge/website-opensquilla.ai-blue?style=for-the-badge" alt="Website"></a>
  <a href="https://github.com/opensquilla/opensquilla/releases"><img src="https://img.shields.io/github/v/release/opensquilla/opensquilla?include_prereleases&style=for-the-badge" alt="GitHub release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg?style=for-the-badge" alt="Apache 2.0 License"></a>
</p>

## Overview

OpenSquilla is a token-efficient, microkernel AI agent — same budget,
more capability, better results. It combines smart routing, persistent
memory, a secure sandbox, built-in web search, and local embeddings
under a single model loop.
Every entry point — Web UI, CLI, and chat channels — runs through a
shared `TurnRunner`, and a pluggable provider layer lets it speak to
OpenRouter, OpenAI, Anthropic, Ollama, DeepSeek, Gemini, Qwen/DashScope,
and roughly twenty other LLM providers without changes to your code or
config schema.

## Quick start

Choose the path that matches how you want to use OpenSquilla:

| User type | Path | Status |
| --- | --- | --- |
| New user | [Release package](#release-package-coming-soon) | Coming soon |
| Command-line user | [Install from source](#install-from-source) | Available now |
| Developer | [Develop from source](#develop-from-source) | Available now |

SquillaRouter is included by default in every currently available install path.
Only choose the `core` profile or `--router disabled` if you intentionally want
to skip the bundled router.

### Release package — coming soon

This will be the recommended path for non-developers: download a release
package, extract it, set an API key, start OpenSquilla, and open the Web UI.
Public release packages are not published yet. Until release packages are
published, new users should use Install from source.

### Install from source

Use this path when you want to run OpenSquilla as a local app from the current
source tree. The clone is only the package source the installer reads from; after
installing, use `opensquilla ...` commands, not `uv run`.

1. Install prerequisites: Git, Git LFS, and uv.

   Download links:
   - Git: <https://git-scm.com/downloads>
   - Git LFS: <https://git-lfs.com/>
   - uv: <https://docs.astral.sh/uv/getting-started/installation/>

   <details>
   <summary>Optional: install prerequisites from a terminal</summary>

   Windows PowerShell:

   ```powershell
   winget install --id Git.Git -e
   winget install --id GitHub.GitLFS -e
   powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
   git lfs install
   ```

   macOS, if you already use Homebrew:

   ```sh
   brew install git git-lfs uv
   git lfs install
   ```

   Homebrew is optional: <https://brew.sh/>. If you do not use Homebrew, use the
   download links above.

   Debian / Ubuntu:

   ```sh
   sudo apt update
   sudo apt install -y git git-lfs
   curl -LsSf https://astral.sh/uv/install.sh | sh
   git lfs install
   ```

   Fedora:

   ```sh
   sudo dnf install -y git git-lfs
   curl -LsSf https://astral.sh/uv/install.sh | sh
   git lfs install
   ```

   Arch:

   ```sh
   sudo pacman -S --needed git git-lfs
   curl -LsSf https://astral.sh/uv/install.sh | sh
   git lfs install
   ```

   Open a new terminal if `git`, `git lfs`, or `uv` is not found after
   installation.

   </details>

2. Clone with LFS assets:

   ```sh
   git lfs install
   git clone https://github.com/opensquilla/opensquilla.git
   cd opensquilla
   git lfs pull --include="src/opensquilla/squilla_router/models/**"
   ```

3. Install with the recommended profile. This creates a user-local
   `opensquilla` command. The checkout-local `.venv`, if any, is not used.
   The normal install commands above already install SquillaRouter.

   macOS / Linux:

   ```sh
   bash install.sh
   ```

   Windows PowerShell:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\install.ps1
   ```

   PowerShell 7 users can run `pwsh -ExecutionPolicy Bypass -File .\install.ps1`.

   Optional: add a channel adapter only if you need one. For example, add
   Feishu websocket channel support with these full install commands:

   Windows PowerShell:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\install.ps1 -Extras feishu
   ```

   macOS / Linux:

   ```sh
   OPENSQUILLA_INSTALL_EXTRAS=feishu bash install.sh
   ```

   Only set `OPENSQUILLA_INSTALL_PROFILE=core` if you intentionally want
   to skip the bundled router.

   Open a new terminal if `opensquilla` is not found after installation.

4. Configure. Use the installed `opensquilla` command below. Do not prefix
   these commands with `uv run` unless you chose **Develop from source**.

   Recommended for beginners:

   ```sh
   opensquilla onboard
   ```

   The wizard asks you to choose a provider and enter or reference its API key.

   For automation, this OpenRouter example is copy-pasteable. If you choose
   OpenRouter, create a key at <https://openrouter.ai/docs/api-keys>, then
   replace `sk-...` with the real key value. The `export` and `$env:` examples
   below set the key for the current terminal only.
   OpenRouter is only an example; substitute any supported provider and its API
   key variable.

   macOS / Linux:

   ```sh
   export OPENROUTER_API_KEY="sk-..."
   opensquilla onboard --provider openrouter --api-key-env OPENROUTER_API_KEY
   ```

   Windows PowerShell:

   ```powershell
   $env:OPENROUTER_API_KEY="sk-..."
   opensquilla onboard --provider openrouter --api-key-env OPENROUTER_API_KEY
   ```

5. Run the gateway:

   ```sh
   opensquilla gateway run
   ```

Wait until the gateway says it is running before opening the Web UI at
<http://127.0.0.1:18790/control/>. Press `Ctrl+C` to stop the foreground
gateway. If Windows lacks the Visual C++ Redistributable, the gateway still
starts but the bundled router falls back to a safe direct route. If Windows
prints an `onnxruntime` or `DLL load failed` warning, see the Visual C++ runtime
note in [Prerequisites](#prerequisites).

## Setup details and troubleshooting

Setup details expands the Quick start paths; it is not a separate install path.
Use Install from source when you only want to run OpenSquilla. Use Develop from
source only when you want to edit, test, or debug the code.

Sections marked **(optional)** can be skipped depending on your environment;
everything else is required for a working source install.

### Prerequisites

- **Python 3.12+** — required only when you skip `uv` and use the `pip --user`
  fallback, or when you develop from source. **(optional)** for portable-zip
  users, since the release zip already bundles its own CPython.
- **Git and Git LFS** — required. The bundled SquillaRouter assets are
  stored as LFS pointers; without `git-lfs` the `recommended` profile
  fails with `version https://git-lfs.github.com/spec/v1` pointer files
  in place of the model bytes. Install once: <https://git-lfs.com/>.
- **`uv`** — recommended for normal source installs. The installer scripts use
  `uv tool install` when available. Install once: <https://docs.astral.sh/uv/>.
- **`pip` >= 23** — fallback only when `uv` is unavailable. The scripts fall
  back to `python -m pip install --user`.
- **Windows Visual C++ runtime** — recommended when using the bundled router
  on Windows. `install.ps1` tries to install the Microsoft Visual C++
  Redistributable for Visual Studio 2015-2022 (x64) with `winget` when it is
  missing. If startup still prints `DLL load failed while importing
  onnxruntime_pybind11_state`, install it manually, then restart PowerShell:
  <https://aka.ms/vs/17/release/vc_redist.x64.exe>. If `winget` is not present,
  download and run the Visual C++ installer manually. If you need to run while
  fixing the runtime, use the `--router disabled --minimal` workaround in
  [First-run config](#first-run-config).

### Clone the repo

```sh
git lfs install
git clone https://github.com/opensquilla/opensquilla.git
cd opensquilla
git lfs pull --include="src/opensquilla/squilla_router/models/**"
```

`git lfs install` is idempotent and safe to run again.

### Install from source (detailed)

Use this path when you want to run OpenSquilla, not edit its source.
The clone is only the package source for the installer. After install,
use `opensquilla ...`; do not use `uv run`.

The scripts install `.[recommended]` by default. `recommended` is the
normal runtime profile: SquillaRouter, memory, and local model dependencies.
Messaging channel adapters are opt-in extras. Most users do not need
every chat platform SDK.

The install scripts default to the `recommended` profile, which installs
`.[recommended]`. That path includes SquillaRouter dependencies and checks the
bundled router model assets before installing. The only normal opt-out is the
`core` profile.

macOS / Linux:

```sh
bash install.sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

PowerShell 7 users can run `pwsh -ExecutionPolicy Bypass -File .\install.ps1`.

Install channel extras into the same user-local command. Feishu is shown only
as an example channel adapter:

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Extras feishu
```

macOS/Linux:

```sh
OPENSQUILLA_INSTALL_EXTRAS=feishu bash install.sh
```

Supported channel extras include `dingtalk`, `feishu`, `matrix`, `matrix-e2e`,
`msteams`, `qq`, `telegram`, and `wecom`. The optional non-channel extra is
`document-extras`.

The scripts prefer `uv tool install` and fall back to
`python -m pip install --user`. The installed command uses its own
Python environment; it is separate from a checkout-local `.venv`.

Useful install options:

```powershell
$env:OPENSQUILLA_INSTALL_PROFILE="core"          # minimal runtime
$env:OPENSQUILLA_INSTALL_DRY_RUN="1"             # print the plan only
```

```sh
OPENSQUILLA_INSTALL_PROFILE=core bash install.sh
OPENSQUILLA_INSTALL_DRY_RUN=1 bash install.sh
```

To check which command your shell will run:

```powershell
where.exe opensquilla
```

```sh
command -v opensquilla
```

If a new terminal still cannot find it, run `uv tool update-shell`, reopen the
terminal, and try again.

After reinstalling from a local checkout, restart the gateway process so it
loads the updated package.

### Develop from source

Use this path only when you want to modify, test, or debug the current
checkout. `uv sync` creates the checkout-local `.venv`, and `uv run`
executes against the live source tree.

```sh
uv sync --extra recommended
uv run opensquilla --help
```

The `recommended` extra includes SquillaRouter for development too. Use
`uv sync` without `--extra recommended` only when you are intentionally testing
a minimal environment.

Install extras into the same environment you run:

```sh
uv sync --extra recommended --extra feishu
uv run opensquilla channels status feishu --json
```

In this mode, prefix every command below with `uv run`. Do not debug a
development checkout through a user-local `opensquilla` command; that
command runs in a different Python environment.

### First-run config

`opensquilla onboard --if-needed` is the recommended post-install
entrypoint for first-run setup and automation. It writes the active
config file, skips when an LLM provider is already configured, and keeps
provider secrets in environment variables when you pass `--api-key-env`.
The router defaults to `recommended`; `recommended` enables SquillaRouter for
supported provider profiles. Pass `--router disabled` only if you
intentionally want direct single-model routing, or `--router
openrouter-mix` to keep the built-in OpenRouter mixed model routes.
Useful invocations:

```sh
opensquilla onboard                # full interactive wizard
opensquilla onboard --if-needed    # idempotent: skip if already configured
opensquilla onboard --minimal      # provider only, skip channels/search
```

In SSH, CI, or any environment without a TTY the interactive flow
exits with code 2. Use the non-interactive form — keep the secret in
the environment and pass its **name**, not its value, to onboard:

```sh
export OPENROUTER_API_KEY="sk-..."
opensquilla onboard \
  --provider openrouter \
  --api-key-env OPENROUTER_API_KEY
```

For example, with OpenAI:

```sh
export OPENAI_API_KEY="sk-..."
opensquilla onboard --provider openai --api-key-env OPENAI_API_KEY
```

To persist the key on macOS or Linux, add the same `export` line to your shell
profile.

Windows PowerShell:

```powershell
$env:OPENROUTER_API_KEY="sk-..."
opensquilla onboard --provider openrouter --api-key-env OPENROUTER_API_KEY
```

To persist the key for future PowerShell windows:

```powershell
setx OPENROUTER_API_KEY "sk-..."
```

Close and reopen PowerShell after `setx`, then run:

```powershell
opensquilla onboard --provider openrouter --api-key-env OPENROUTER_API_KEY
```

If a Windows machine cannot initialize `onnxruntime` and logs
`DLL load failed while importing onnxruntime_pybind11_state`, OpenSquilla will
keep running with a safe router fallback, but the bundled router runtime is not
active until the Visual C++ runtime is fixed. To make a first install quiet and
direct while fixing the Windows runtime, use:

```powershell
$env:OPENROUTER_API_KEY="sk-..."
opensquilla onboard --provider openrouter --api-key-env OPENROUTER_API_KEY --router disabled --minimal
opensquilla gateway run
```

After installing the Visual C++ Redistributable and reopening PowerShell, restore
the recommended router. If you used only `$env:OPENROUTER_API_KEY`, set it again
in the new PowerShell window.

```powershell
opensquilla onboard --provider openrouter --api-key-env OPENROUTER_API_KEY --router recommended
opensquilla gateway restart
```

**(optional)** Re-configure one section later without redoing the whole
wizard:

```sh
opensquilla configure provider --provider openai --model gpt-4o
opensquilla configure router --router recommended
opensquilla configure search   --search-provider brave
opensquilla configure channels                # interactive section
```

Sections: `provider`, `router`, `channels`, `search`,
`image-generation`, `memory-embedding`. The Web UI also exposes a setup
flow at `/control/setup` for provider, router tiers, optional channels,
and extras. Later CLI edits should use `opensquilla configure
<section>` rather than provider-specific aliases.

Messaging channel saves are config changes, not runtime connectivity
proof. Restart the gateway process after channel edits, then verify the
live adapter state:

```sh
opensquilla gateway restart
opensquilla channels status <name> --json
```

Treat a channel as connected only when the status payload reports
`enabled=true`, `configured=true`, and `connected=true`. Feishu defaults
to websocket mode and does not need a public URL in that mode; Feishu
webhook mode, Slack, WeCom, and Microsoft Teams require a public
provider-reachable URL.

**Config load order:** `OPENSQUILLA_GATEWAY_CONFIG_PATH` →
`./opensquilla.toml` → `~/.opensquilla/config.toml` → built-in
defaults. Onboarding writes the file at the path the runtime would
read; environment values for individual secrets always win over file
values.

### Run

```sh
opensquilla gateway run                   # foreground, 127.0.0.1:18790
opensquilla gateway start --json          # background + health wait
opensquilla chat                          # interactive REPL
opensquilla agent -m "your prompt"        # one-shot, automation-friendly
```

Open the Web UI at <http://127.0.0.1:18790/control/> and check health
with `curl http://127.0.0.1:18790/health`.

### Public network binding — (optional)

To make the Web UI reachable from another machine, bind the gateway to
all interfaces and use the host's public IP address:

```sh
opensquilla gateway run --listen 0.0.0.0 --port 18790
# or, for a background process:
opensquilla gateway start --listen 0.0.0.0 --port 18790 --json
```

Then open `http://<public-ip>:18790/control/` and verify the public
health endpoint with:

```sh
curl http://<public-ip>:18790/health
```

If another gateway is already bound to `18790`, stop it first or choose
a different `--port`. Public access also requires the host firewall or
cloud security group to allow inbound TCP traffic on that port.
Do not expose the gateway publicly with `[auth] mode = "none"`; configure
token or password auth before binding to `0.0.0.0`.

### Docker and portable paths — (optional)

`./start.sh` (or `start.ps1` on Windows) wraps `docker compose up -d`
and tails the gateway logs — convenient if you do not want a Python
toolchain on the host. Release zips that bundle a CPython runtime are
produced by the `Wheelhouse Zip Release` workflow; portable users
extract the zip and run its bundled launcher without a system Python
install.

### Further tuning

Provider-specific config, tier profiles, sandbox tuning, image
generation, and concurrency settings are managed through
`opensquilla onboard`, `opensquilla config`, and
`opensquilla.toml.example`.

## Benchmark Results

PinchBench 1.2.1 average results across 25 tasks:

| Agent | Base Model | Avg. score | Total input tokens | Total output tokens | Total cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| OpenSquilla | Model router (Opus4.7, GLM5.1, DS4 Flash) | 0.9251 | 1,721,328 | 61,475 | $0.688 |
| OpenClaw | Claude Opus 4.7 | 0.9255 | 3,066,243 | 50,890 | $6.233 |

## Key Features

- **Token-efficient routing** — local `SquillaRouter` (LightGBM + ONNX
  BGE classifier, `recommended` extra) routes each turn across four
  tiers (T0–T3). Hybrid features (length, language, code blocks,
  keywords + semantic embeddings) pick the cheapest model that can
  handle the turn; classification runs on-device, so your prompt never
  leaves the machine to make the decision.
- **Adaptive reasoning and prompts** — reasoning-token billing only
  kicks in when the turn needs deep thought, and the system prompt
  scales with task complexity (lightweight for trivial turns, full
  instructions for complex ones). No paying reasoning tokens for "hello".
- **On-demand skills** — built-in MCP client plus 16
  bundled skills (coding agents, GitHub, cron, deep research,
  pptx/docx/xlsx/pdf toolkits, summarization, tmux, weather, and more);
  only the skills needed for the current task are loaded into context,
  avoiding steady-state token waste.
- **Four-tier cognitive memory** — working (current task) → episodic
  (experience and causality) → semantic (facts and rules) → raw (audit
  and retraining base), mirroring human cognition.
- **Hybrid memory search + local embeddings** — Markdown source-of-truth
  memory with FTS keyword search alongside `sqlite-vec` semantic recall.
  Bundled ONNX inference runs on CPU so embeddings stay on your machine;
  optionally swap to OpenAI- or Ollama-hosted embeddings.
- **Adaptive recall and consolidation** — frequently used memories
  auto-promote and dated ones decay exponentially (with an "evergreen"
  opt-out); periodic Dream consolidation merges scattered episodic
  traces into structured knowledge, mirroring sleep consolidation, with
  bounded prompt-injection budgets throughout.
- **Layered security sandbox** — three policy tiers (Standard / Strict
  / Locked) on a permission-tier matrix, with Bubblewrap on Linux
  executing code in isolated environments (the macOS Seatbelt backend
  currently renders SBPL profiles only; process execution is pending).
  A denial ledger auto-pauses autonomous execution after repeated
  sandbox denials, rejected outputs are purged via intent + stale-output
  caches so the agent can't recover them through a side channel, and
  all skill metadata and tool results are XML-escaped to close common
  prompt-injection vectors.
- **Unified gateway across all entry points** — Starlette ASGI server on
  `127.0.0.1:18790` with WebSocket RPC and an embedded control console
  (`/control/`). Web UI, CLI, and first-class adapters for Terminal,
  WebSocket, Slack, Telegram, Discord, Feishu, DingTalk, WeCom, MS
  Teams, Matrix, and QQ all converge on a shared `TurnRunner` for
  consistent tool dispatch, retry, and decision logging.
- **20+ LLM providers** — OpenRouter, OpenAI, Anthropic, Ollama,
  DeepSeek, Gemini, DashScope/Qwen, Moonshot, Mistral, Groq, Zhipu,
  SiliconFlow, Volcengine, BytePlus, MiniMax, vLLM, LM Studio, OVMS, and
  more, with a primary-plus-fallback selector.
- **Durable sessions, agents, and scheduling** — SQLite-backed session,
  transcript, and replay storage with per-agent workspaces and a
  `reset`/flush contract that proves persistence before destructive
  rewrites; `SchedulerEngine` with an in-tree `CronExpression` parser
  plus stagger, reaper, and heartbeat services exposed via the
  `opensquilla cron` CLI.

## Credits

OpenSquilla is a token-efficient AI Agent inspired by
[OpenClaw](https://github.com/openclaw/openclaw). Bundled third-party content is fully attributed
in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Contributing

OpenSquilla is an open-source project and we welcome contributions of
every kind — bug reports, feature ideas, documentation, new provider or
channel adapters, skills, and core runtime work. Open an issue or a
pull request on [GitHub](https://github.com/opensquilla/opensquilla)
to get involved.
