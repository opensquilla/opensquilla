# Design

## Source of truth
- Status: Draft
- Last refreshed: 2026-06-01
- Primary product surfaces: Vue control UI, sidebar, Chat, Sessions, Agents
- Evidence reviewed: `opensquilla-webui/src/App.vue`, `opensquilla-webui/src/views/ChatView.vue`, `opensquilla-webui/src/views/SessionsView.vue`, `src/opensquilla/gateway/static/js/views/chat.js`, `src/opensquilla/gateway/static/js/views/sessions.js`

## Brand
- Personality: precise, calm, operator-focused.
- Trust signals: predictable naming, visible state, restrained controls.
- Avoid: duplicate labels for different actions, playful toy styling, hidden side effects.

## Product goals
- Goals: make the fastest chat path obvious while keeping administrative session and agent creation explicit.
- Non-goals: turn the sidebar into a full session-management surface.
- Success signals: users can tell whether an action creates only a chat, a backend session record, or an agent.

## Personas and jobs
- Primary personas: local operators, developers, and power users managing agent runs.
- User jobs: start a quick chat, inspect prior sessions, create sessions for a specific agent, create/manage agents.
- Key contexts of use: long-lived local control UI, frequent switching between chat and management pages.

## Information architecture
- Primary navigation: sidebar quick actions, route links, recent history, bottom utility links.
- Core routes/screens: Chat is the immediate conversation surface; Sessions is the management surface for persisted session records; Agents owns agent lifecycle.
- Content hierarchy: top sidebar action starts a chat; Sessions page actions create/manage sessions.

## Design principles
- Principle 1: one label maps to one behavior.
- Principle 2: quick actions should have minimal setup; management actions should expose their side effects.
- Tradeoffs: a fast chat action can reuse the active agent, while cross-agent or new-agent creation belongs in the Sessions flow.

## Visual language
- Color: use the existing sidebar and control tokens.
- Typography: compact labels with clear verbs.
- Spacing/layout rhythm: preserve current sidebar rhythm.
- Shape/radius/elevation: reuse existing button and modal treatments.
- Motion: route-triggered chat creation should not replay stale setup animations.
- Imagery/iconography: use existing `Icon` components.

## Components
- Existing components to reuse: sidebar action button, Sessions modal, ChatView session state helpers.
- New/changed components: sidebar action label is `New chat`; Sessions primary action label is `Create session`.
- Variants and states: Chat quick action creates a blank webchat in the active agent; Sessions modal can choose or create an agent before creating a backend session.
- Token/component ownership: no new design-system layer.

## Accessibility
- Target standard: keyboard and screen-reader usable control UI.
- Keyboard/focus behavior: sidebar action remains a button; modal keeps explicit submit/cancel controls.
- Contrast/readability: follow existing token contrast.
- Screen-reader semantics: titles and button labels should describe actual behavior.
- Reduced motion and sensory considerations: no additional motion introduced.

## Responsive behavior
- Supported breakpoints/devices: current desktop and mobile sidebar behavior.
- Layout adaptations: keep the sidebar action compact in collapsed/hover states.
- Touch/hover differences: hover feedback remains decorative; click/tap behavior is identical.

## Interaction states
- Loading: Sessions modal handles RPC loading/submission.
- Empty: Chat quick action shows an empty chat; Sessions empty state offers `Create session`.
- Error: Sessions modal surfaces create failures inline.
- Success: Chat quick action lands on `/chat?session=<new-webchat-key>`; Sessions creation lands on the created session.
- Disabled: Sessions submit is disabled until an agent is selected or typed.
- Offline/slow network, if applicable: Chat quick action should not require agent-list RPC.

## Content voice
- Tone: operational and direct.
- Terminology: `New chat` means a blank conversation in the active agent. `Create session` means an explicit session-management action that may also create an agent.
- Microcopy rules: avoid using `New session` for both quick chat and managed session creation.

## Implementation constraints
- Framework/styling system: Vue 3, Vue Router, Pinia, repo-local CSS tokens.
- Design-token constraints: reuse existing tokens and icons.
- Performance constraints: sidebar action must stay instant and not fetch the agent list.
- Compatibility constraints: accept legacy `?new=1` route signals and normalize them to `?session=...`.
- Frontend selection: Vue is the default and only product-facing Control UI. The `control_ui.frontend = "legacy"` gateway setting exists only as a maintainer rollback fallback for the frozen vanilla-JS frontend, is not user-visible, and requires a gateway restart.
- Test/screenshot expectations: run typecheck/build and smoke the `/chat?newChat=1` path when possible.

## Open questions
- [ ] Should the Sessions create flow pass `kind: "webchat"` to `sessions.create`, or should managed sessions intentionally keep the backend default key shape?
