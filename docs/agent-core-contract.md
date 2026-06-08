# Agent Core Contract

This contract defines the boundary for selectable OpenSquilla agent kernels.
The current Python agent remains the default kernel. A Pi-backed kernel can be
added behind the same runtime boundary without changing CLI, TUI, Web UI, or
channel event contracts.

## Goals

- Support two selectable agent kernels:
  - `opensquilla`: the existing Python `opensquilla.engine.agent.Agent`.
  - `pi`: a Pi-backed sidecar runtime that emits OpenSquilla agent-core
    protocol frames and requests host-owned effects through explicit ports.
- Preserve existing OpenSquilla behavior by default.
- Keep tool execution, approval, artifact projection, compaction persistence,
  router-control replay, usage/cost enrichment, and memory refresh owned by the
  OpenSquilla runtime unless a later contract explicitly moves them.
- Keep the public `AgentEvent` stream stable for CLI, TUI, Web UI, channels, and
  persisted session consumers.

## Non-Goals

- Do not change TUI or CLI request/response contracts.
- Do not require Pi to become the only agent implementation.
- Do not move OpenSquilla tool policy, approval, artifact, memory, routing, or
  compaction semantics into Pi.
- Do not expose Pi-specific event names directly to existing OpenSquilla
  downstream consumers.

## Kernel Boundary

An agent kernel is selected before `StreamConsumerStage` starts consuming the
turn. CLI, TUI, Web UI, and channel callers still depend on `TurnRunner` and
the public `AgentEvent` stream only; they do not select or call kernel-specific
APIs.

The selected kernel must provide a `KernelRuntime` object accepted by the
existing `AgentRunPort` boundary:

```python
run_turn(
    turn_input: str,
    *,
    extra_messages: list[Any] | None,
    semantic_message: str | None = None,
) -> AsyncIterator[AgentEvent]
```

The kernel may internally use OpenSquilla's Python agent, a Pi sidecar command,
or a future in-process implementation. Downstream runtime stages must continue
to consume only `AgentEvent`.

## Required Contract Types

The first supported agent-core contract is intentionally explicit:

- `AgentCoreConfig`: selects the kernel, declares
  `opensquilla.agent_core.v1`, configures the Pi sidecar command/client, and
  keeps host-owned provider/tool/session/orchestration/finalizer flags strict by
  default. The kernel id, protocol version, Pi sidecar command, and command or
  client provenance fields must be strings or omitted; arbitrary config objects
  are rejected instead of being coerced through `str()`. Strict-host flags must
  be booleans or explicit boolean strings; arbitrary truthy/falsy objects are
  rejected instead of being coerced through `bool()`. Test-fixture Pi
  command/client opt-ins follow the same strict boolean rule, so string
  `"false"` remains disabled and arbitrary truthy objects cannot bypass
  production provenance gates. Pi sidecar v1 rejects direct runtime
  construction unless the resolved kernel is `pi`; it also rejects disabled
  strict-host flags at runtime startup. Omitted or blank protocol versions
  resolve to the v1 protocol before any sidecar-visible turn kwargs or frame
  comparisons. Non-strict foreign kernels require a future protocol revision.
- `KernelTurnSnapshot`: host-authored turn inputs passed to a kernel, including
  session key, sidecar-visible session id, agent id, turn id, system prompt,
  request-context prompt, model id, tool definitions, extra messages, semantic
  message, and metadata. The session key and session id must be non-empty
  strings; when omitted, `session_id` defaults to the host-selected
  `session_key`. Pi sidecars may map this field to Pi `sessionId` for
  provider-cache identity, but provider execution, cache accounting, and final
  `DoneEvent` usage fields remain OpenSquilla-owned. Turn input fields must be
  strings. The derived `agent_id` and host-authored `turn_id` must be
  non-empty; if a legacy `agent:`-prefixed session key has an empty agent
  segment, the adapter falls back to the full session key for `agent_id`
  instead of exposing a blank identity to the sidecar.
  System prompt,
  request-context prompt, and model id fields must be strings or
  omitted/`None`; `semantic_message` must be a string or `None`; arbitrary host
  identity, config, turn input, or semantic message objects are rejected
  before sidecar RPC instead of being coerced through `str()`.
  `extra_messages` must be a list or `None`; history passed through
  `set_history` must be a list; tool definitions must be a list; metadata must
  be an object. A JSON object is not accepted as a substitute for list-shaped
  fields, and a JSON list is not accepted as metadata. The snapshot is
  descriptive; it does not grant side-effect authority. Snapshot collections
  and the sidecar-visible
  history/extra-message lists are adapter-owned copies so an in-process sidecar
  cannot mutate nested state back into the host turn. Sidecar-visible snapshot,
  history, extra-message, tool-definition, and metadata values must also be
  JSON-safe owned copies so in-process RPC clients cannot observe Python-only
  objects, including non-finite floating-point values such as `NaN` and
  `Infinity`, that command-backed JSONL sidecars could never receive as standard
  JSON. Python-only sidecar-visible values must fail instead of falling back to
  `str()`. JSON object keys must already be strings; the adapter rejects
  non-string keys instead of silently stringifying them. Known parity metric
  metadata such as `cache_hit_rate` must be finite probabilities in the closed
  range `0 <= x <= 1`. Pi snapshots may include a host-authored
  `metadata.host_runtime_policy` object for read-only runtime policy alignment,
  including flush and compaction-policy fields such as `flush_enabled`,
  `flush_triggers`, `flush_pre_compaction`, `flush_timeout_seconds`,
  `flush_compaction_requires_safe_receipt`, `flush_compaction_safety_mode`,
  `compaction_profile`, and `compaction_protected_recent_messages`. This
  metadata is descriptive only: provider calls, tool execution, session writes,
  compaction persistence, and final usage accounting continue to use
  OpenSquilla host config and host ports, and sidecar provider/request config
  cannot override these host-owned policy fields.
- `KernelHostPorts`: OpenSquilla-owned capabilities for provider calls, tool
  execution/projection, session writes, queue polling, savepoints,
  orchestration/yield, finalization, and telemetry.
- `KernelRuntime`: the runtime protocol consumed by `TurnRunner` stages:
  `set_history`, `refresh_system_prompt`, and `run_turn`. The OpenSquilla
  Python path is wrapped by `OpenSquillaPythonKernelRuntime`; the Pi path is
  wrapped by `PiSidecarKernelRuntime`. Direct Pi runtime construction requires
  a sidecar RPC client with callable `stream_prompt`; production command/client
  provenance remains enforced by the agent-core builder/config path. Production
  Pi runtimes constructed through the builder emit host state-change events and
  inject host runtime context for public parity. They also emit a public
  `ToolUseStartEvent` before a successful `yield.request` result so
  `sessions_yield` has the same tool start/result shape as the Python agent.
  Production Pi state changes coalesce parallel tool execution into the same
  public shape as the Python agent: one `streaming -> tool_calling` transition
  covers the batch, and a yielded turn can finish with `tool_calling -> done`
  without exposing per-tool internal thinking cycles.
  Low-level fake sidecar contract fixtures may disable that emission/injection
  so frame validation and host-port routing tests stay focused. Production Pi
  sidecars own visible provider feedback replay after `provider.request`;
  allowlisted fake sidecars may keep direct host provider events visible to test
  lifecycle cleanup without pretending to be the live Pi adapter.

Host ports are capabilities, not suggestions. A foreign kernel cannot perform a
provider call, execute a tool, write a session row, mark a savepoint, wake a
parent, or finalize a turn unless it returns that intent to an OpenSquilla port.
Pi sidecar frame `protocol`, `kind`, and `type` values must be non-empty
strings; intent frame `type` values are validated before host-port lookup, and
structured values are rejected instead of being coerced through `str()`.
Ports expose one uniform method:

```python
handle_intent(
    *,
    intent_type: str,
    payload: dict[str, Any],
    session_key: str,
) -> AgentEvent | Iterable[AgentEvent] | AsyncIterable[AgentEvent] | None
```

The returned events must already be normalized OpenSquilla `AgentEvent` values.
Adapters must accept `None`, a single event, a sync iterable, or an async
iterable, and must reject any non-`AgentEvent` host-port output before it can
reach TurnRunner. Adapters must also validate each event's `kind` literal and
public `AgentEvent` field types from host-port output before yielding those
events to CLI/TUI, so malformed custom host ports cannot smuggle structured
objects into stable text, terminal, tool, artifact, router, warning, heartbeat,
or compaction fields. `telemetry.emit` targets a host-owned non-user-facing telemetry port.
The default host telemetry port is a no-op so Pi-side lifecycle/diagnostic
telemetry cannot break a turn; deployments may replace it with a best-effort
sink that implements `handle_intent(...)`, `emit(payload)`, or a callable
payload sink. `telemetry.emit` payloads must remain JSON-safe values with string
object keys and finite numbers, and the top-level payload must be an object,
before any sink sees them. A sidecar may omit `session_key` or echo the
host-selected current session, but it cannot use telemetry payloads to claim a
different OpenSquilla session. Telemetry payloads may carry arbitrary diagnostic
fields, but they must not be shaped as public `AgentEvent` payloads such as
`kind: event` plus a public event `type`, or as Pi `intent_result` feedback;
event-shaped and intent-result-shaped payloads are rejected before any sink call.
Runtime failures from the default telemetry sink are
ignored so non-user-facing diagnostics cannot replace public turn events.
Telemetry sinks receive adapter-owned payload copies and must not return public
`AgentEvent` values, including through sync or async iterables; returning any
event is a protocol error because telemetry is not a sidecar event-injection
channel.

