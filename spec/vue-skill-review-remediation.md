# Vue Skill Review Remediation Spec

Status: Draft
Owner: Frontend
Last updated: 2026-06-03
Scope: `opensquilla-webui/`
Source: Vue / Vue best-practices / Pinia / Vue Router review

## Background

The current Vue frontend passes `vue-tsc --noEmit`, but the review found several places where the implementation does not match Vue best-practice boundaries. These are not all immediate production bugs. They are mostly maintainability and state-flow risks that will become expensive as the Web UI grows.

The most important pattern is that route-level views are doing too much. `ChatView.vue` is the highest-risk file because it owns rendering, RPC event handling, session state, streaming state, markdown rendering, artifacts, attachments, keyboard/document listeners, and large scoped CSS in one SFC.

## Goals

- Keep Vue Router as the single source of truth for chat route state.
- Keep route-level components as composition surfaces, not full feature implementations.
- Replace manual DOM mutation with declarative reactive state.
- Improve protocol typing where UI correctness depends on backend event shape.
- Make viewport-dependent UI reactive or CSS-driven.

## Non-Goals

- Do not redesign the whole chat UI.
- Do not change backend RPC/event contracts as part of this remediation.
- Do not introduce new dependencies for the first pass.
- Do not rewrite `ChatView.vue` in one large change.
- Do not treat this spec as a blocker for unrelated frontend bug fixes.

## Constraints

- All implementation work should stay inside `opensquilla-webui/` unless a backend contract gap is proven.
- Every frontend change must pass:

```bash
cd opensquilla-webui && npm run typecheck
cd opensquilla-webui && npm run build
```

- After any visible frontend change, rebuild the Vite output served by the gateway.
- Preserve existing behavior before refactoring. Add focused regression tests or small smoke checks before risky extraction work.

## Remediation Items

### VUE-1: Route state must not bypass Vue Router

Priority: P1
Risk: Medium
Files:
- `opensquilla-webui/src/views/ChatView.vue`
- `opensquilla-webui/src/App.vue`

Current behavior:

- `ChatView.vue` persists the session and rewrites the URL using `history.replaceState`.
- `App.vue` derives the current session from `useRoute().query.session`.
- Because `history.replaceState` does not update Vue Router's reactive route object, UI that depends on `useRoute()` can lag behind the browser URL.

Required behavior:

- Chat session URL changes must go through `router.replace()` or `router.push()`.
- `sessionKey` and `route.query.session` must converge after creating, switching, or restoring a chat.
- Do not read `window.location.search` for route state when `useRoute()` can provide the same value.

Implementation notes:

- Replace direct `history.replaceState(null, '', url)` in `persistSession()` with a router update path.
- Keep `localStorage` persistence, but do not let it override an explicit route query.
- Avoid a watch loop between `persistSession()` and the route watcher.

Acceptance criteria:

- Opening `/chat` without a session creates or restores a session and the reactive route query updates to the same key.
- Sidebar current-session highlighting updates immediately after a new chat is created.
- Switching sessions from the sidebar updates both `sessionKey` and `route.query.session`.
- Browser back/forward behavior remains reasonable for explicit session navigation.

### VUE-2: Split `ChatView.vue` into feature components and composables

Priority: P1
Risk: Medium
Files:
- `opensquilla-webui/src/views/ChatView.vue`
- new files under `opensquilla-webui/src/components/chat/`
- new files under `opensquilla-webui/src/composables/chat/`

Current behavior:

- `ChatView.vue` is over 6000 lines.
- It mixes route composition, UI rendering, stream state, RPC subscriptions, artifact handling, attachment handling, markdown rendering, session persistence, keyboard/document listeners, timers, and scoped CSS.

Required behavior:

- `ChatView.vue` should become a route-level composition surface.
- Feature state and side effects should move into composables.
- Repeated or complex UI sections should move into child components with explicit props and emits.

Recommended extraction order:

1. Extract pure utilities first:
   - markdown rendering
   - artifact labeling/download URL helpers
   - router decision formatting
   - session-key helpers
2. Extract presentational components:
   - `ChatMessageList.vue`
   - `ChatMessageBubble.vue`
   - `ToolTimeline.vue`
   - `RouterFxStrip.vue`
   - `ArtifactChip.vue`
   - `ChatComposer.vue`
3. Extract stateful composables:
   - `useChatSession()`
   - `useChatStream()`
   - `useChatAttachments()`
   - `useChatKeyboard()`
   - `useChatArtifacts()`

Component contract direction:

- Props down: rendered message data, streaming state, attachment list, composer state.
- Events up: send, stop, edit, regenerate, copy, attach, remove attachment, toggle tool group.
- RPC calls stay in composables or stores, not presentational components.

Acceptance criteria:

- `ChatView.vue` no longer owns full message markup, composer markup, tool timeline markup, and stream subscription logic at the same time.
- Extracted components use `<script setup lang="ts">`.
- Extracted components have typed `defineProps` and `defineEmits`.
- No behavior changes in:
  - normal send
  - streaming response
  - tool call display
  - artifact download
  - attachment upload
  - session switching
- `npm run typecheck` and `npm run build` pass after each extraction batch.

### VUE-3: Replace direct DOM mutation in Cron run actions

Priority: P1
Risk: Medium
Files:
- `opensquilla-webui/src/views/CronView.vue`

