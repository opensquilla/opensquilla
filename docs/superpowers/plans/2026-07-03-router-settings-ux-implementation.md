# Router Settings UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the three chat composer popovers close on outside click, simplify Settings > Router to two user-facing modes, and make the router configuration read-only when single-model mode is selected.

**Architecture:** Keep all backend and wire-schema behavior unchanged. Add a small local outside-click pattern in `ChatComposer.vue`, expose setup-only router UI state from `useSetupRouterForm`, and let `SetupRouterPanel.vue` render two labels while preserving existing internal mode values such as `openrouter-mix`.

**Tech Stack:** Vue 3 `<script setup>`, vue-i18n JSON locales, Vitest with happy-dom, existing WebUI Playwright/browser validation.

---

## File Map

- Modify: `opensquilla-webui/src/components/chat/ChatComposer.vue`
  - Owns the three composer popover anchors and will close the active popover when a `pointerdown` happens outside its anchor.
- Create: `opensquilla-webui/src/components/chat/ChatComposer.popovers.test.ts`
  - Behavioral happy-dom tests for outside-click dismissal, inside-click retention, and one-popover-at-a-time behavior.
- Modify: `opensquilla-webui/src/composables/setup/useSetupRouterForm.ts`
  - Adds setup-only computed state: `routerModeChoice` and `routerConfigDisabled`.
- Modify: `opensquilla-webui/src/composables/setup/useSetupRouterForm.test.ts`
  - Verifies `openrouter-mix` remains internally preserved while the settings UI maps it to the two-option `Model routing` choice.
- Modify: `opensquilla-webui/src/components/setup/SetupRouterPanel.vue`
  - Renders only `Model routing` and `Single model`; disables dependent controls when `routerConfigDisabled` is true.
- Modify: `opensquilla-webui/src/components/setup/SetupRouterPanel.test.ts`
  - Verifies option count/labels and semantic disabled states for selects, inputs, and `ControlSwitch`.
- Modify: `opensquilla-webui/src/locales/en.json`
- Modify: `opensquilla-webui/src/locales/zh-Hans.json`
- Modify: `opensquilla-webui/src/locales/ja.json`
- Modify: `opensquilla-webui/src/locales/fr.json`
- Modify: `opensquilla-webui/src/locales/de.json`
- Modify: `opensquilla-webui/src/locales/es.json`
  - Adds the new i18n keys and keeps locale parity.

## Naming Decision

Use these two setup-page option labels:

| Locale | Enabled routing mode | Single-model mode |
| --- | --- | --- |
| English | `Model routing` | `Single model` |
| Simplified Chinese | `模型路由` | `单模型` |
| Japanese | `モデルルーティング` | `単一モデル` |
| French | `Routage des modèles` | `Modèle unique` |
| German | `Modell-Routing` | `Einzelmodell` |
| Spanish | `Enrutamiento de modelos` | `Modelo único` |

Do not expose `OpenRouter aggregated model tiers` as a selectable setup option. Existing `openrouter-mix` config remains valid internally and is shown as the enabled `Model routing` choice.

## Task 1: Add Failing Router Settings Tests

**Files:**
- Modify: `opensquilla-webui/src/components/setup/SetupRouterPanel.test.ts`
- Modify: `opensquilla-webui/src/composables/setup/useSetupRouterForm.test.ts`

- [ ] **Step 1: Update the SetupRouterPanel test helper contract**

In `opensquilla-webui/src/components/setup/SetupRouterPanel.test.ts`, replace the `panel` helper with this implementation so tests can express the new UI-only fields:

```ts
function panel(overrides: Record<string, unknown> = {}) {
  const routerMode = String(overrides.routerMode ?? 'openrouter-mix')
  return {
    routerSummary: 'Follow current provider tiers',
    routerMode,
    routerModeChoice: routerMode === 'disabled' ? 'disabled' : 'recommended',
    routerConfigDisabled: routerMode === 'disabled',
    routerDefaultTier: 'c1',
    routerVisualMode: 'real_candidates',
    routerVisualModeDirty: false,
    routerVisualModeOptions: [{ value: 'real_candidates', label: 'Real routing candidates' }],
    hasSavedProvider: true,
    ensembleProfileActive: false,
    canUseOpenrouterMix: true,
    textTiers: ['c0', 'c1'],
    tierRows: [
      {
        name: 'c0',
        provider: 'openrouter',
        model: 'deepseek/deepseek-v4-flash',
        thinkingLevel: 'high',
        supportsImage: false,
      },
    ],
    tierLabel: (tier: string) => tier,
    ...overrides,
  }
}
```