After a host port handles an intent, the Pi runtime may also report the
normalized host result back to the RPC client through an optional
`receive_intent_result(intent_type, payload, events, session_key)` callback.
This is the sidecar-loop feedback channel for provider/tool/queue outcomes; it
does not change the public CLI/TUI contract, which remains the normalized
`AgentEvent` stream. Feedback payloads and events are JSON-compatible,
adapter-owned copies, so in-process RPC clients see the same protocol-shaped
data as command-backed JSONL sidecars and cannot mutate the host event stream
before TurnRunner or CLI/TUI consumers observe it. Feedback delivery is
best-effort: ordinary callback failures must not replace or suppress host-owned
public events, though consumer cancellation still propagates through the
runtime normally. Feedback serialization failures are protocol errors, while
ordinary callback delivery failures remain best-effort. A successful
`yield.request` is the exception: once it returns a non-error `sessions_yield`
result, the sidecar stream is settled and OpenSquilla must not send same-turn
`intent_result` feedback for that success.

For command-backed JSONL sidecars, OpenSquilla writes the turn bootstrap as the
first JSONL frame on the sidecar process stdin before it reads stdout:

```json
{
  "protocol": "opensquilla.agent_core.v1",
  "kind": "turn_start",
  "payload": {
    "prompt": "user prompt",
    "kwargs": {
      "session_key": "agent:main:test",
      "session_id": "agent:main:test"
    }
  }
}
```

Prompt text, history, tool definitions, and other turn kwargs must not be
passed through process environment variables; the environment may carry only
non-sensitive adapter setup such as `OPENSQUILLA_AGENT_CORE_PROTOCOL`.
Provider API keys and Pi command/provenance variables must not be inherited by
Pi JSONL sidecar processes.
JSONL command clients must drain sidecar stderr concurrently so diagnostic logs
cannot block stdout frames; stderr is diagnostic data, not an event channel.
Sidecar stdout frames must be UTF-8 JSONL; invalid UTF-8 must fail before JSON
parsing or event normalization.
Sidecar stdout JSONL frames must remain within the command client's bounded
stream line limit; overlong frames fail before JSON parsing or event
normalization.
JSONL command clients must reject duplicate JSON object keys and non-finite
JSON constants before yielding frames, so parser last-key-wins behavior or
Python-only `NaN`/`Infinity` values cannot change sidecar protocol meaning.
Turn kwargs must be validated as JSON-compatible before the Pi command process
is launched, so malformed host bootstrap data cannot start a real sidecar.
Outgoing JSONL `turn_start.payload.prompt`,
`turn_start.payload.kwargs.session_key`,
`turn_start.payload.kwargs.session_id`, `intent_result.type`, and
`intent_result.session_key` must be non-empty strings.
If `turn_start.payload.kwargs.turn_snapshot` is present, it must be a JSON
object before the command process starts.
If `turn_snapshot.session_key` or `turn_snapshot.session_id` is present, it
must be a non-empty string before the command process starts.
When `turn_snapshot.session_key` or `turn_snapshot.session_id` is present
alongside the top-level turn kwarg, it must match the corresponding top-level
value before the command process starts.
Outgoing JSONL `intent_result.type` must be one of the allowed Pi intent types.
Outgoing JSONL `intent_result.payload` must be an object and
`intent_result.events` must be a list whose entries are event objects with
non-empty string `kind` fields from OpenSquilla's supported public `AgentEvent`
kinds. `intent_result.events` must also obey the host-port terminal ordering
rule: at most one terminal `done` or `error` event, and any terminal event must
be the final feedback event.
Outgoing JSONL `intent_result.payload` and `intent_result.events` must be
validated as JSON-compatible before the command client writes to sidecar stdin.

After a host intent is handled, the callback is serialized as one JSONL frame on
the same sidecar process stdin:

```json
{
  "protocol": "opensquilla.agent_core.v1",
  "kind": "intent_result",
  "type": "queue.poll",
  "payload": {"task_id": "task-1"},
  "session_key": "agent:main:test",
  "events": [{"kind": "run_heartbeat", "message": "queue empty"}]
}
```

The stdin frame is feedback to the sidecar loop only. The same normalized host
events are still yielded outward through the OpenSquilla runtime event stream.
Command-backed clients may write `intent_result` frames only while their
matching sidecar stream is active; stale stdin handles or post-turn callbacks
must fail before writing so feedback cannot cross turn or process boundaries.
Successful `yield.request` settlement does not write an `intent_result` frame.
The packaged Pi bridge may treat stdin EOF while `yield.request` is pending as
that settled success path; EOF while any other intent is pending remains a
protocol/lifecycle error.

## Stable Event Contract

The runtime-visible event stream remains the OpenSquilla `AgentEvent` union.
Kernel adapters must normalize foreign events into these events:

- Assistant text maps to `TextDeltaEvent`.
- Tool-call start maps to `ToolUseStartEvent`.
- Tool-call argument deltas are internal to the kernel adapter unless a future
  OpenSquilla event explicitly exposes them.
- Tool execution result maps to `ToolResultEvent` after OpenSquilla projection.
- Artifacts map to `ArtifactEvent`.
- Router replay maps to `RouterControlReplayEvent`.
- Compaction maps to `CompactionEvent`.
- Non-terminal notices map to `WarningEvent`.
- Terminal success maps to `DoneEvent`.
- Terminal failure maps to `ErrorEvent`.

`CompactionEvent.kept_entries` must remain a list of JSON-safe objects because
TurnRunner may persist those entries into host-owned history/compaction state.

`DoneEvent` must keep OpenSquilla usage, cost, cache, session-total, and routing
fields. If a kernel cannot provide a value, the adapter must populate the
existing neutral defaults rather than changing the schema.

For Pi, `DoneEvent`, `ToolResultEvent`, session writes, yield/subagent wake, and
provider request/proof frames remain host-finalized. Pi sidecar intent names
such as `tool.call.execute`, `session.write.enqueue`, `queue.poll`,
`savepoint.request`, `yield.request`, and `telemetry.emit` are valid only as
`kind: "intent"` host-port requests; a Pi sidecar frame that tries to emit
these as public OpenSquilla events is invalid.
When a Pi sidecar stream finishes without a terminal host event, the adapter
must ask `KernelHostPorts.finalizer` to synthesize the host-owned `DoneEvent`
from the normalized text deltas and neutral usage/cost defaults. The host
finalizer `text` and `model` payloads must be strings when present; omitted
text finalizes as an empty string, and omitted model falls back to host config
or provider usage. Explicit null `text` or `model` is malformed, not omitted.
Drained finalizer usage summary fields are strict too:
the usage summary must be an object, and
token/cache/iteration fields are non-negative integers, cost and billed-cost are
non-negative numbers, model/cost-source are strings, reasoning content is a
string or null, and `session_totals` is either null or a host-normalized
`SessionTotalsSnapshot` whose expanded token/cache fields are non-negative
integers and whose expanded cost fields are finite non-negative numbers. A
host-owned `DoneEvent` must not report `cached_tokens` or `cache_write_tokens`
greater than its `input_tokens`; session totals must not report
`cache_read_tokens` or `cache_write_tokens` greater than session
`input_tokens`. The direct finalizer port enforces the same cache-to-input
bound before returning a `DoneEvent`. A
present finalizer usage field with an explicit null value is malformed, except
`reasoning_content`, which may remain null. A
finalizer result that contains an `ErrorEvent` is a terminal
host-port failure. A
finalizer result with neither `DoneEvent` nor `ErrorEvent` is also a terminal
host-port failure, not a successful empty turn. A finalizer result must contain
exactly one terminal `DoneEvent` or `ErrorEvent`, and that terminal event must
be the last finalizer event. The adapter
must not synthesize `DoneEvent` while sidecar-announced tool calls remain
pending; an unsettled sidecar stream is a protocol error, not a successful turn.
Host-port returned `ToolUseStartEvent` and `ToolResultEvent` identities must
also use non-empty `tool_use_id` and `tool_name` strings before they become
public OpenSquilla events or Pi `intent_result` feedback. For Pi
`tool.call.prepare` and `tool.call.execute`, those returned tool identities must
also match the current intent's `tool_call_id` and `tool_name`; custom tool
ports cannot turn one sidecar tool intent into another public tool event or
sidecar feedback result.
Host-port returned `ArtifactEvent` values must also keep `session_key` equal to
the current host-selected turn session before they become public OpenSquilla
events or Pi `intent_result` feedback; custom `KernelHostPorts` implementations
cannot publish artifacts into a different session.

