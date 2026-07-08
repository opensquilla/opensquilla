# Runtime experiment toggles ("levers")

OpenSquilla exposes a family of opt-in runtime behaviors that scripted or
harness-controlled runs can enable per run without changing code or config
files. This page records the conventions those toggles must follow and how a
calling harness can verify that a toggle it requested was actually delivered.
The companion tooling lives in `scripts/experiments/`.

## Conventions

- **Naming**: `OPENSQUILLA_<AREA>_<KNOB>` (e.g.
  `OPENSQUILLA_PROVIDER_HISTORY_DEDUP`,
  `OPENSQUILLA_TOOL_REPEAT_NUDGE_THRESHOLD`).
- **Single parse site**: environment values are parsed only in
  `engine/turn_runner/agent_bootstrap_stage.py` (`_*_from_env` helpers), flow
  into `AgentConfig` fields, and are consumed by runtime resolvers. Nothing
  else in the engine reads these variables directly.
- **Default off**: with no toggle set, the runtime behaves like stock
  OpenSquilla. A toggle must never change behavior for users who have not set
  it.
- **Strict values**: unrecognized values raise instead of being silently
  ignored, so a run manifest cannot record an override the run did not
  actually apply.
- **Provider differences live in policy tables**: per-provider behavior
  belongs in `OpenAICompatPolicy`, `ProviderContextProfile`, or
  `reasoning_dialects` fields — never in model-name conditionals at call
  sites.

## Delivery verification

A harness that sets toggles can verify delivery end to end:

1. The harness allowlist decides which variables are passed into the
   container (`docker exec -e ...`).
2. The harness echoes the delivered environment into the run's
   `metadata.json` under `agent.controls.progress_watchdog_env`. This echo is
   written by the harness adapter unconditionally — it does not depend on any
   runtime toggle, including the watchdog mode itself.
3. `scripts/experiments/exp_finalize.py` gates a finished run on the expected
   environment (`AGENT_ENV_DELIVERY_VARS`), and
   `scripts/experiments/check_treatment_delivery.py` asserts the resulting
   provider payload shape (e.g. expected proof budget, reasoning effort, and
   a bounded number of reasoning fallbacks).

## Adding a new toggle

A new toggle must:

1. be added to the calling harness's allowlist,
2. default off, and
3. be added to `AGENT_ENV_DELIVERY_VARS` if it can affect task outcomes, so
   the delivery gate covers it.

## Reproducing older behavior

Two defaults were flipped to off when this code was merged; runs that want
the previous behavior should pin them explicitly:

- `OPENSQUILLA_PROGRESS_WATCHDOG_MODE=warn_model` (merged default: `off`;
  other values: `log`, `block`). Harness-controlled runs should always pin
  this mode explicitly rather than relying on the default.
- `OPENSQUILLA_TOOL_REPEAT_NUDGE_THRESHOLD=3` (merged default: `0`,
  disabled).