- [ ] **Step 2: Replace the old three-option label test with the new two-option test**

Replace `renders clearer router mode labels` in `opensquilla-webui/src/components/setup/SetupRouterPanel.test.ts` with:

```ts
it('renders only the two setup-level router mode choices', async () => {
  const { app, el } = await mountRouterPanel({
    routerMode: 'openrouter-mix',
    routerModeChoice: 'recommended',
    canUseOpenrouterMix: true,
  })
  const options = Array.from(el.querySelectorAll('select[name="setup_router_mode"] option'))
    .map((option) => option.textContent || '')

  expect(options).toEqual(['Model routing', 'Single model'])
  expect(options).not.toContain('OpenRouter aggregated model tiers')
  app.unmount()
})
```

- [ ] **Step 3: Add the single-model disabled-state test**

Append this test to the same `describe('SetupRouterPanel', ...)` block:

```ts
it('disables router configuration controls in single-model mode', async () => {
  const { app, el } = await mountRouterPanel({
    routerMode: 'disabled',
    routerModeChoice: 'disabled',
    routerConfigDisabled: true,
  })

  expect(el.textContent).toContain('Enable model routing to edit tier configuration.')
  expect(el.querySelector<HTMLSelectElement>('select[name="setup_router_default_tier"]')?.disabled).toBe(true)
  expect(el.querySelector<HTMLSelectElement>('select[name="setup_router_visual_mode"]')?.disabled).toBe(true)
  expect(el.querySelector<HTMLInputElement>('input[aria-label="c0 model"]')?.disabled).toBe(true)
  expect(el.querySelector<HTMLSelectElement>('select[aria-label="c0 thinking level"]')?.disabled).toBe(true)
  expect(el.querySelector<HTMLInputElement>('input[aria-label="c0 supports image"]')?.disabled).toBe(true)
  expect(el.querySelector('[role="table"]')?.getAttribute('aria-disabled')).toBe('true')

  app.unmount()
})
```

- [ ] **Step 4: Add the model-routing enabled-state test**

Append this test after the disabled-state test:

```ts
it('keeps router configuration controls editable in model-routing mode', async () => {
  const { app, el } = await mountRouterPanel({
    routerMode: 'recommended',
    routerModeChoice: 'recommended',
    routerConfigDisabled: false,
  })

  expect(el.textContent).not.toContain('Enable model routing to edit tier configuration.')
  expect(el.querySelector<HTMLSelectElement>('select[name="setup_router_default_tier"]')?.disabled).toBe(false)
  expect(el.querySelector<HTMLSelectElement>('select[name="setup_router_visual_mode"]')?.disabled).toBe(false)
  expect(el.querySelector<HTMLInputElement>('input[aria-label="c0 model"]')?.disabled).toBe(false)
  expect(el.querySelector<HTMLSelectElement>('select[aria-label="c0 thinking level"]')?.disabled).toBe(false)
  expect(el.querySelector<HTMLInputElement>('input[aria-label="c0 supports image"]')?.disabled).toBe(false)
  expect(el.querySelector('[role="table"]')?.getAttribute('aria-disabled')).toBeNull()

  app.unmount()
})
```

- [ ] **Step 5: Add router form UI mapping tests**

Append these tests to `opensquilla-webui/src/composables/setup/useSetupRouterForm.test.ts`:

```ts
it('maps openrouter-mix to the two-option model-routing UI choice without changing the payload', () => {
  const f = useSetupRouterForm()
  f.initFromConfig({ enabled: true, tier_profile: null }, {}, 'openrouter')

  const panel = makePanel(f, true)
  expect(panel.value.routerMode).toBe('openrouter-mix')
  expect(panel.value.routerModeChoice).toBe('recommended')
  expect(panel.value.routerConfigDisabled).toBe(false)
  expect(f.payload().mode).toBe('openrouter-mix')
})

it('maps disabled router config to the single-model UI choice', () => {
  const f = useSetupRouterForm()
  f.initFromConfig({ enabled: false }, {}, 'openrouter')

  const panel = makePanel(f, true)
  expect(panel.value.routerMode).toBe('disabled')
  expect(panel.value.routerModeChoice).toBe('disabled')
  expect(panel.value.routerConfigDisabled).toBe(true)
})
```

- [ ] **Step 6: Run the router tests and verify they fail**

Run:

```bash
cd /Users/wailord/Developer/projects/opensquilla/opensquilla-webui
npm run test:unit -- src/components/setup/SetupRouterPanel.test.ts src/composables/setup/useSetupRouterForm.test.ts
```

Expected before implementation: FAIL. The failures should mention missing `routerModeChoice` / `routerConfigDisabled`, old option labels, or controls not being disabled.

## Task 2: Implement Two-Option Router Settings and Disabled Controls

**Files:**
- Modify: `opensquilla-webui/src/composables/setup/useSetupRouterForm.ts`
- Modify: `opensquilla-webui/src/components/setup/SetupRouterPanel.vue`
- Modify: all six `opensquilla-webui/src/locales/*.json` files listed in the file map
- Test: `opensquilla-webui/src/components/setup/SetupRouterPanel.test.ts`
- Test: `opensquilla-webui/src/composables/setup/useSetupRouterForm.test.ts`

- [ ] **Step 1: Add setup-only computed fields in useSetupRouterForm**

In `opensquilla-webui/src/composables/setup/useSetupRouterForm.ts`, add these computed values after `const defaultTier = computed(...)`:

```ts
  const routerModeChoice = computed(() => (routerMode.value === 'disabled' ? 'disabled' : 'recommended'))
  const routerConfigDisabled = computed(() => routerMode.value === 'disabled')
```

Then add both fields to the object returned by `createPanel(context)`:

```ts
      routerModeChoice: routerModeChoice.value,
      routerConfigDisabled: routerConfigDisabled.value,
```

Keep `routerMode` in the panel contract so existing internal values and tests can still inspect `openrouter-mix`.

- [ ] **Step 2: Update the SetupRouterPanel contract**

In `opensquilla-webui/src/components/setup/SetupRouterPanel.vue`, add the new fields to `RouterPanelContract`:

```ts
  routerModeChoice: string
  routerConfigDisabled: boolean
```

No new emit type is needed; continue using `updateRouterMode`.

- [ ] **Step 3: Render only two mode options**

In `SetupRouterPanel.vue`, replace the router mode `<select>` block with this exact shape:

```vue
        <select
          class="control-input"
          :value="panel.routerModeChoice"
          name="setup_router_mode"
          :disabled="!panel.hasSavedProvider"
          @change="emit('updateRouterMode', ($event.target as HTMLSelectElement).value)"
        >
          <option value="recommended">{{ t('setup.router.modeModelRouting') }}</option>
          <option value="disabled">{{ t('setup.router.modeSingleModel') }}</option>
        </select>
```

This maps `openrouter-mix` to the displayed `recommended` choice without rewriting the stored mode unless the user changes the dropdown.

- [ ] **Step 4: Disable dependent controls when routerConfigDisabled is true**

In `SetupRouterPanel.vue`, update the dependent controls as follows:

```vue
        <select
          class="control-input"
          :value="panel.routerDefaultTier"
          name="setup_router_default_tier"
          :disabled="!panel.hasSavedProvider || panel.routerConfigDisabled"
          @change="emit('updateRouterDefaultTier', ($event.target as HTMLSelectElement).value)"
        >
```

```vue
        <select
          class="control-input"
          :value="panel.routerVisualMode"
          name="setup_router_visual_mode"
          :disabled="panel.routerConfigDisabled"
          @change="emit('updateRouterVisualMode', ($event.target as HTMLSelectElement).value)"
        >
```