## Tool Contract

OpenSquilla remains the source of truth for tool definitions and execution.
Adapters must translate between foreign tool-call shapes and
`opensquilla.tool_boundary.ToolCall` / `ToolResult` without bypassing:

- tool visibility and policy,
- concurrency and timeout controls,
- approval retry,
- artifact publication and projection,
- execution-status envelopes,
- router-control results,
- turn-yield and terminate-turn semantics.

Foreign kernels may request tool execution, but OpenSquilla decides how tools
execute and what result text returns to the model.

## Selection Contract

Kernel selection must be explicit and reversible. Valid IDs are:

- `opensquilla`
- `pi`

The default is always `opensquilla`. Unknown IDs must fail before a turn starts
with a clear `ValueError` so callers do not silently fall back to a different
kernel.

Selection belongs in engine/runtime configuration, not in CLI/TUI command
schemas. CLI/TUI may continue to call `TurnRunner` as they do today.

Selected kernels may expose read-only provider identity metadata to the host
history/compaction loader so provider-native context state, such as Anthropic
compaction blocks, remains visible after kernel selection. This metadata surface
must not expose a callable provider client; provider calls remain host-owned
through `KernelHostPorts.provider`.

## Pi Direct-Use Boundary And Provenance

Production Pi kernels must connect to a real upstream Pi runtime, CLI, package,
or equivalent RPC process through a configured `pi_agent_rpc_command`,
`agent_core.pi_rpc_command`, or injected `pi_agent_rpc_client`. OpenSquilla must
not implement, rewrite, or half-rewrite Pi's own loop inside the host runtime.
The adapter must not implement or rewrite Pi's agent loop, including Pi-owned
no-throw stream semantics, `prepareNextTurn`, safe-point queues,
parallel tool scheduling/invocation scheduling/execution,
`beforeToolCall` / `afterToolCall` and before/after tool hooks, `shouldStopAfterTurn`,
`getSteeringMessages` / `getFollowUpMessages`, steering/follow-up queues, and
Pi session lifecycle logic.

OpenSquilla adapter code owns only process launch/connection, JSONL/RPC bridge,
protocol frame validation, host-port dispatch, event normalization, and process
lifecycle cleanup. Those pieces translate protocol and IO only. Provider calls,
tool execution, approvals, projection, session writes, yield/subagent wake,
router replay, and finalization remain OpenSquilla host-port effects.
Production command/client provenance must not claim the OpenSquilla wrapper or
client implements or rewrites Pi agent-loop mechanics such as
no-throw stream semantics, `prepareNextTurn`, safe-point queues,
parallel tool scheduling/execution, `beforeToolCall` / `afterToolCall`,
before/after tool hooks, `getSteeringMessages` / `getFollowUpMessages`,
steering/follow-up queues, or Pi session lifecycle.
Such provenance contradicts the sidecar contract even when it also names a real
upstream Pi runtime.
JSONL command clients own exactly one active sidecar stream; concurrent Pi
sidecar streams must use separate client instances so intent-result feedback
cannot cross turn or process boundaries. If a stream is already active, the
client must reject another stream before validating that second stream's prompt
or kwargs so malformed caller data cannot hide the concurrency fault.
Pi kernel runtime instances own exactly one active turn; concurrent work must
use host queueing or a separate runtime/session so pending tools, yield state,
and provider usage cannot cross turn boundaries.

Pi production startup must fail fast when neither `pi_agent_rpc_command` nor
`pi_agent_rpc_client` is configured, or when both are configured at once. A
production command/client must declare both the upstream Pi runtime/package it
invokes and the OpenSquilla
`opensquilla.agent_core.v1` sidecar protocol it speaks. Native upstream Pi CLI
or package modes (`pi --mode rpc`, legacy `pi --rpc`, `pi --mode json`,
`pi --mode text`, or `@earendil-works/pi-coding-agent` in those modes) are not
sufficient as an OpenSquilla agent kernel even if a provenance string claims
`opensquilla.agent_core.v1`, because native Pi modes do not emit host-port
intents and would let provider/tool/session effects happen inside Pi instead of
the OpenSquilla host. Direct Node execution of an upstream Pi package path is
treated as native Pi CLI/package invocation for the same reason. This includes
installed `@earendil-works/*` package paths and local Pi checkout paths such as
`packages/agent/src/index.ts`, `packages/coding-agent/src/cli.ts`,
`packages/ai/src/cli.ts`, and `packages/tui/src/index.ts`, including
package-runner source execution such as
`pnpm tsx packages/coding-agent/src/cli.ts --mode rpc`. Node inline code such as `node -e` /
`node --eval` that imports an upstream Pi package, and Node preload/loader
options such as `--import`, `--require`, `--loader`, and
`--experimental-loader` whose path, specifier, inline code, or data URL names an
upstream Pi package are treated as the same native Pi CLI/package invocation.
Upstream Pi repository launchers such as
`scripts/profile-coding-agent-node.mjs --mode rpc` are also native Pi launcher
modes, not OpenSquilla sidecar wrappers.
Environment or shell launch wrappers such as `env ...`, `bash -lc ...`,
`bash -lc 'exec -- ...'`, `bash -lc 'command -- ...'`, `csh -c ...`,
`fish -c ...`, `tcsh -c ...`, `cmd /c ...`, or
`powershell -Command ...` do not change this boundary;
they may wrap a valid OpenSquilla sidecar bridge command, but they must not
hide direct native Pi CLI/package execution. Process launch wrappers such as
`timeout ...`, `nohup ...`, `nohup -- ...`, `nice ...`, `setsid ...`, or
`stdbuf ...` follow the same rule. `NODE_OPTIONS` values that preload, import,
or inline-import upstream Pi packages cannot hide native Pi execution behind an
otherwise valid bridge command. Shell startup environment variables such as
`BASH_ENV`, `ENV`, or `ZDOTDIR` must not point at upstream Pi package/repository
paths while launching a bridge shell command. Command-bearing environment
variables such as `PI_AGENT_RPC_COMMAND`, `PI_AGENT_CMD`,
`PI_AGENT_COMMAND`, or `PI_AGENT_SPAWN` must not hide native upstream Pi RPC
commands behind an otherwise valid bridge command. Runtime reference
environment variables may name an upstream package as inert wrapper
configuration, but must not point at an upstream Pi repository source path and
must not be paired with wrapper env such as `PI_AGENT_MODE=rpc` that selects
native upstream Pi RPC mode. Ordinary model configuration variables such as
`MODEL=rpc` are not mode selectors and must not make an otherwise valid
OpenSquilla sidecar wrapper look like native upstream Pi RPC mode.
`env -S` / `env --split-string` wrappers must be parsed as the actual command
argv before applying native Pi CLI/package checks.
Windows `cmd` builtins such as `call ...` and `start ...` must likewise be
unwrapped before native Pi CLI/package checks, including optional `start` titles
and common `start` switches.
Windows launcher suffixes such as `.exe`, `.cmd`, `.bat`, and `.ps1` do not
change command identity: `pi.cmd`, `pi.ps1`, `npx.cmd`, `npm.cmd`, `pnpm.cmd`,
`yarn.cmd`, `bunx.exe`, and `node.exe` must be checked as their suffixless
commands, while suffix-bearing OpenSquilla bridge wrappers remain valid
adapter commands.
PowerShell encoded command wrappers such as `powershell -EncodedCommand ...`,
`powershell -enc ...`, or `pwsh -e ...` must be decoded and checked before
accepting the sidecar command; opaque or undecodable encoded payloads must
fail fast instead of being accepted as sidecar wrappers.
PowerShell file wrappers such as `powershell -File ...` or `pwsh -File ...`
must parse the script path and arguments before native Pi checks; a script path
under an upstream Pi package or the short `pi` launcher is native Pi execution.
`corepack pnpm` / `corepack yarn` / `corepack npm` launchers follow
package-runner native Pi checks; they may launch a valid OpenSquilla sidecar
bridge package, but they must not hide direct `@earendil-works/pi-*` package
execution. Package-runner package injection options such as `--package` and
`-p` must not inject upstream Pi packages behind a different command. Percent-
encoded upstream package or package-path specifiers in these argv tokens are
treated the same as literal specifiers. Package-runner shell command options
such as `npm exec -c ...` and
`npx -c ...` follow the same native Pi checks. Node script runners such as
`node --run pi` and package-runner `yarn node ...` must not hide native Pi RPC
mode or upstream Pi package paths. Package script runners such as `npm run pi`,
`pnpm run pi`, `yarn pi`, and `bun run pi` must not hide native Pi RPC mode.
Direct TypeScript/Deno executors such as `tsx`, `ts-node`, `jiti`, `esno`, or
`deno run npm:@earendil-works/pi-*` must not launch upstream Pi as an
OpenSquilla sidecar boundary. Package runners that target the short `pi` bin
such as `npx pi`, `npx pi@latest`, `pnpm dlx pi`, or `bunx pi` are native Pi
CLI/package invocation. Package creator/init runners such as `pnpm create`, `yarn create`,
`npm init`, and `bun create` must not target upstream Pi packages.
`@earendil-works/pi-agent-core` is valid runtime/provenance evidence, but it is
not accepted as a direct CLI command because the upstream package has no CLI
bin. FakePiRpcClient, fake/mock/dummy/stub/test/fixture/example/sample/demo-labeled
sidecars, and Python script sidecars are contract-test fixtures only; they may
validate protocol frames, host-port routing, cancellation, and lifecycle cleanup
only behind an explicit pytest-only test-fixture opt-in, but they must not
become a production runtime fallback and must not stand in for live Pi parity
evidence. Commands under `tests/`, `examples/`, `samples/`, or `demos/` paths
are treated as test/demo fixtures for this boundary, and `python -m tests.*`,
`python -m examples.*`, `python -m samples.*`, or `python -m demos.*` sidecar
commands are treated as test/demo fixtures too. Commands whose `PYTHONPATH`
points at a `tests`, `examples`, `samples`, or `demos` directory are also
treated as test/demo fixtures.
Production command/client provenance must not declare
fake/mock/dummy/stub/test/fixture/example/sample/demo fixtures.
Native upstream Pi RPC client identities must not be used as OpenSquilla
sidecar clients. A `pi_rpc_client` injected into production config must be a
client for the OpenSquilla sidecar protocol, not a direct upstream Pi client
whose provider/tool/session effects would bypass host ports.
Native Pi module prefixes such as `pi.agent`, `pi.coding_agent`,
`pi_agent_core`, or `pi_coding_agent`, and native Pi runtime class markers such
as `PiAgentRuntimeClient`, remain native Pi client identities even when the type
name also contains `OpenSquilla` or `Bridge`.
The pytest-only client fixture opt-in does not weaken this rule; it permits
contract-test fake clients, not direct native Pi runtime clients.

