# Trusted Sandbox Development Recovery Design

Date: 2026-06-09

## Summary

OpenSquilla should make ordinary development workflows work smoothly inside
Trusted Sandbox without turning Trusted Sandbox into Full Host Access. The
current behavior depends too heavily on static command matching. When a command
is not recognized as a package install or network operation, the sandboxed shell
fails with ordinary output and the model may improvise offline workarounds such
as downloading tarballs through web tools. That makes dependency installation
slow, brittle, and hard to reason about.

This design replaces "enumerate every install command" as the primary strategy
with three cooperating layers:

- static capability profiling for common development operations;
- a centralized policy matrix for auto, ask, and deny decisions;
- runtime recovery that handles safe missed cases by granting temporary sandbox
  permissions and retrying once.

The model should not be responsible for inventing recovery paths after common
sandbox denials. The runtime should produce structured recovery behavior.

## Goals

- Keep development dependency workflows in sandboxed execution.
- Automatically support common project setup, environment creation, dependency
  installation, build, and verification commands in Trusted Sandbox.
- Avoid relying on a complete list of Python, Node, Rust, Go, Java, PHP, or
  future package-management command spellings.
- Make Standard mode ask for new path or network grants instead of auto
  granting them.
- Keep Full Host Access as the only mode that executes directly on the host.
- Prevent automatic access to sensitive paths, credentials, local/private
  networks, link-local addresses, and metadata endpoints.
- Stop model-facing hints from recommending separate web download tools for
  dependency installation unless the user explicitly requests offline handling.

## Non-Goals

- Do not introduce a separate "install dependencies" tool as the main solution.
- Do not auto-allow system package manager operations such as `apt install`,
  `dnf install`, or `brew install`.
- Do not persist Trusted auto grants as broad global permissions by default.
- Do not allow unbounded retry loops. Runtime recovery retries at most once for
  a given failure class and command fingerprint.
- Do not make Trusted Sandbox equivalent to Full Host Access.

## Current State

The current implementation has these useful pieces:

- `OperationProfile` classifies commands such as `pip install`, `npm install`,
  `cargo build`, and `go mod download`.
- Shell and code execution pass `LevelHints(needs_network=True)` into the
  sandbox policy when static profiling detects network need.
- Policy can select `NetworkMode.PROXY_ALLOWLIST`.
- `preflight_subprocess_managed_network()` can return `sandbox_network`
  approvals for explicit domains or package bundles.
- Trusted mode can add package bundle grants automatically before the managed
  proxy starts.
- The managed network proxy injects `HTTP_PROXY`, `HTTPS_PROXY`, and related
  environment into subprocess sandbox requests.

The current gap is that static profiling is treated as the primary way to enter
the managed-network path. When a command is missed, the runtime returns ordinary
failure text to the model. The model then chooses its own workaround, which can
be slow or policy-inconsistent.

## Design Overview

### 1. Capability Profile

Introduce a capability-oriented profile that describes what the command is
trying to do, independently of the exact tool spelling.

Suggested fields:

```text
capabilities: set[Capability]
package_ecosystem: optional ecosystem id
network_intent: optional network intent
read_paths: tuple[path]
write_paths: tuple[path]
may_run_build_scripts: bool
sensitive_path_touch: bool
confidence: high | medium | low
evidence: tuple[string]
```

Suggested capability values:

```text
create_project_dir
create_env
install_packages
run_build_scripts
verify_import_or_build
fetch_source
extract_archive
```

Suggested network intents:

```text
package_registry
source_fetch
explicit_public_url
unknown_public
private_or_local
metadata_or_link_local
```

`OperationProfile` can remain as the static parser, but its output should map
into `CapabilityProfile`. Existing callers can migrate gradually.

### 2. Static Operation Profiling

Static profiling remains valuable because it lets common commands take the
right sandbox path before they fail. It should cover common ecosystems, but it
must not be the only correctness mechanism.

Initial static coverage should include:

```text
Python:
  python -m venv
  virtualenv
  pip install
  python -m pip install
  uv venv
  uv pip install
  poetry install
  hatch env / hatch run patterns
  rye sync
  pixi install

Node:
  npm install
  npm ci
  pnpm install
  pnpm add
  yarn install
  yarn add
  bun install
  bun add

Rust:
  cargo build
  cargo test
  cargo install
  cargo fetch

Go:
  go mod download
  go mod tidy
  go get
  go install

Java:
  mvn dependency:resolve
  mvn package
  gradle build
  ./gradlew build

PHP:
  composer install
  composer update

Source fetch:
  git clone
  git fetch
  curl/wget/httpie URL
  tar/unzip into a project path
```

The parser should also handle common shell wrappers and composition:

```text
timeout 30 <command>
sh -lc '<command>'
bash -lc '<command>'
VAR=value <command>
mkdir ... && <install command>
source venv/bin/activate && pip install ...
```

When a command includes multiple operations, the resulting profile should merge
capabilities and path/network needs instead of returning only the first match.

### 3. Policy Matrix

Move auto, ask, and deny decisions into a centralized policy matrix. This
matrix should consume:

- run mode;
- capability profile;
- path classification;
- network target classification;
- whether the operation may run build scripts;
- whether the target is already covered by run-context grants.

Recommended decisions:

```text
Mode      Capability          Target                         Decision
Trusted   dev capability      normal path                    auto temporary rw grant
Trusted   install_packages    known package registry          auto managed proxy
Trusted   dev capability      unknown public host             auto managed proxy + record
Trusted   any                 sensitive/system path           deny or ask
Trusted   any                 localhost/private/link-local    deny or ask
Standard  new path/domain     any                            approval_required
Full      any                 any                            host execution
```

The matrix should be implemented as a small explicit module rather than
scattered through shell, integration, and path validation code.

### 4. Path Classification

Path classification should distinguish normal user/project paths from sensitive
or system paths. Trusted mode should not be limited to workspace and `/tmp`, but
auto recovery must still avoid sensitive areas.

Suggested path classes:

```text
safe_auto:
  configured workspace
  session scratch directory
  /tmp and OS temp directories
  ordinary paths owned by the current user
  ordinary project/data paths on non-system volumes

ask:
  paths outside workspace where ownership or intent is unclear
  shared project directories not owned by the current user
  global package/cache directories that are not obviously safe

deny:
  /etc
  /usr
  /bin
  /sbin
  /var/lib
  ~/.ssh
  ~/.gnupg
  ~/.aws
  credential stores
  token/config secret directories
  Windows system directories such as C:\Windows and Program Files
```

Trusted automatic grants should be temporary and scoped to the current command
or current session. They should not become broad persistent writable mounts.

### 5. Network Classification

Network classification should preserve the managed-proxy boundary. Trusted
automatic network recovery should still run through the proxy and should not
become host networking.

Suggested network classes:

```text
known_package_registry:
  PyPI
  npm registry
  crates.io
  Go proxy and sumdb
  Maven Central / Gradle plugin portal
  Packagist

source_fetch:
  GitHub
  GitLab
  common public source archive hosts

unknown_public:
  public routable host not currently in a bundle

deny_or_ask:
  localhost
  private RFC1918 ranges
  link-local
  cloud metadata endpoints
  credential/token endpoints
```

Trusted mode may auto allow `unknown_public` only when it is tied to a
development capability and remains behind the managed proxy. The proxy should
continue to block unsafe resolved addresses even when the host name looks
public.

### 6. Runtime Recovery

Runtime recovery is the primary completeness mechanism.

When sandbox execution fails, the runtime should inspect structured backend
notes and stderr/stdout patterns for:

```text
path denied
write denied
network disabled
DNS failure
proxy denied
connection blocked
package registry blocked
```

If the failure is eligible under the policy matrix:

- Trusted mode auto grants the needed temporary path or network permission and
  retries the original command once.
- Standard mode returns structured approval payloads such as `sandbox_network`
  or path access approval.
- Deny-class targets return a structured denial with a clear reason.

Runtime recovery should not ask the model to choose a workaround. Tool results
should be structured enough for the agent loop to retry the same command with
the new grant or approval id.