Current behavior:

- `runJob()` reads and writes `event.currentTarget.innerHTML`.
- It directly mutates `button.disabled`.
- Vue owns that DOM subtree, so reactive re-renders during the RPC call can desynchronize the DOM and the component state.

Required behavior:

- Track running jobs in reactive state.
- Render button loading text, spinner, and disabled state declaratively.
- Do not assign `innerHTML` from script.

Implementation sketch:

```ts
const runningJobIds = ref<Set<string>>(new Set())

function isJobRunning(id: string): boolean {
  return runningJobIds.value.has(id)
}

async function runJob(id: string) {
  runningJobIds.value = new Set(runningJobIds.value).add(id)
  try {
    await rpc.call('cron.run', { id })
  } finally {
    const next = new Set(runningJobIds.value)
    next.delete(id)
    runningJobIds.value = next
  }
}
```

Acceptance criteria:

- Running one job disables only that job's run button.
- Spinner/text is rendered through template branches, not `innerHTML`.
- If the job list refreshes while the RPC call is in flight, the button state remains correct.
- `npm run typecheck` and `npm run build` pass.

### VUE-4: Type critical RPC and session payloads

Priority: P1
Risk: Medium
Files:
- `opensquilla-webui/src/lib/rpc.ts`
- `opensquilla-webui/src/stores/rpc.ts`
- `opensquilla-webui/src/views/ChatView.vue`
- `opensquilla-webui/src/composables/useSessions.ts`
- optional new file: `opensquilla-webui/src/types/rpc.ts`

Current behavior:

- The project uses `strict: true`, but critical protocol areas rely heavily on `any`.
- Chat events, router decisions, artifacts, usage, timeline segments, and session normalization are weakly typed.
- This makes backend contract regressions easy to miss at compile time.

Required behavior:

- Define narrow interfaces for high-value event payloads.
- Keep unknown backend fields possible, but isolate them behind typed normalization functions.
- Avoid `call<any>()` for known RPC methods.

Recommended type surfaces:

```ts
interface RpcMethodMap {
  'sessions.list': {
    params: { limit?: number; view?: string }
    result: { sessions?: RawSessionItem[]; keys?: RawSessionItem[] }
  }
  'agents.list': {
    params: Record<string, never>
    result: { agents?: AgentOption[] }
  }
}

interface RpcEventMap {
  'session.event.text_delta': TextDeltaPayload
  'session.event.tool_use_start': ToolUsePayload
  'session.event.tool_use_delta': ToolDeltaPayload
  'session.event.tool_result': ToolResultPayload
  'session.event.artifact': ArtifactPayload
  'session.event.router_decision': RouterDecisionPayload
}
```

Acceptance criteria:

- Known RPC calls in App/session/chat code no longer use `call<any>()`.
- Chat event handlers receive typed payloads for the common event path.
- `RawSessionItem` replaces broad `any` fields with `unknown` or explicit nested interfaces where feasible.
- Runtime fallback behavior for unknown legacy backend fields is preserved.
- `npm run typecheck` and `npm run build` pass.

### VUE-5: Make viewport-dependent UI reactive or CSS-driven

Priority: P2
Risk: Low
Files:
- `opensquilla-webui/src/views/ChatView.vue`

Current behavior:

- `composerPlaceholder` reads `window.innerWidth` inside a computed.
- Window resize does not update that computed because `window.innerWidth` is not reactive.

Required behavior:

- Use a reactive viewport/media-query state, or remove the JS branch and let layout/CSS handle mobile presentation.

Implementation options:

- Option A: add a tiny local composable:

```ts
function useMediaQuery(query: string) {
  const matches = ref(false)
  let mql: MediaQueryList | null = null
  let handler: ((event: MediaQueryListEvent) => void) | null = null

  onMounted(() => {
    mql = window.matchMedia(query)
    matches.value = mql.matches
    handler = event => { matches.value = event.matches }
    mql.addEventListener('change', handler)
  })

  onUnmounted(() => {
    if (mql && handler) mql.removeEventListener('change', handler)
  })

  return matches
}
```

- Option B: use one placeholder string and handle compact mobile layout with CSS.

Acceptance criteria:

- Resizing desktop to mobile width updates the composer placeholder if JS branching remains.
- Listener cleanup is present if a media query listener is introduced.
- `npm run typecheck` and `npm run build` pass.

## Suggested Delivery Plan

1. VUE-1: fix router-state consistency first because it has direct UI correctness impact.
2. VUE-3 and VUE-5: small, low-risk declarative Vue fixes.
3. VUE-4: introduce typed protocol surfaces incrementally.
4. VUE-2: split `ChatView.vue` in small batches after behavior is locked.

## Verification Matrix

| Area | Check |
| --- | --- |
| Type safety | `cd opensquilla-webui && npm run typecheck` |
| Build output | `cd opensquilla-webui && npm run build` |
| Chat route state | create chat, switch chat, refresh, verify sidebar current item |
| Chat stream | send prompt, observe text deltas, tool timeline, terminal state |
| Cron run action | run a job and refresh list during in-flight state |
| Responsive composer | resize viewport across 480px threshold |

## Known Good State Before Remediation

`npm run typecheck` passed on 2026-06-03 before this spec was written. The review did not run full browser QA or `npm run build` because no code changes were made during the review pass.