```vue
    <div
      v-if="panel.hasSavedProvider"
      class="setup-tier-table-wrap"
      :class="{ 'is-disabled': panel.routerConfigDisabled }"
    >
      <p v-if="panel.routerConfigDisabled" class="setup-tier-table-wrap__note">
        {{ t('setup.router.routingDisabledHint') }}
      </p>
      <div class="setup-tier-table" role="table" :aria-disabled="panel.routerConfigDisabled ? 'true' : undefined">
        <div class="setup-tier-table__row is-head" role="row">
          <span>{{ t('setup.router.colTier') }}</span><span>{{ t('setup.router.colProvider') }}</span><span>{{ t('setup.router.colModel') }}</span><span>{{ t('setup.router.colThinking') }}</span><span>{{ t('setup.router.colImage') }}</span>
        </div>
        <div v-for="tier in panel.tierRows" :key="tier.name" class="setup-tier-table__row" role="row">
          <span class="setup-tier-table__tier">{{ panel.tierLabel(tier.name) }}</span>
          <span class="setup-tier-table__readonly" :aria-label="t('setup.router.tierProviderAria', { tier: tier.name })" :title="t('setup.router.tierProviderAria', { tier: tier.name })">{{ tier.provider || '-' }}</span>
          <input :value="tier.model" :aria-label="t('setup.router.tierModelAria', { tier: tier.name })" :placeholder="t('setup.router.tierModelAria', { tier: tier.name })" :disabled="panel.routerConfigDisabled" @input="emit('updateTierField', tier.name, 'model', ($event.target as HTMLInputElement).value)">
          <select :value="tier.thinkingLevel" :aria-label="t('setup.router.tierThinkingAria', { tier: tier.name })" :disabled="panel.routerConfigDisabled" @change="emit('updateTierField', tier.name, 'thinkingLevel', ($event.target as HTMLSelectElement).value)">
            <option v-for="v in ['', 'off', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh']" :key="v" :value="v">{{ v || '-' }}</option>
          </select>
          <ControlSwitch :checked="tier.supportsImage" :disabled="panel.routerConfigDisabled" :aria-label="t('setup.router.tierImageAria', { tier: tier.name })" @change="(v) => emit('updateTierField', tier.name, 'supportsImage', v)" />
        </div>
      </div>
    </div>
```

Keep the existing `v-else` provider-first warning unchanged.

- [ ] **Step 5: Add disabled-state styling**

Append this scoped CSS to `SetupRouterPanel.vue`:

```css
.setup-tier-table-wrap {
  display: grid;
  gap: 0.5rem;
}

.setup-tier-table-wrap.is-disabled {
  opacity: 0.72;
}

.setup-tier-table-wrap__note {
  color: var(--text-muted);
  font-size: 0.8125rem;
  margin: 0;
}
```

The disabled controls carry the semantic state; the opacity only supports visual scanning.

- [ ] **Step 6: Add locale keys in all supported locales**

Add these keys inside each locale's `setup.router` object.

`opensquilla-webui/src/locales/en.json`:

```json
"modeModelRouting": "Model routing",
"modeSingleModel": "Single model",
"routingDisabledHint": "Enable model routing to edit tier configuration."
```

`opensquilla-webui/src/locales/zh-Hans.json`:

```json
"modeModelRouting": "模型路由",
"modeSingleModel": "单模型",
"routingDisabledHint": "启用模型路由后可编辑分层配置。"
```

`opensquilla-webui/src/locales/ja.json`:

```json
"modeModelRouting": "モデルルーティング",
"modeSingleModel": "単一モデル",
"routingDisabledHint": "モデルルーティングを有効にすると階層設定を編集できます。"
```

`opensquilla-webui/src/locales/fr.json`:

```json
"modeModelRouting": "Routage des modèles",
"modeSingleModel": "Modèle unique",
"routingDisabledHint": "Activez le routage des modèles pour modifier la configuration des niveaux."
```

`opensquilla-webui/src/locales/de.json`:

```json
"modeModelRouting": "Modell-Routing",
"modeSingleModel": "Einzelmodell",
"routingDisabledHint": "Aktivieren Sie Modell-Routing, um die Stufenkonfiguration zu bearbeiten."
```

