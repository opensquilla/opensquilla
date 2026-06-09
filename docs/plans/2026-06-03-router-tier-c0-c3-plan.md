# Router Tier c0-c3 Migration Plan

Date: 2026-06-03

## Goal

Migrate OpenSquilla's text router tier identifiers from `t0-t3` to `c0-c3`, remove `S/M/L/XL tier` labels from user-facing/operator descriptions, and prevent Router Control prompt context from exposing tier-strength descriptions to the model.

The bundled router's route classes (`R0-R3`) remain internal. Existing configurations and historical metadata using `t0-t3` should be accepted at input boundaries and normalized to canonical `c0-c3`.

## Requirements

- Canonical text router tier ids are `c0`, `c1`, `c2`, and `c3`.
- Legacy `t0-t3` are read-only aliases at config/RPC/history/tool input boundaries.
- Product output surfaces emit only `c0-c3`, not `t0-t3`.
- `description` remains available for configuration, onboarding, diagnostics, and operator UI.
- Router Control prompt must not include tier descriptions or explicit strength labels.
- Default descriptions must not include `S tier`, `M tier`, `L tier`, or `XL tier`.
- Router behavior must remain equivalent: `R0 -> c0`, `R1 -> c1`, `R2 -> c2`, `R3 -> c3`.
- Existing routing controls, anti-downgrade behavior, large-context floors, savings display, and highest-tier compaction must continue to work.

## Non-Goals

- Do not retrain or regenerate the bundled router model artifacts.
- Do not remove internal `T0-T3` thinking-mode names in this change.
- Do not make descriptions private; only keep them out of model prompt context.
- Do not preserve `t0-t3` as canonical public output.

## Design Decisions

### Canonical Tier Module

Add one shared tier helper module, likely `src/opensquilla/squilla_router/tiers.py`, with:

- `TEXT_TIERS = ("c0", "c1", "c2", "c3")`
- `LEGACY_TEXT_TIER_ALIASES = {"t0": "c0", "t1": "c1", "t2": "c2", "t3": "c3"}`
- `ROUTE_CLASS_TO_TIER = {"R0": "c0", "R1": "c1", "R2": "c2", "R3": "c3"}`
- `TIER_TO_ROUTE_CLASS = {"c0": "R0", "c1": "R1", "c2": "R2", "c3": "R3"}`
- `normalize_text_tier(value: object) -> str | None`
- `normalize_tier_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]`
- `tier_index(value: object) -> int`
- `highest_text_tier() -> str`
- `default_text_tier() -> str`

This avoids scattered string rewrites and fixes existing assumptions such as `str(routed_tier).lstrip("t")`.

### Legacy Compatibility

Normalize legacy ids at these boundaries:

- Gateway config load and tier profile merge.
- `default_tier` values from config files, environment-derived payloads, and RPC payloads.
- Onboarding router configuration payloads.
- Router history entries before anti-downgrade and previous-tier comparison.
- Router Control target resolution for legacy requests like `tier:t3`.

After normalization, runtime metadata and responses should store/emit canonical `c*` values.

### Router Control Prompt

Change `render_router_control_prompt_block()` so the model receives only operational target ids, not descriptions:

```text
Use `router_control` only when the user explicitly asks to use a configured route or restore automatic routing.
Choose one target_id exactly from this menu; do not invent aliases or model ids.

router_control_targets=[{"target_id":"tier:c0"},{"target_id":"tier:c1"},{"target_id":"tier:c2"},{"target_id":"tier:c3"}]
```

If model-specific targets are retained, expose only `target_id`, for example `{"target_id":"model:deepseek/deepseek-v4-pro"}`. Do not include `tier`, `description`, or `thinking_level` in the prompt menu unless a later requirement proves they are necessary.

Router Control success/replay events may keep detailed metadata for observability, but model prompt context should remain minimal.

### Descriptions

Keep descriptions in config/profile data, but remove `S/M/L/XL tier` and similar explicit tier-label phrasing.

Examples:

- `DeepSeek V4 Flash route for trivial chat, short rewrites, extraction, and low-risk simple Q&A.`
- `Default balanced text model for normal agent work, coding assistance, debugging, and moderate analysis.`
- `Stronger text model for multi-step coding, structured reasoning, larger context synthesis, and harder analysis.`
- `Highest-quality text reasoning model for difficult planning, deep review, complex debugging, and high-stakes synthesis.`

Provider profiles should also avoid `fast tier`, `balanced tier`, `strong tier`, and `highest tier` phrasing. Use `route` or direct model description instead.

## Implementation Steps

1. Add shared tier helpers.
   - Add `src/opensquilla/squilla_router/tiers.py`.
   - Update `src/opensquilla/squilla_router/controller.py` to import canonical tier order.
   - Keep internal thinking-mode values unchanged.

2. Convert default router configuration.
   - Update `src/opensquilla/gateway/config.py` default tiers and provider profiles to `c0-c3`.
   - Change `SquillaRouterConfig.default_tier` to `c1`.
   - Add config validators to normalize legacy tier mappings and legacy default tier values.
   - Ensure config serialization writes canonical `c*`.

3. Convert routing runtime.
   - Update `src/opensquilla/squilla_router/v4_phase3.py` so `R0-R3` map to `c0-c3`.
   - Update `src/opensquilla/engine/steps/squilla_router.py` to use shared helper constants.
   - Change large-context floors from `t2/t3` to canonical `c2/c3`.
   - Normalize previous routing history tiers before comparisons.
   - Replace hardcoded fallback default `t1` with shared default tier.