### 7. Model-Facing Guidance

The model-facing hint for sandbox network failure should say:

- shell/code has no direct network;
- use sandbox managed-network approval or Trusted managed-network recovery;
- retry the same shell command through the managed proxy;
- do not switch to separate web download tools for package installs unless the
  user explicitly asks for offline handling.

The hint should not name web download tools as the recommended recovery path.

## Data Flow

### Static Success Path

```text
exec_command
  -> parse command into CapabilityProfile
  -> policy matrix decides network/path needs
  -> Trusted auto grants or Standard approval preflight
  -> run sandbox subprocess with managed proxy/mounts
  -> return normal output
```

### Runtime Recovery Path

```text
exec_command
  -> static profile misses a tool
  -> sandbox subprocess fails with network/path denial
  -> runtime classifies failure
  -> policy matrix decides auto/ask/deny
  -> Trusted auto grant + retry once, or Standard approval payload
  -> return retried output or structured denial
```

### Deny Path

```text
exec_command
  -> target path or network is sensitive
  -> policy matrix returns deny or ask
  -> no host fallback
  -> return structured denial or approval requirement
```

## Testing Strategy

Unit tests:

- Capability profiles for common ecosystems.
- Shell wrapper parsing for `timeout`, `sh -lc`, activation chains, and
  composed commands.
- Policy matrix decisions for mode/capability/path/network combinations.
- Path classification for workspace, temp, ordinary user paths, and sensitive
  paths.
- Network classification for registries, public hosts, private hosts, metadata,
  and localhost.

Integration tests:

- Trusted package install receives managed proxy without prompting.
- Standard package install returns `sandbox_network` approval before execution.
- Unknown install tool that fails with DNS/proxy denial is retried once in
  Trusted mode through managed proxy.
- Ordinary user path denied by initial sandbox mount is auto granted and retried
  once in Trusted mode.
- Sensitive path denial is not auto granted.
- Private/link-local/metadata network target is not auto granted.
- Runtime recovery does not loop after a failed retry.

Regression tests:

- The network hint does not recommend separate web download tools for package
  installs.
- Full Host Access remains the only mode that runs directly on the host.
- Existing explicit approvals still work in Standard mode.

## Rollout Plan

Phase 1:

- Introduce `CapabilityProfile` and adapter functions from current
  `OperationProfile`.
- Add policy-matrix module with tests.
- Keep existing behavior while routing current profile decisions through the
  matrix.

Phase 2:

- Add runtime recovery for subprocess network denials.
- Ensure Trusted auto grants managed network and retries once.
- Ensure Standard returns structured approvals.

Phase 3:

- Add runtime recovery for path denials.
- Support ordinary user/project paths beyond workspace and `/tmp`.
- Keep sensitive paths deny/ask.

Phase 4:

- Broaden static ecosystem recognition.
- Update model-facing hints and prompts.
- Add telemetry for auto grants, asks, denials, and recovery retries.

## Design Decisions

- Trusted `unknown_public + dev capability` auto allows behind the managed
  proxy, records the grant decision, and never switches to host networking.
- Ordinary user paths are classified by ownership plus a sensitive/system
  denylist in the first version. Project markers such as `.git`,
  `pyproject.toml`, `package.json`, and `Cargo.toml` may raise confidence but
  are not required for auto recovery.
- Runtime recovery auto grants are command-scoped and retry the command once.
  Explicit Trusted package bundles may remain session-scoped because they are
  already tied to known package-registry domains.

## Acceptance Criteria

- Trusted Sandbox can install dependencies for common Python, Node, Rust, Go,
  Java, and PHP project workflows without direct host execution.
- A missed package manager can still recover from a network denial through the
  managed proxy without model-invented offline download steps.
- Ordinary non-sensitive user/project paths can be auto granted in Trusted
  mode.
- Sensitive/system paths and unsafe network targets are not auto granted.
- Standard mode still asks for new path/domain/package grants.
- Full Host Access remains explicit host execution.
- Recovery retries at most once for the same command/failure.
- Tests cover static classification, policy matrix decisions, and runtime
  recovery behavior.