`opensquilla-webui/src/locales/es.json`:

```json
"modeModelRouting": "Enrutamiento de modelos",
"modeSingleModel": "Modelo único",
"routingDisabledHint": "Activa el enrutamiento de modelos para editar la configuración de niveles."
```

Leave `modeRecommended`, `modeDisabled`, and `modeOpenrouterMix` in place for compatibility until a separate locale cleanup removes unused keys.

- [ ] **Step 7: Run the router tests and verify they pass**

Run:

```bash
cd /Users/wailord/Developer/projects/opensquilla/opensquilla-webui
npm run test:unit -- src/components/setup/SetupRouterPanel.test.ts src/composables/setup/useSetupRouterForm.test.ts
```

Expected after implementation: PASS for all tests in both files.

- [ ] **Step 8: Commit router settings changes**

Run:

```bash
cd /Users/wailord/Developer/projects/opensquilla
git add opensquilla-webui/src/components/setup/SetupRouterPanel.vue \
  opensquilla-webui/src/components/setup/SetupRouterPanel.test.ts \
  opensquilla-webui/src/composables/setup/useSetupRouterForm.ts \
  opensquilla-webui/src/composables/setup/useSetupRouterForm.test.ts \
  opensquilla-webui/src/locales/en.json \
  opensquilla-webui/src/locales/zh-Hans.json \
  opensquilla-webui/src/locales/ja.json \
  opensquilla-webui/src/locales/fr.json \
  opensquilla-webui/src/locales/de.json \
  opensquilla-webui/src/locales/es.json
git commit -m "Improve router settings mode UX"
```

Expected: one commit containing only the router settings UI, form, locale, and test files.

## Task 3: Add Failing Composer Popover Outside-Click Tests

**Files:**
- Create: `opensquilla-webui/src/components/chat/ChatComposer.popovers.test.ts`
- Modify later: `opensquilla-webui/src/components/chat/ChatComposer.vue`

- [ ] **Step 1: Create the behavior test file**

Create `opensquilla-webui/src/components/chat/ChatComposer.popovers.test.ts` with this content:

```ts
// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from 'vitest'
import { createApp, nextTick, type App } from 'vue'
import i18n from '@/i18n'
import ChatComposer from './ChatComposer.vue'

function pointerDown(target: EventTarget) {
  target.dispatchEvent(new Event('pointerdown', { bubbles: true, composed: true }))
}

async function mountComposer() {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(ChatComposer, {
    modelValue: '',
    'onUpdate:modelValue': () => {},
    attachments: [],
    busySendMode: 'queue',
    hasSendContent: false,
    isStreaming: false,
    isNewLanding: false,
    placeholder: 'Send a message',
    sendButtonTitle: 'Send',
    runMode: 'trusted',
    allowedRunModes: ['standard', 'trusted', 'full'],
    modelRoutingMode: 'off',
    modelRoutingSettingsBusy: false,
    routerVisualEffectsEnabled: true,
    codingModeEnabled: false,
    codingModeSettingsBusy: false,
    voiceBusy: false,
    voiceRecording: false,
  })
  app.use(i18n)
  app.mount(el)
  await nextTick()
  return { app: app as App<Element>, el }
}

async function clickButton(el: HTMLElement, label: string) {
  const button = el.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)
  expect(button).toBeTruthy()
  button?.click()
  await nextTick()
}

function expectPopover(el: HTMLElement, selector: string, visible: boolean) {
  expect(Boolean(el.querySelector(selector))).toBe(visible)
}

beforeEach(() => {
  i18n.global.locale.value = 'en'
  document.body.innerHTML = ''
})

describe('ChatComposer popovers', () => {
  it.each([
    ['Composer settings', '.composer-settings'],
    ['Model routing', '.composer-model-routing'],
    ['Execution mode', '.composer-run-mode'],
  ])('closes %s on outside pointerdown', async (label, selector) => {
    const { app, el } = await mountComposer()

    await clickButton(el, label)
    expectPopover(el, selector, true)
    pointerDown(document.body)
    await nextTick()
    expectPopover(el, selector, false)

    app.unmount()
  })

  it('keeps the active popover open when clicking inside it', async () => {
    const { app, el } = await mountComposer()

    await clickButton(el, 'Composer settings')
    const popover = el.querySelector<HTMLElement>('.composer-settings')
    expect(popover).toBeTruthy()
    if (popover) pointerDown(popover)
    await nextTick()
    expectPopover(el, '.composer-settings', true)

    app.unmount()
  })

  it('keeps only one composer popover open at a time', async () => {
    const { app, el } = await mountComposer()

    await clickButton(el, 'Composer settings')
    expectPopover(el, '.composer-settings', true)
    await clickButton(el, 'Model routing')
    expectPopover(el, '.composer-settings', false)
    expectPopover(el, '.composer-model-routing', true)
    await clickButton(el, 'Execution mode')
    expectPopover(el, '.composer-model-routing', false)
    expectPopover(el, '.composer-run-mode', true)

    app.unmount()
  })
})
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```bash
cd /Users/wailord/Developer/projects/opensquilla/opensquilla-webui
npm run test:unit -- src/components/chat/ChatComposer.popovers.test.ts
```

Expected before implementation: FAIL on the outside pointerdown cases because the active popovers do not close when clicking outside.

## Task 4: Implement Composer Outside-Click Dismissal

**Files:**
- Modify: `opensquilla-webui/src/components/chat/ChatComposer.vue`
- Test: `opensquilla-webui/src/components/chat/ChatComposer.popovers.test.ts`

- [ ] **Step 1: Add anchor refs in the template**

In `ChatComposer.vue`, update the three popover anchor containers:

```vue
            <div ref="settingsAnchorEl" class="chat-settings-anchor">