Command argv arguments that name an upstream Pi package do not count as
provenance. A wrapper such as `python opensquilla_pi_bridge.py --runtime
@earendil-works/pi-coding-agent` must still provide
`pi_agent_rpc_command_provenance` or equivalent client provenance declaring the
real upstream Pi runtime/package and the OpenSquilla agent-core sidecar
protocol.
Legacy upstream package/repository names from Pi's package-scope migration,
including `@mariozechner/pi-agent-core`, `@mariozechner/pi-coding-agent`, and
`github.com/badlogic/pi-mono`, may satisfy provenance for a bridge wrapper that
invokes a real upstream Pi package. They do not make direct native Pi CLI/package
execution a valid OpenSquilla sidecar.

Sidecar package wrapper commands may name upstream Pi packages as configuration
arguments. They must not pass inline executable code or data/javascript URLs
that import or otherwise name upstream Pi packages; those are treated as native
Pi CLI/package invocation rather than inert wrapper configuration. Percent-
encoded upstream package specifiers in inline code or data/javascript URLs are
treated the same as literal specifiers. Runtime-reference options such as
`--runtime`, `--runtime-package`, `--runtime_package`, `--pi-runtime`,
`--pi_runtime`, `--piRuntime`, `--agent-runtime`, `--agent_runtime`,
`--agentRuntime`, and `--runtimepackage` may name an upstream Pi
package as inert wrapper configuration, but they must not point to an upstream
Pi repository source path such as `packages/agent/`, `packages/coding-agent/`,
`packages/ai/`, or `packages/tui/`.
Wrapper module-resolution options such as `--module-root` may point to an
external wrapper/package root used to resolve installed upstream Pi packages,
but they do not count as provenance and must not vendor or point OpenSquilla at
copied Pi implementation files inside `src/opensquilla` or upstream Pi
repository source paths such as `packages/agent/`, `packages/coding-agent/`,
`packages/ai/`, or `packages/tui/`.
They must not pass a native upstream Pi command tail, such as
`-- @earendil-works/pi-coding-agent --mode rpc`, or a
command-bearing option value, such as `--runtime-command "pi --mode rpc"` or
`--runtimeCommand "pi --mode rpc"`, to a sidecar wrapper. For example, a
command such as
`npx @opensquilla/pi-agent-core-bridge --runtime
@earendil-works/pi-coding-agent` is a valid command shape only when its
provenance declares both the OpenSquilla agent-core sidecar protocol and the
upstream Pi runtime/package it invokes. This differs from directly
targeting the upstream Pi package itself, such as
`npx @earendil-works/pi-coding-agent --mode json`, which is native Pi
CLI/package execution and remains invalid as an OpenSquilla kernel boundary.
The sidecar bridge package name itself does not count as upstream Pi runtime
provenance, even when it contains Pi-like words such as `pi-agent-core`.
Direct package-runner commands under the upstream `@earendil-works/pi-*`
namespace are native Pi packages, not OpenSquilla sidecars.

OpenSquilla must not vendor Pi source or copy Pi implementation files into
`src/opensquilla`. If a thin wrapper is needed, it must invoke upstream Pi code
and only translate between upstream Pi IO and OpenSquilla agent-core frames. Pi
is MIT-licensed; integration docs, generated wrappers, and distribution notices
must preserve upstream Pi license and provenance information when the Pi bridge
is shipped or documented.

## Pi Adapter Contract

The Pi adapter is a sidecar boundary adapter, not a replacement for OpenSquilla
runtime semantics. It speaks JSON frames with:

```json
{
  "protocol": "opensquilla.agent_core.v1",
  "kind": "event | intent",
  "type": "text.delta",
  "payload": {}
}
```

Every sidecar frame must include the exact v1 `protocol` string declared by
`AgentCoreConfig.protocol_version`, and Pi sidecar v1 only supports
`opensquilla.agent_core.v1`. Unknown configured protocol versions, frame kinds,
and event or intent types are protocol errors. The frame `protocol`, `kind`,
and `type` values must be exact non-empty strings with no surrounding
whitespace before event/intent dispatch; structured values are invalid
protocol frames rather than fallback metadata.
Protocol validation happens before event or intent dispatch, including before
host-owned event denylist checks, and `kind` validation happens before event
`type` denylist dispatch. The adapter must fail fast rather than guessing compatibility,
because silent fallback can bypass host-owned provider, tool, session,
orchestration, or finalizer invariants.
Top-level sidecar frame fields are limited to `protocol`, `kind`, `type`, and
`payload`; any other top-level field is a protocol error rather than metadata.
In-process RPC clients must meet the same JSON-frame contract as JSONL command
sidecars: top-level frame object keys must be strings, and every frame field value,
including `payload`, must be JSON-compatible before dispatch. JSON-compatible
means standard JSON values only; non-finite numbers such as `NaN` and `Infinity`
are rejected instead of relying on Python's permissive JSON defaults.

Supported v1 event frames:

| Frame type | OpenSquilla handling |
| --- | --- |
| `text.delta` | yields `TextDeltaEvent` from string `payload.text` only |
| `error` | yields `ErrorEvent` from string `payload.message` / `payload.code` only |

A `text.delta` payload may omit `text` to represent an empty delta, but if
present `payload.text` must be a string and no other payload fields are allowed.
An `error` payload may omit `message` or `code`; missing values default to an
empty message and `pi_error` code, but present values must be strings, and
present `payload.code` must be a non-empty string. Structured sidecar data must
not be coerced into user-visible text or
terminal error metadata.

All side effects, including non-user-facing telemetry, must use supported
`kind: "intent"` frames so they pass through `KernelHostPorts`. Adapters must
pass host ports adapter-owned payload copies and report feedback from the
original sidecar frame, so host tools cannot mutate sidecar-visible intent
payloads by sharing nested dictionaries. Feedback events must also be copied
before they are passed back to the sidecar. Tool bridges must also build
`ToolCall.arguments` from owned copies, even when called directly by future
adapters.
Host ports may return only validated public `AgentEvent` values; numeric public
metrics such as `DoneEvent` cost/routing fields and `RouterDecisionEvent`
confidence must be finite, and `RouterDecisionEvent.probs` values must be finite
probabilities in the inclusive `0.0..1.0` range, never `NaN` or `Infinity`.
When a public event or intent frame includes `payload`, it must be a JSON object;
malformed payloads such as arrays or strings, non-string object keys, and nested
values that are not JSON-compatible fail before any `AgentEvent` is yielded or
host port is called. A missing payload is interpreted as an empty object only for
frames that can validly omit all optional fields.

