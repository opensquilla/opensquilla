# Router Settings UX Design

Date: 2026-07-03

## Goal

Tighten the WebUI router-related controls so users can close popovers naturally, understand the two router setup modes, and avoid editing router-tier controls when routing is disabled.

## Scope

- Chat composer popovers:
  - model routing
  - input settings
  - execution mode
- Setup/settings router panel:
  - router mode naming
  - router mode option count
  - disabled/read-only tier configuration when single-model mode is selected
- Locale coverage for `en`, `zh-Hans`, `ja`, `fr`, `de`, and `es`.
- Focused unit tests plus rendered browser validation.

## Non-Goals

- No backend RPC or wire-schema changes.
- No change to the chat composer three-state runtime model routing control.
- No change to completed ensemble assistant metadata or trace popovers.
- No new settings sections or routes.

## Design Decisions

### Composer Popover Dismissal

The three composer popovers should all close on outside click while keeping the existing close affordances:

- clicking the `X` closes the popover
- pressing `Esc` closes the popover
- clicking anywhere outside the active popover anchor closes the popover
- clicking inside the popover does not close it unless the clicked control explicitly selects an option
- opening one composer popover closes the other two

Implementation should attach outside-click behavior at each popover anchor, not as broad page-level state that could interfere with the chat input or other dialogs.

### Router Settings Mode Naming

The settings router page should expose only two setup modes:

- `Single model`
- `Model routing`

Chinese labels:

- `单模型`
- `模型路由`

Rationale:

- This settings page configures the router tier table. It should not expose three runtime routing states.
- `Single model` means the request goes directly to the currently configured provider/model path and the tier table is inactive.
- `Model routing` means the tier table below is active and OpenSquilla can choose from configured tiers.
- Avoid `Configurable model routing` / `可配置模型路由` because it is longer, reads like an implementation attribute, and creates translation noise. The configurability belongs in the description text.

Descriptions:

- Single model: "Send requests directly to the selected provider model."
- Model routing: "Use the tier table below to choose a model for each request."

Chinese descriptions:

- 单模型：`请求会直连当前选定的服务商模型。`
- 模型路由：`使用下方分层配置按请求选择模型。`

### Disabled Router Configuration State

When `Single model` is selected:

- the default tier control is disabled
- the router visual panel control is disabled
- all tier table inputs/selects/toggles are disabled
- the section visually dims as read-only
- a short helper note appears above the tier table:
  - English: `Enable model routing to edit tier configuration.`
  - Chinese: `启用模型路由后可编辑分层配置。`

The disabled state must be semantic, not just visual. Keyboard users should not be able to tab into disabled controls.

When `Model routing` is selected:

- all existing editable router controls behave as they do today
- provider-specific constraints still apply
- existing OpenRouter mix detection and save payload behavior remain unchanged

## Architecture

### Composer Popovers

Use a small reusable composable or local helper pattern for outside-click dismissal. The preferred shape is:

- each anchor owns a root `ref`
- when its popover is open, document `pointerdown` closes it if the event target is outside the root
- listener is removed when closed and on unmount

This keeps behavior local and testable without coupling the three popovers to a global modal manager.

### Router Setup Panel

`useSetupRouterForm` remains the source of truth for router form state.

`SetupRouterPanel.vue` should derive disabled UI from the existing mode:

- disabled/read-only when `panel.routerMode === 'disabled'`
- editable when the mode is any routing-enabled value

The saved config format can continue using existing internal values. Only the presented options and labels change.

## Data Flow

1. User chooses `Single model`.
2. Router form mode becomes the existing disabled/internal single-model value.
3. Router setup panel disables dependent controls and shows the helper note.
4. Save behavior continues to produce the current disabled router payload.

1. User chooses `Model routing`.
2. Router form mode becomes the existing enabled/default routing value.
3. Tier controls become editable.
4. Save behavior continues to include configured tiers.

## Error Handling

- If backend save fails, existing setup error/toast behavior remains unchanged.
- Disabled controls should not emit edit events.
- Outside-click handlers should tolerate missing refs and stale event targets without throwing.

## Tests

### Unit Tests

- Composer popovers:
  - opens each popover from its icon
  - closes on outside click
  - does not close on inside click
  - keeps `Esc` and `X` behavior
- Router settings:
  - mode options render only `Single model` / `Model routing`
  - i18n keys exist in all supported locales
  - choosing single-model mode disables dependent controls
  - choosing model-routing mode enables dependent controls
  - save payload remains compatible with existing router config schema

### Browser Validation

Use the running gateway at `http://127.0.0.1:18792/control/`.

Validate:

- chat composer model-routing popover outside click closes
- chat composer input settings popover outside click closes
- chat composer execution-mode popover outside click closes
- settings router page shows only two mode choices
- `Single model` disables the router controls below
- `Model routing` restores editability
- no console error or framework overlay

## Open Questions

- None. The chat composer keeps its three-state runtime control; this spec only reduces the setup router page to two setup modes.

## Implementation Checklist

1. Add focused failing tests for composer outside-click dismissal.
2. Add focused failing tests for router setup mode options and disabled state.
3. Implement local outside-click dismissal for the three composer popover anchors.
4. Update setup router mode labels/descriptions and locale strings.
5. Disable dependent router setup controls when single-model mode is active.
6. Run unit tests, typecheck, build, and browser validation.

## Spec Self-Review

- Placeholder scan: no TBD/TODO placeholders remain.
- Internal consistency: setup page uses two modes, composer runtime control remains three-state.
- Scope check: limited to WebUI interaction, labels, disabled state, tests, and generated dist if build changes it.
- Ambiguity check: `Single model` maps to the existing disabled router mode; `Model routing` maps to the existing routing-enabled configuration path.