```

```vue
            <div ref="modelRoutingAnchorEl" class="chat-settings-anchor">
```

```vue
            <div ref="runModeAnchorEl" class="chat-settings-anchor">
```

- [ ] **Step 2: Import lifecycle and computed helpers**

Replace the Vue import in `ChatComposer.vue` with:

```ts
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
```

- [ ] **Step 3: Add local outside-click state and helpers**

After the existing `const runModeOpen = ref(false)` line, add:

```ts
const settingsAnchorEl = ref<HTMLElement | null>(null)
const modelRoutingAnchorEl = ref<HTMLElement | null>(null)
const runModeAnchorEl = ref<HTMLElement | null>(null)

const anyPopoverOpen = computed(() => settingsOpen.value || modelRoutingOpen.value || runModeOpen.value)

function eventInsideRoot(event: PointerEvent, root: HTMLElement | null): boolean {
  if (!root) return false
  const path = typeof event.composedPath === 'function' ? event.composedPath() : []
  if (path.includes(root)) return true
  return event.target instanceof Node && root.contains(event.target)
}

function closeOpenPopoversFromOutside(event: PointerEvent) {
  if (settingsOpen.value && !eventInsideRoot(event, settingsAnchorEl.value)) {
    settingsOpen.value = false
  }
  if (modelRoutingOpen.value && !eventInsideRoot(event, modelRoutingAnchorEl.value)) {
    modelRoutingOpen.value = false
  }
  if (runModeOpen.value && !eventInsideRoot(event, runModeAnchorEl.value)) {
    runModeOpen.value = false
  }
}