Pi sidecar `error` frames, sidecar transport failures, and host-port runtime
failures are terminal failures normalized to `ErrorEvent` frames so TurnRunner
continues to consume the stable `AgentEvent` stream. Protocol violations,
unsupported frames, missing required host ports, and unsettled tool-call state
remain fail-fast adapter errors rather than model-visible failures. After an
`ErrorEvent` terminal failure or fail-fast protocol error, the adapter must
clear sidecar pending-tool state so the next turn starts from a clean/settled
boundary. For command-backed Pi sidecars, a sidecar-emitted terminal `error`
also closes the current stdout stream and terminates the command process; the
sidecar cannot keep writing events after that terminal failure.

When any host port yields a terminal `DoneEvent` or `ErrorEvent`, the Pi adapter
must yield that event and stop consuming sidecar frames for the turn. A sidecar
must not append text, tool intents, telemetry, or another terminal after host
terminal success or failure. If a host terminal event appears while sidecar tool
calls are still pending, the adapter treats that as a protocol error instead of
silently settling them.
Before intent-result feedback is sent back to the sidecar, each host-port event
batch must contain at most one terminal event, and a terminal event must be the
last item in that batch. This prevents a sidecar loop from observing impossible
same-turn state through feedback after the public `AgentEvent` stream has already
settled.

Supported v1 intent frames:

| Intent type | Required host port |
| --- | --- |
| `provider.request` | `KernelHostPorts.provider` |
| `tool.call.prepare` | `KernelHostPorts.tool_bridge` |
| `tool.call.execute` | `KernelHostPorts.tool_bridge` |
| `session.write.enqueue` | `KernelHostPorts.session_writes` |
| `queue.poll` | `KernelHostPorts.queue` |
| `savepoint.request` | `KernelHostPorts.savepoints` |
| `yield.request` | `KernelHostPorts.orchestration` |
| `telemetry.emit` | `KernelHostPorts.telemetry` (default no-op host sink) |

For session-scoped intents (`provider.request`, `tool.call.prepare`,
`tool.call.execute`, `session.write.enqueue`, `queue.poll`,
`savepoint.request`, `yield.request`, and `telemetry.emit`), the Pi adapter must validate any
sidecar-provided `session_key` before dispatching to `KernelHostPorts`. This is
a runtime-level invariant, so it also applies when tests or future embeddings
install custom host port implementations instead of OpenSquilla's concrete
ports. The sidecar may omit `session_key` or echo the host-selected current
session, but it cannot target a different session and explicit non-string or
null values are malformed.
For fixed-schema host-port intents (`provider.request`, `tool.call.prepare`,
`tool.call.execute`, `session.write.enqueue`, `queue.poll`,
`savepoint.request`, and `yield.request`), top-level payload allowlists are also
runtime-level invariants: unknown fields are rejected before any concrete or
custom `KernelHostPorts` implementation is called. `telemetry.emit` is the
exception: it remains a JSON-safe non-user-facing sink with reserved public
event and intent-result payloads denied by the telemetry host port.

Host-owned direct event frames are rejected, including Pi-native loop frames
such as `agent_start`, `turn_start`, `message_start`, `message_update`,
`message_end`, `tool_execution_start`, `tool_execution_update`,
`tool_execution_end`, `queue_update`, `compaction_start`, `compaction_end`,
`auto_retry_start`, `auto_retry_end`, `turn_end`, `agent_end`, plus host-owned
terminal or side-effect frames such as `done`, `text_delta`, `tool.result` /
`tool_result`, `artifact`, `tool_use_start`, `tool_use_delta`, `tool_use_end`,
`router_decision`, `router_control_replay`, `thinking`, `run_heartbeat`,
`state_change`, `warning`, `compaction`, `session.write`, and `yield`. This prevents Pi from
bypassing OpenSquilla's tool bridge, Tokenjuice projection, artifact projection,
approval retry, squilla-router decisions, router replay, session persistence,
finalizer, `TaskRuntime`, `subagent_announce`, and `background_completion`
semantics.

The Pi adapter tracks sidecar-announced pending tool calls from
`tool.call.prepare` until their matching `tool.call.execute` returns through the
host tool bridge. `yield.request` is invalid while any sidecar tool call remains
pending; OpenSquilla only accepts yield/orchestration intents from a clean
idle/settled sidecar state. A sidecar stream may only reach host finalization
after the pending set is empty. Once a host-owned `yield.request` returns a
non-error `sessions_yield` result, OpenSquilla stops consuming sidecar frames
for that turn, skips intent-result feedback for that success, and closes the
sidecar stream; the sidecar must not rely on any additional same-turn frames.
Parent wake, `TaskRuntime`, `subagent_announce`, and `background_completion`
remain host-owned consequences of `sessions_yield`.
No host port may return a `sessions_yield` `ToolResultEvent` for any intent
other than `yield.request`; this runtime-level rule applies to custom
`KernelHostPorts` implementations as well as OpenSquilla's concrete ports.
A non-error `sessions_yield` result returned by `yield.request` must be the
final event in its host-port batch.
Host-owned yield error results are feedback to the sidecar loop, not a settled
yield state.
`tool.call.execute` requires a matching earlier `tool.call.prepare` for the
same `tool_call_id`; this keeps tool-start events, approval retry, artifacts,
and projection on the host-owned path even when the sidecar schedules multiple
tool calls. Both `tool.call.prepare` and `tool.call.execute` must include a
string, non-empty `tool_call_id` and a string, non-empty `tool_name` after
normalization before reaching the host tool bridge. Compatibility aliases for
`tool_call_id` may be accepted only when each present identity field is already
string-typed and non-empty after normalization; a structured or blank primary
identity field cannot fall back to another alias. If present,
`synthetic_from_text` must be a JSON boolean and `origin_trace` must be a
string; explicit null is malformed, not omitted, and neither field may be
coerced from structured or truthy/falsy sidecar values.
`KernelHostPorts.tool_bridge` must enforce the same identity and
provenance-field rules, so future adapters cannot bypass runtime-side
validation with structured tool metadata fields. Multiple tool
calls may be prepared concurrently, but each pending `tool_call_id` must be
unique until its matching execute returns through the host tool bridge.
A host-owned tool error result still settles the matching pending tool call;
only unsettled tool calls, protocol errors, or runtime failures keep the turn
from reaching the normal finalizer path.

When the Pi kernel is selected through the normal TurnRunner construction path,
the v1 adapter wires host-owned ports for provider requests, tool calls,
session writes, savepoints, and yield orchestration:

- `provider.request` calls the configured OpenSquilla provider and normalizes
  provider heartbeat/text/error frames back to `AgentEvent`, preserving
  retry/idle heartbeats plus token, cache, cost, and model fields. The top-level
  payload is an allowlist: `session_key`, `messages`, `prompt`, `message`,
  `tools`, and `config`; unknown fields are rejected by the runtime before any
  provider call or custom `KernelHostPorts.provider` implementation is called.
  Sidecar-supplied `tools`, when present, must be a JSON-safe list or null, and
  sidecar-supplied `config`, when present, must be a JSON-safe object.
  Sidecar-supplied `tools` and `config` are accepted only as inert protocol echo
  fields and cannot override host-owned policy. Provider `ChatConfig` is derived
  from the host agent configuration; sidecar-supplied config fields must not
  override host system prompt, request timeout, stop
  sequences, cache policy, budgets, capabilities, thinking level/resolved
  thinking budget, or proof limits. The Pi construction path must preserve all
  recognized `AgentConfig` fields from lightweight host config objects instead
  of rebuilding a lossy minimal config. Mutable host fields, including stop
  sequences, cache breakpoints, and tools, are adapter-owned copies before they
  reach a provider or sidecar. The provider host port must preserve
  `AgentConfig.resolve_thinking(...)` semantics
  for boolean, fixed-level, and adaptive thinking. The provider-visible tool
  list is also host-derived and copied before the provider call;
  sidecar-supplied `tools` cannot change OpenSquilla tool visibility or policy,
  and provider mutation cannot corrupt host tool definitions. Provider
  `messages` must be a list when present; entries must be JSON-safe values with
  string object keys and finite numbers, validate as OpenSquilla provider
  `Message` values, and are copied before reaching the provider.
  Provider message `tool_calls`, when present, must be a list whose entries are
  objects before the message can reach the provider. Assistant `tool_calls`
  are normalized into OpenSquilla provider-native `tool_use` content blocks
  before `Message` validation, so OpenAI-style sidecar context cannot be
  silently dropped by the host provider port.
  Invalid sidecar message shapes are rejected before reaching the provider.
  Provider request messages must repair orphaned provider-native
  `tool_use`/`tool_result` pairs before provider dispatch so a sidecar cannot
  make the next provider turn fail with a dangling tool call that has no
  matching result. If repair removes every message, the provider request is
  malformed and must fail before provider dispatch.
  Sidecar messages may echo host-authored provider-native compaction,
  thinking, `reasoning_content`, or `cache_control` fields that came from
  OpenSquilla history/context, but cannot invent new provider context controls;
  compaction state, cache breakpoints, proof generation, thinking provenance,
  and cache accounting remain host-owned.
  Provider requests must include `messages`, `prompt`, or `message`; an omitted
  user input is malformed and cannot become an empty provider user `Message`.
  When `messages` is omitted, fallback `prompt` / `message` payloads
  must be non-empty strings before they can become a provider user `Message`;
  blank strings and explicit null are malformed, not omitted. Provider
  text/error/heartbeat fields that become public `AgentEvent` fields must be
  strings before host conversion; malformed provider output is rejected instead
  of leaking structured values to CLI/TUI-visible events. The sidecar
  may omit `session_key` or echo the current host session, but it cannot target
  another session. If supplied, `session_key` must be a string before session
  ownership is evaluated; explicit null is malformed, not omitted. Provider tool-use
  start/delta/end streams are collected
  as a host-owned provider-tool envelope: starts may surface as
  `ToolUseStartEvent`, argument deltas/end frames are accumulated inside the
  host port, and complete calls execute through the host tool bridge so
  projection, artifacts, approval retry, router replay, and tool-result
  delivery remain OpenSquilla-owned. Provider tool-use start/delta/end identity
  fields must be non-empty strings before the host uses them for public
  `ToolUseStartEvent` values, pending-stream lookup, or host tool execution;
  end `tool_name` must match the original start `tool_name` for the same
  `tool_use_id`. Streamed argument fragments must be strings. Provider tool-use
  `synthetic_from_text` provenance must be a JSON
  boolean. Complete provider tool-use arguments are copied before entering the
  host tool bridge and must be JSON-safe objects with string object keys and
  finite numbers; direct non-object or Python-only arguments fail fast instead
  of reaching tool execution.
  `sessions_yield` remains reserved for `yield.request` execution, but it may
  appear as a provider tool-use stream under `provider.request`; the real Pi
  runtime must receive that feedback and execute it through the bridge's
  `yield.request` mapping rather than through ordinary `tool.call.execute`.
  Incomplete, duplicate, or out-of-order provider tool-use streams fail fast
  instead of silently losing arguments or bypassing host tool execution.
  Provider-level done frames are
  intent-result feedback only when the Pi kernel is wired through the host accumulator; they do
  not become turn-level `DoneEvent`. This lets the sidecar loop continue toward a
  final answer while their token/cache/cost/model fields are accumulated by the
  host and drained into the eventual host-finalized turn-level `DoneEvent`,
  preserving live parity accounting even when a sidecar loop performs multiple
  provider/tool steps. Provider usage accounting is strict in both accumulated
  and direct provider-done paths: token/cache fields must be non-negative
  integers, cached/cache-write counters must not exceed input tokens, billed
  cost must be a non-negative number, stop reason must be a string, and
  model/cost-source/reasoning fields must be strings; stringified numbers or
  structured values are rejected
  instead of being coerced into live parity metrics, including provider done
  frames with non-terminal stop reasons. Explicit null values are malformed, not
  omitted, for token/cache/cost fields and for `model`/`cost_source`;
  `reasoning_content` may remain null. When
  provider output omits a model and host `config.model_id` is used as fallback,
  that host value must also be a string or omitted/`None`.
  The direct provider host-port result batch obeys the same terminal-event
  ordering rule as Pi intent feedback: at most one terminal event, and only as
  the final item.
  Accumulated provider usage is turn-scoped and must be reset on turn start,
  sidecar errors, protocol failures, and consumer cancellation so failed turns
  cannot leak accounting into later turns.
- `tool.call.prepare` / `tool.call.execute` execute through the OpenSquilla tool
  bridge so projection, artifacts, approval retry, and router-control replay
  remain host-owned. Tool intent top-level payloads are allowlisted to
  `session_key`, `tool_call_id`, `toolCallId`, `id`, `tool_name`, `name`,
  `arguments`, `input`, `synthetic_from_text`, and `origin_trace`; unknown
  fields are rejected by the runtime before prepare events, host tool execution,
  or any custom `KernelHostPorts.tool_bridge` implementation is called. `sessions_yield`
  is reserved for `yield.request`; direct `tool.call.prepare` / `tool.call.execute`
  frames for `sessions_yield` are invalid because they bypass host session injection
  and sidecar settle/close semantics. Tool call `arguments` or fallback `input`
  must be JSON objects
  with string object keys and finite numbers when present; malformed arguments
  fail fast instead of being converted to an empty host tool call or reaching
  host tool execution. If both fields are present, `arguments` is selected for
  host execution but `input` must still pass the same JSON-safe object
  validation before prepare events or host tool execution.
  Sidecar-supplied `approval_id` or `approvalId` in tool
  arguments is invalid; OpenSquilla injects approval IDs only during the
  host-owned approval retry path. A sidecar may omit `session_key` on tool intents or echo
  the current host session, but it cannot target another session; if supplied,
  `session_key` must be a string before host tool execution. Tool bridge events
  must not contain terminal
  `DoneEvent` or `ErrorEvent`; tools feed the sidecar loop through projected
  tool results, while turn termination remains provider/finalizer-owned. Tool
  result artifacts must be a list; explicit null is malformed, not an empty
  artifact list. Each artifact is validated before it
  becomes a public `ArtifactEvent`: string fields remain strings and `size`
  remains a non-negative integer. Projected tool results are validated
  again before they become public `ToolResultEvent` values: `tool_use_id`
  and `tool_name` must be non-empty strings that match the original host tool
  call, `content` must be present and must be a string, `is_error` must be a boolean, and
  `execution_status` must be either null or a JSON-safe object normalized by the
  host. Tool result `arguments`, when present, must also be a JSON-safe object.
  Router replay events emitted from tool output are validated before entering
  the public stream: `action` is
  a string, `target_tier`, `target_model`, `target_provider`, and `target_id`
  are strings or null, and `replay_depth` is a non-negative integer.
  `KernelHostPorts.tool_bridge` must reject `sessions_yield` at the port boundary
  too, so future adapters cannot bypass the orchestration port by calling the
  tool bridge directly.
- `queue.poll` observes or waits on the host `TaskRuntime` when one is attached
  through the session manager and reports a host-owned queue heartbeat
  containing a stable task-status snapshot through the normal intent-result
  event channel. The heartbeat snapshot is validated before it enters the public
  stream: TaskRuntime `status` and heartbeat `task_id` are strings, and
  `terminal_reason` is a string or null. The top-level payload is allowlisted to
  `session_key`, `task_id`, `operation`, `action`, and `timeout_seconds`;
  unknown fields are rejected by the runtime before TaskRuntime lookup or any
  custom `KernelHostPorts.queue` implementation is called. `queue.poll.task_id`,
  `operation`, and `action` must be strings when present; structured and
  explicit null values are rejected before TaskRuntime lookup. A sidecar may omit
  `session_key` or echo the current host session, but it cannot poll a queue for another
  session; if supplied, `session_key` must be a string before TaskRuntime
  lookup. It never
  lets the sidecar enqueue, cancel, reorder, list, or drain OpenSquilla tasks
  directly or by embedding a control `operation` in the poll payload.
  Sidecar-provided `timeout_seconds` must be a finite non-negative JSON number;
  explicit null is malformed, not omitted. It is a host-clamped hint, not
  authority to block a turn indefinitely.
- `session.write.enqueue` calls `SessionManager.append_message` for the
  host-selected current `session_key` inside the runtime session-write context
  when a session manager is available. A sidecar may omit `session_key` or echo
  the current value, but if supplied it must be a string and cannot target a
  different session; explicit null is malformed, not omitted. It also cannot
  write a privileged `system` transcript role after role
  normalization. When present, `role` must be a string that normalizes to
  `user`, `assistant`, or `tool`; unsupported transcript roles are rejected
  before entering `SessionManager`. The payload is an allowlist contract:
  `session_key`, `role`, `content`, `reasoning_content`, `tool_calls`,
  `turn_usage`, and `token_count` are the only accepted fields, and unknown
  fields are rejected by the runtime before entering `SessionManager` or any
  custom `KernelHostPorts.session_writes` implementation is called. `content` and
  `reasoning_content` must be strings when present; omitted `content` becomes an
  empty string, omitted `reasoning_content` remains `None`, and explicit-null
  `reasoning_content` is malformed.
  When present, `tool_calls` must be a list whose entries are objects,
  `turn_usage` must be an object, and `token_count` must be a non-negative
  integer; explicit null values for these fields are malformed, not omitted.
  Sidecar-provided `tool_calls` and `turn_usage` payloads must be
  JSON-safe values with string object keys and finite numbers. Known
  `turn_usage` token/cache, iteration, and context-size counters, including
  `total_tokens`, `iterations`, and `runtime_context_chars`, must be
  non-negative integers, and `cached_tokens`/`cache_write_tokens` cannot exceed
  `input_tokens` when the input total is present; known cost/savings fields,
  including total savings fields, must be non-negative finite numbers, and known
  parity/routing rates such as `cache_hit_rate`,
  `kv_cache_hit_rate`, and `routing_confidence` must be finite probabilities in
  the closed range `0 <= x <= 1`. Known model/cost/router/provenance string
  metadata fields must be strings, while `routed_tier`, `runtime_context_hash`,
  and `reasoning_content` may be strings or null. Known boolean cache/router
  metadata such as `cache_hit_active` and `routing_applied` must be boolean.
  These payloads are copied before entering the session manager so host mutations
  cannot leak back into
  the sidecar frame or caller-owned payload.