4. Convert special tier-dependent behavior.
   - Update `src/opensquilla/engine/router_decision.py` to use `tier_index()`.
   - Update Dream model selection in `src/opensquilla/memory/dream_factory.py` to use the default canonical tier instead of hardcoded `t1`.
   - Update highest-tier compaction checks in `src/opensquilla/engine/runtime.py` from hardcoded `t3` to canonical highest text tier. Public names can remain `t3_upgrade` temporarily if renaming the feature would broaden the change too much.
   - Update auto-propose paths in `src/opensquilla/gateway/boot.py` that currently read `tiers["t3"]`.

5. Convert Router Control.
   - Update `src/opensquilla/router_control.py` target building, tier strength ordering, target resolution, and prompt rendering.
   - Accept `tier:t0-t3` as legacy input aliases but emit `tier:c0-c3`.
   - Remove descriptions from prompt menu output.
   - Remove `upgrade`/`downgrade` wording from prompt instructions where it implies tier strength.
   - Update `src/opensquilla/tools/builtin/router_control.py` description if needed.

6. Convert onboarding, CLI, and setup surfaces.
   - Update `src/opensquilla/onboarding/mutations.py`.
   - Update `src/opensquilla/onboarding/router_specs.py`.
   - Update `src/opensquilla/onboarding/flow.py`.
   - Update `src/opensquilla/onboarding/next_steps.py`.
   - Update `src/opensquilla/cli/onboard_cmd.py`.
   - Ensure setup payloads accept legacy ids but display canonical ids.

7. Convert WebUI router display.
   - Update `src/opensquilla/gateway/static/js/views/setup.js` text tiers and labels.
   - Update `src/opensquilla/gateway/static/js/views/chat.js` router-fx default tiers, sorting, comments, history handling, and placeholder handling.
   - Update `src/opensquilla/gateway/static/css/components.css` tier badge classes from `.t0/.t2/.t3` to `.c0/.c2/.c3`.

8. Update docs, examples, scripts, and tests.
   - Update `opensquilla.toml.example`.
   - Update router behavior tests.
   - Update Router Control tests.
   - Update onboarding tests.
   - Update WebUI functional tests.
   - Update live/smoke scripts that define tier configs.
   - Leave unrelated `t0` variables, scheduler anchors, Slack channel ids, and bundled tokenizer vocabulary untouched.

## Acceptance Criteria

- New default config uses `c0-c3` and `default_tier = "c1"`.
- Old config with `t0-t3` starts successfully and runtime-normalizes to `c0-c3`.
- Router classifier output maps `R0-R3` to `c0-c3`.
- `routed_tier`, `final_tier`, `base_tier`, `previous_tier`, and router events emit `c*` values after normalization.
- `RouterDecisionEvent.tier_index` returns `0-3` for `c0-c3`.
- Router Control accepts `tier:t3` as a legacy alias but emits `tier:c3`.
- Router Control prompt output contains no `description`, `S tier`, `M tier`, `L tier`, `XL tier`, or `tier:t0-t3`.
- WebUI setup and chat surfaces display `c0-c3`.
- `description` remains visible in config/operator-facing payloads where already supported.
- Highest-tier compaction still triggers on upgrades into `c3`.
- Dream/default model selection still resolves a valid default text model.

## Verification Plan

Run targeted tests first:

```bash
pytest \
  tests/test_model_router_behavior.py \
  tests/test_engine/test_router_decision_event.py \
  tests/test_engine/test_router_control.py \
  tests/test_tools/test_router_control_tool.py \
  tests/test_onboarding/test_router_specs.py \
  tests/test_onboarding/test_mutations.py \
  tests/test_onboarding/test_flow.py \
  tests/test_gateway/test_static_onboarding_views.py
```

Run high-risk behavior tests:

```bash
pytest \
  tests/test_engine/test_t3_upgrade_compaction.py \
  tests/test_memory_dream_factory.py \
  tests/functional/test_webui_browser_chat_e2e.py
```

Run static checks for prompt leakage:

```bash
rg -n "S tier|M tier|L tier|XL tier|tier:t[0-3]|router_control_targets=.*description" \
  src opensquilla.toml.example tests
```

Expected remaining matches should be limited to legacy-compat tests or irrelevant fixtures, with each remaining match reviewed.

## Risks And Mitigations

- Risk: old configs fail to route correctly.
  - Mitigation: normalize legacy `t*` config keys and defaults during config model validation.

- Risk: hidden runtime comparisons still assume `t*`.
  - Mitigation: replace all tier ordering/index logic with shared helpers and add regression tests for `c*`.

- Risk: model still infers strength from Router Control prompt.
  - Mitigation: remove descriptions and strength wording from prompt menu; expose only exact target ids.

- Risk: UI loses router history strips for old sessions.
  - Mitigation: normalize incoming `routed_tier` values in history/event handling or backend history projection.

- Risk: changing public metadata breaks downstream consumers expecting `t*`.
  - Mitigation: treat `c*` as the new canonical contract, but accept `t*` at input boundaries. Document the change in release notes.

## Implementation Decisions

- Legacy `t*` config is normalized in memory at load time; existing files are not automatically rewritten except through normal config save flows.
- Public config now uses `upgrade_to_c3_compaction_enabled`; the old `upgrade_to_t3_compaction_enabled` key is accepted as an input alias so explicit false values are preserved.
- Router Control prompt and dynamic tool schema expose only canonical route target ids (`tier:c0` through `tier:c3`), not model ids or descriptions.