watch(anyPopoverOpen, (open) => {
  if (open) {
    document.addEventListener('pointerdown', closeOpenPopoversFromOutside, true)
  } else {
    document.removeEventListener('pointerdown', closeOpenPopoversFromOutside, true)
  }
}, { immediate: true })

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', closeOpenPopoversFromOutside, true)
})
```

The listener uses capture so focus changes or child handlers do not prevent dismissal. The anchor root includes the icon button and the popover, so clicking inside either stays local.

- [ ] **Step 4: Run the composer popover tests and verify they pass**

Run:

```bash
cd /Users/wailord/Developer/projects/opensquilla/opensquilla-webui
npm run test:unit -- src/components/chat/ChatComposer.popovers.test.ts
```

Expected after implementation: PASS for outside click, inside click, and one-popover-at-a-time behavior.

- [ ] **Step 5: Run the existing composer settings source tests**

Run:

```bash
cd /Users/wailord/Developer/projects/opensquilla/opensquilla-webui
npm run test:unit -- src/components/chat/ChatComposerSettings.test.ts
```

Expected: PASS. This confirms the existing run mode and model routing source-contract tests were not broken.

- [ ] **Step 6: Commit composer popover changes**

Run:

```bash
cd /Users/wailord/Developer/projects/opensquilla
git add opensquilla-webui/src/components/chat/ChatComposer.vue \
  opensquilla-webui/src/components/chat/ChatComposer.popovers.test.ts \
  opensquilla-webui/src/components/chat/ChatComposerSettings.test.ts
git commit -m "Close composer popovers on outside click"
```

If `ChatComposerSettings.test.ts` is unchanged, omit it from `git add` before committing.

## Task 5: Full Verification and Browser QA

**Files:**
- No source edits expected in this task.

- [ ] **Step 1: Run focused unit tests**

Run:

```bash
cd /Users/wailord/Developer/projects/opensquilla/opensquilla-webui
npm run test:unit -- src/components/chat/ChatComposer.popovers.test.ts src/components/chat/ChatComposerSettings.test.ts src/components/setup/SetupRouterPanel.test.ts src/composables/setup/useSetupRouterForm.test.ts
```

Expected: PASS for all four files.

- [ ] **Step 2: Run i18n and type checks**

Run:

```bash
cd /Users/wailord/Developer/projects/opensquilla/opensquilla-webui
npm run typecheck
```

Expected: PASS. This includes `check:i18n`, architecture checks, and `vue-tsc --noEmit`.

- [ ] **Step 3: Build the WebUI**

Run:

```bash
cd /Users/wailord/Developer/projects/opensquilla/opensquilla-webui
npm run build
```

Expected: PASS and a Vite production build is generated.

- [ ] **Step 4: Run whitespace diff validation**

Run:

```bash
cd /Users/wailord/Developer/projects/opensquilla
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 5: Browser QA against the running gateway**

Use the currently running gateway at:

```text
http://127.0.0.1:18792/control/
```

Validate these states in the in-app browser:

- Open chat composer settings, click outside the popover, confirm it closes.
- Open chat composer model routing, click outside the popover, confirm it closes.
- Open chat composer execution mode, click outside the popover, confirm it closes.
- Open Settings > Router and confirm the mode dropdown has exactly `Model routing` and `Single model` in English, or `模型路由` and `单模型` in Simplified Chinese.
- Select `Single model` and confirm default text tier, router panel, tier model, thinking, and image controls are disabled.
- Select `Model routing` and confirm those controls become editable again.
- Switch language to Chinese and confirm labels and disabled helper text are localized.
- Check DevTools console or Playwright console output for no Vue warnings or runtime errors.

- [ ] **Step 6: Final commit if verification caused source adjustments**

If verification requires edits, commit the adjustments with:

```bash
cd /Users/wailord/Developer/projects/opensquilla
git add opensquilla-webui
git commit -m "Polish router settings UX verification issues"
```

If no edits were needed, skip this step and keep the two implementation commits from Task 2 and Task 4.

## Self-Review Checklist

- Spec coverage:
  - Composer popovers close on outside click: Task 3 and Task 4.
  - Settings router mode has only two user-facing options: Task 1 and Task 2.
  - i18n updated across supported locales: Task 2.
  - Single-model mode disables lower router controls semantically: Task 1 and Task 2.
  - No backend/RPC/schema changes: all tasks touch only WebUI source, tests, and locales.
- Marker scan:
  - No unresolved planning markers or unspecified implementation steps remain.
- Type consistency:
  - `routerModeChoice` and `routerConfigDisabled` are defined in `useSetupRouterForm.ts`, consumed in `SetupRouterPanel.vue`, and asserted in both unit test files.
- Risk note:
  - `openrouter-mix` remains an internal mode. It displays as `Model routing` in the setup dropdown and remains in the save payload unless the user changes the mode.