- `savepoint.request` calls `SessionManager.record_memory_checkpoint` for the
  host-selected current `session_key` inside the same write context when that
  capability is available. A sidecar cannot create checkpoints for a different
  session; if supplied, `session_key` must be a string before session ownership
  is evaluated, and explicit null is malformed, not omitted. The top-level
  payload is allowlisted to `session_key`, `transcript`, `turn_id`, and `source`;
  unknown fields are rejected by the runtime before entering `SessionManager` or
  any custom `KernelHostPorts.savepoints` implementation is called. Sidecar-provided
  checkpoint `turn_id` and `source` metadata must be
  strings when present; omitted or blank string values use host defaults.
  Explicit null `turn_id` or `source` values are malformed, not omitted. Sidecar
  source metadata must not claim privileged host provenance such as `host`,
  `opensquilla`, or `session-manager`. Sidecar-provided checkpoint `transcript`
  must be a list of objects when present; explicit null `transcript` is
  malformed, not omitted. When present,
  transcript `role` must be a non-empty string that normalizes to `user`,
  `assistant`, `tool`, or the privileged `system` value rejected below; `content`,
  and `reasoning_content` must be strings, transcript `tool_call_id` must be a
  non-empty string, `tool_calls` must be a list whose entries are objects, and
  `token_count` must be a non-negative integer. Explicit null values for these
  transcript fields are malformed, not omitted. Sidecar-provided transcript
  `tool_calls` must be JSON-safe values with string object keys and finite
  numbers. Checkpoint transcript objects are
  copied and normalized into host-readable checkpoint entries before entering
  the session manager, and cannot contain privileged `system` transcript roles
  after role normalization,
  so host checkpoint mutation cannot leak back into the sidecar frame or
  caller-owned payload.
- `yield.request` executes the host `sessions_yield` tool for the host-selected
  current `session_key`. A sidecar may omit `session_key` or echo the current
  value, but if supplied it must be a string and cannot yield a different
  session; explicit null is malformed, not omitted. The top-level payload is
  allowlisted to `session_key`, `message`, `reason`, `timeout_seconds`, and
  `tool_call_id`; unknown orchestration-control fields are rejected by the
  runtime before the host `sessions_yield` tool call or any custom
  `KernelHostPorts.orchestration` implementation is called. If a sidecar supplies `tool_call_id` for the host-owned
  `sessions_yield` call, it must be a string; omitted or blank string values use
  the host default `yield-request`, while explicit null is malformed. The adapter
  must not inject `session_key` into host `sessions_yield` arguments; omitting
  that argument selects OpenSquilla's current-turn yield path, while supplying it
  would select the legacy child-status wait path. The packaged Pi bridge
  preserves Pi's `reason` yield argument as top-level `yield.request.reason`;
  it does not rename Pi yield arguments into host-only fields. Sidecar-provided
  yield arguments are copied before the host tool call; when present, `message`
  and `reason` must be JSON-safe values with string object keys and finite
  numbers.
  Sidecar-provided `timeout_seconds` must be a finite
  non-negative JSON number; explicit null is malformed, not omitted. It remains
  a host-clamped wait hint, not authority to block a turn indefinitely.
  The host orchestration batch for `yield.request` must contain exactly one
  `sessions_yield` `ToolResultEvent`; public text, heartbeats, terminal events,
  or other tool results from the orchestration port are protocol errors. Parent wake and background completion
  remain consequences of
  OpenSquilla `TaskRuntime`,
  `subagent_announce`, and `background_completion`, not sidecar-owned effects.
- `sessions_spawn` and `sessions_send` remain ordinary host tool calls through
  `tool.call.prepare` / `tool.call.execute`; the sidecar never creates or owns
  child-session lifecycle state directly.

`KernelHostPorts.tool_bridge`, `session_writes`, `queue`, `savepoints`,
`orchestration`, and `telemetry` are non-terminal ports. They must not return
public `DoneEvent` or `ErrorEvent` values; provider and finalizer ports are the
only Pi host-port paths that may terminate a turn.

If a required host capability is absent, the adapter fails fast instead of
silently emulating the effect in Pi. This fail-fast rule applies to provider,
tool, session write, queue, savepoint, and yield/orchestration intents; only
non-user-facing telemetry has a default host no-op sink.

Pi-style internal hook, queue, wake, or finalizer intents are not protocol
frames. Examples such as `tool.hook.before`, `tool.hook.after`,
`provider.hook.before`, `provider.hook.after`, `queue.enqueue`, `queue.drain`,
`session.write.direct`, `subagent.wake`, `parent.wake`, and `turn.finalize`
must fail fast when emitted by the sidecar. Their semantics belong behind
OpenSquilla-owned provider/tool/session/queue/orchestration/finalizer ports, or
behind a future explicitly versioned port added to this contract.

## Clean-Room Pi Alignment

Pi's stronger runtime ideas should be aligned semantically, not copied into
OpenSquilla. The v1 mapping treats these Pi-style concepts as host-owned ports:

- queue drain and steering/follow-up safe points map to `KernelHostPorts.queue`
  plus OpenSquilla `TaskRuntime` orchestration;
- pending session writes map to `KernelHostPorts.session_writes`;
- provider hooks map to `KernelHostPorts.provider` so provider proof,
  accounting, cache metadata, and retries remain OpenSquilla-owned;
- provider proof numeric fields such as `retry_count`, `estimated_chars`,
  `proof_budget`, `raw_proof_budget`, `effective_proof_budget`, and
  `proof_headroom_chars` are non-negative integer counters; booleans and
  fractional values, as well as stringified numbers, are malformed parity
  evidence, even if a local runtime could coerce them;
- provider proof `fallback_reason`, when present, is string metadata; structured
  values, nulls, and other non-string values are malformed parity evidence;
- tool hooks map to `KernelHostPorts.tool_bridge` so approval retry,
  execution status, artifacts, and Tokenjuice projection remain unchanged;
- savepoint and lifecycle recovery map to `KernelHostPorts.savepoints` and
  `KernelHostPorts.finalizer`; Pi adapters must not construct terminal success
  events directly when the stream ends.

This gives OpenSquilla room to adopt Pi-grade lifecycle discipline while keeping
existing Python-agent, router, meta-skill, and CLI/TUI contracts intact.

## Migration Rules

- First implementation must keep the existing Python agent behavior equivalent
  at the `AgentRunPort` boundary. The default kernel remains `opensquilla`.
- Add the selectable-kernel abstraction with tests before integrating live Pi
  RPC behavior.
- Pi RPC process management must be isolated behind a Pi-specific adapter.
  The initial supported process boundary is a JSONL command client configured
  by runtime config (`pi_agent_rpc_command`, top-level `pi_rpc_command`, or
  `agent_core.pi_rpc_command`). Equivalent aliases must resolve to the same
  normalized value when more than one is provided; conflicting aliases are
  malformed production config. Object-valued aliases such as
  `pi_agent_rpc_client` and `pi_rpc_client` must point to the same object
  identity, not merely compare equal.
  In production, that command must invoke upstream Pi through a sidecar bridge
  that speaks `opensquilla.agent_core.v1`; native Pi CLI/package modes such as
  RPC, JSON, and text are not valid OpenSquilla kernel boundaries because
  provider/tool/session effects would be Pi-owned instead of host-owned. Direct
  Node execution of upstream package paths is also treated as native package
  invocation. A thin wrapper may translate IO/protocol
  around upstream Pi, but it must not contain Pi loop logic. Runtime config must
declare both upstream Pi provenance and OpenSquilla agent-core sidecar protocol
provenance for production commands; argv arguments naming upstream Pi packages
are configuration only and do not satisfy provenance. Argv arguments containing
inline executable code or data/javascript URLs that name upstream Pi are native
invocation, not wrapper configuration, including when the upstream package
specifier is percent-encoded one or more times. A sidecar wrapper must also not
turn module-resolution roots such as `--module-root` into vendored Pi source or
provenance substitutes. It must also not
receive a native
upstream Pi command tail such as `-- pi --mode rpc` or
`-- @earendil-works/pi-coding-agent --mode rpc`. Sidecar package wrapper
commands must also not hide native upstream Pi commands inside command-bearing
option values such as `--command`, `--exec`, `--runtime-command`,
`--runtime-cmd`, `--runtimeCmd`, `--runtime_cmd`, `--runtime_command`,
`--runtimeCommand`, or agent command options such as `--agent-command`, `--agentCmd`, or
`--agent_cmd`, as well as wrapper spawn options such as `--spawn-command`,
`--spawnCommand`, `--spawnCmd`, and `--spawn_command`. They are allowed only
when the runner target is the sidecar wrapper package, not the native upstream
Pi CLI/package. The command receives
`OPENSQUILLA_AGENT_CORE_PROTOCOL` plus a stdin `turn_start` JSONL frame
containing prompt and kwargs, then emits one agent-core protocol frame per
stdout line. Prompt and turn kwargs must not be exposed through environment
  variables.
  OpenSquilla owns that process lifecycle: if the adapter stops consuming the
  sidecar stream early because a host terminal event, sidecar terminal error,
  runtime error, protocol error, or caller cancellation ends the turn, it must
  close the process boundary and terminate the child process instead of leaving
  a detached Pi command running.
- `sessions_yield` success requires a clean idle/settled sidecar state with no
  pending sidecar tool calls. Parent wake remains owned by OpenSquilla
  `TaskRuntime`, `subagent_announce`, and `background_completion`.
- Any future richer orchestration feature must extend the kernel boundary via
  new ports/events, not by modifying CLI/TUI contracts first.

## Functional Parity Gate

Agent-core changes must include an API-backed functional gate in addition to
pure unit tests. The gate compares:

- the old OpenSquilla Python-agent path,
- the selectable `opensquilla` kernel path,
- the selectable `pi` kernel path when a real upstream Pi sidecar bridge,
  package wrapper, or equivalent upstream RPC process is configured. Pi live
  parity requires the full `OPENSQUILLA_AGENT_CORE_LIVE_PARITY=1` gate as well
  as the Pi-specific `OPENSQUILLA_AGENT_CORE_PI_LIVE=1` gate, so direct Python,
  selectable OpenSquilla, and Pi adapter evidence are produced together. The Pi
  live command/client must not point to
  fake/mock/dummy/stub/test/fixture/example/sample/demo-labeled fixtures,
  must not point directly at native Pi CLI/package
  modes, and must not enable the test-fixture opt-ins used by contract tests. Live parity must
  fail fast when `OPENSQUILLA_AGENT_CORE_ALLOW_TEST_PI_RPC_COMMAND`,
  `OPENSQUILLA_AGENT_CORE_ALLOW_TEST_PI_RPC_CLIENT`,
  `OPENSQUILLA_ALLOW_TEST_PI_RPC_COMMAND`, or
  `OPENSQUILLA_ALLOW_TEST_PI_RPC_CLIENT` is truthy.
  `OPENSQUILLA_PI_AGENT_RPC_COMMAND_PROVENANCE` must name the upstream Pi
  runtime/package invoked by the sidecar bridge. Pi live command provenance
	  must not declare fake/mock/dummy/stub/test/fixture/example/sample/demo fixtures. Explicit live parity opt-in
	  without provider credentials must fail instead of skip, so the API-backed
	  evidence gate cannot silently disappear.
	  Pytest marker selection is part of this gate: only tests that can make real
	  provider calls carry `llm`, `llm_gateway`, and `llm_tools`; non-API
	  threshold, validation, provenance, and fixture-rejection tests must stay
	  selectable under the ordinary `-m "not llm"` regression profile.

The comparison consumes only normalized OpenSquilla `AgentEvent` values and
must record at least:

- terminal success/failure, with a missing terminal event rejected before parity
  comparison,
- exact normalized final answer text after host-finalized `DoneEvent`; missing
  or extra final text fails parity,
  with at most one host-finalized `DoneEvent` accepted per collected turn.
  A terminal `DoneEvent` or `ErrorEvent` must be the final collected public
  event; post-terminal text, tool, router, artifact, heartbeat, or metadata
  events are rejected instead of counted into parity metrics,
- exact streamed `TextDeltaEvent` text after stable chunk concatenation, without
  constraining kernel-specific chunk boundaries; missing or extra stream text
  fails parity,
- input, output, reasoning, and total token counts, including missing-accounting
  and bounded component-level ratio/slack regression checks; candidate token
  counts above baseline-derived slack fail parity even when baseline counts are
  zero,
- cached input tokens, cache-write tokens, cache-active metadata, and KV-cache
  hit rate; candidate cache-write tokens above baseline-derived slack fail
  parity even when baseline cache-write tokens are zero,
- runtime-context metadata, including exact host-owned context hash and
  non-negative context-size fingerprints from the terminal `DoneEvent`,
- cost and billed-cost accounting, including missing-accounting and bounded
  ratio/slack regression checks; candidate cost above baseline-derived slack
  fails parity even when baseline cost is zero,
- terminal `DoneEvent` cost/model/router attribution metadata, including exact
  cost source, provider model, baseline/routed model, routed tier, routing
  confidence/source, and rollout-phase fingerprints,
- session-total token, cache-read/cache-write, cost, and billed-cost accounting,
  including missing, lower-than-baseline, and excessive ratio/slack drift checks,
- malformed accounting events with negative or non-finite turn/session token,
  cache, iteration, context-size, cost, or billed-cost fields must fail the
  parity collector before comparison,
- tool-call count,
- tool error count,
- tool success rate; success/error counters must be backed by observed tool
  calls or stable tool-result fingerprints, and when stable tool-result
  fingerprints are present their count must exactly match success/error
  accounting so handcrafted live metrics cannot inflate or omit tool success
  evidence,
- provider/request proof availability where the harness can capture it, including
  missing or excessive proof count, boolean fit status, missing or excessive
  retry metadata, bounded estimated provider payload chars, and stable proof
  budget/headroom integer metadata, plus boolean compaction-decision metadata
  that cannot be stringified or integer-coerced. Provider
  payload char drift thresholds
  are test configuration, but they must be validated before comparison: the ratio
  must be a finite number at least `1.0`, and the additive slack must be a
  non-negative integer,
- router metadata and router-control replay parity, including exact routed
  model/source identity, stable router decision/replay counts, decision
  tier/model/source fingerprints, routing-applied metadata, and replay
  action/target/provider/depth fingerprints,
- Tokenjuice projection consistency for tool results, including exact projected
  result text, normalized arguments, error state, and execution-status metadata
  fingerprints; missing or extra tool results fail parity,
- artifact event parity via exact stable name, MIME type, non-negative size, and
  content hash fingerprints; missing or extra artifacts fail parity,
- host-owned thinking, state-change, warning, compaction, and heartbeat parity,
  including exact stable public thinking text, state transition, warning
  code/message, compaction
  summary/non-negative count/kept-entry, and queue/runtime heartbeat
  phase/message/non-negative elapsed/idle fingerprints; missing or extra
  host-owned public events fail parity,
- malformed public events with negative artifact size, heartbeat elapsed/idle
  counters, or compaction counters must fail the parity collector before
  comparison,
- session-total snapshots and session writes, including exact snapshot presence
  and exact write counts; missing or extra session-total snapshots and missing
  or extra session-total dimensions fail parity;
  observable session write containers must be lists, and each write record must
  be an object with a non-empty stable session key, a role limited to `user`,
  `assistant`, or `tool`; observable transcript `content` must be a string when
  present, `reasoning_content` must be a string or null when present, and the
  remaining normalized payload fingerprint must be JSON-compatible when the
  harness can observe it; when baseline write counts are non-zero and equal to
  the candidate count, baseline session write fingerprints are required before
  content parity can be claimed,
- yield/subagent completion behavior, including exact `sessions_spawn`,
  `sessions_send`, and `sessions_yield` result fingerprints plus
  `sessions_yield` result counts; missing or extra orchestration results fail
  parity,
- terminal error messages.

A candidate kernel is weaker and must fail the gate when the baseline succeeds
but the candidate does not, when tool-call count differs from the baseline,
when tool success rate regresses,
when tool error count increases, when token accounting is missing,
when token usage exceeds the configured drift
threshold, when cache-write tokens exceed the configured drift threshold, or when
KV-cache hit rate falls below the configured tolerance, or when yield/subagent
result counts differ from the baseline. Live
tests are explicit opt-in because they spend real API credits, but their drift
configuration is still validated before comparison: token ratio must be finite
and at least `1.0`, token slack must be a non-negative integer, and KV-cache hit
rate delta must be finite and no lower than `-1.0`. Tool success rate delta must be finite and
non-negative. Cost ratio must also be finite and at least `1.0`, and cost slack
must be finite and non-negative. These tests are part of the required
release/merge evidence for agent-core work.
