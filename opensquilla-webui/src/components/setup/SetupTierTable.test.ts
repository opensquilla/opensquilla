// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, defineComponent, h, nextTick, ref } from 'vue'
import i18n from '@/i18n'
import SetupTierTable from './SetupTierTable.vue'
import type {
  DiscoveredModel,
  DiscoveredModelsByProvider,
} from '@/composables/setup/useSetupProviderForm'

const ROWS = [
  {
    name: 'c0',
    provider: 'openrouter',
    model: 'deepseek/deepseek-v4-flash',
    thinkingLevel: 'high',
    supportsImage: false,
  },
  {
    name: 'c1',
    provider: 'openai',
    model: 'test-model-1',
    thinkingLevel: '',
    supportsImage: true,
  },
]

const DISCOVERED: DiscoveredModel[] = [
  {
    id: 'test-vendor/alpha',
    name: 'Alpha',
    contextWindow: 262144,
    maxOutputTokens: 16384,
    capabilities: ['chat'],
    pricing: null,
    capabilitySource: 'provider',
  },
]

const TOKENRHYTHM_DISCOVERED: DiscoveredModel[] = [
  {
    id: 'deepseek-v4-flash',
    name: 'DeepSeek V4 Flash',
    contextWindow: 128000,
    maxOutputTokens: 16384,
    capabilities: ['chat', 'tools'],
    pricing: null,
    capabilitySource: 'provider',
  },
]

async function mountTable(props: Record<string, unknown> = {}, listeners: Record<string, unknown> = {}) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(SetupTierTable, {
    rows: ROWS,
    tierLabel: (tier: string) => tier,
    ...props,
    ...listeners,
  })
  app.use(i18n)
  app.mount(el)
  await nextTick()
  return { app, el }
}

async function mountTableWithAsyncCatalog() {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const rows = ref(ROWS.map(row => ({ ...row })))
  const modelsByProvider = ref<DiscoveredModelsByProvider>({})
  const host = defineComponent({
    setup() {
      return () => h(SetupTierTable, {
        rows: rows.value,
        tierLabel: (tier: string) => tier,
        modelsByProvider: modelsByProvider.value,
        onUpdateTierField: (name: string, key: string, value: string | boolean) => {
          const row = rows.value.find(item => item.name === name)
          if (row && key === 'model') row.model = String(value)
        },
      })
    },
  })
  const app = createApp(host)
  app.use(i18n)
  app.mount(el)
  await nextTick()
  return { app, el, modelsByProvider }
}

beforeEach(() => {
  i18n.global.locale.value = 'en'
  document.body.innerHTML = ''
})

describe('SetupTierTable — render parity with the old inline Router table', () => {
  it('renders the same table structure: head row, read-only provider, editable model/thinking/image', async () => {
    const { app, el } = await mountTable()

    const table = el.querySelector('[role="table"]')
    expect(table).toBeTruthy()
    expect(table?.getAttribute('aria-disabled')).toBeNull()
    const head = el.querySelector('.setup-tier-table__row.is-head')
    expect(head?.textContent).toContain('Tier')
    expect(head?.textContent).toContain('Request entry')
    expect(head?.textContent).toContain('Model')
    expect(head?.textContent).toContain('Thinking')
    expect(head?.textContent).toContain('Image')

    const requestEntry = el.querySelector('[aria-label="c0 request entry"]')
    expect(requestEntry?.tagName).toBe('SPAN')
    expect(requestEntry?.textContent).toBe('openrouter')

    const model = el.querySelector<HTMLInputElement>('input[aria-label="c0 model"]')
    expect(model?.value).toBe('deepseek/deepseek-v4-flash')
    expect(model?.disabled).toBe(false)
    expect(el.querySelector<HTMLSelectElement>('select[aria-label="c0 thinking level"]')?.value).toBe('high')
    expect(el.querySelector<HTMLInputElement>('input[aria-label="c0 supports image"]')).toBeTruthy()

    app.unmount()
  })

  it('emits updateTierField from the model input', async () => {
    const onUpdateTierField = vi.fn()
    const { app, el } = await mountTable({}, { onUpdateTierField })

    const model = el.querySelector<HTMLInputElement>('input[aria-label="c0 model"]')!
    model.value = 'new-model'
    model.dispatchEvent(new Event('input', { bubbles: true }))

    expect(onUpdateTierField).toHaveBeenCalledWith('c0', 'model', 'new-model')
    app.unmount()
  })

  it('disables every editable control and marks the table aria-disabled', async () => {
    const { app, el } = await mountTable({ disabled: true })

    expect(el.querySelector('[role="table"]')?.getAttribute('aria-disabled')).toBe('true')
    expect(el.querySelector<HTMLInputElement>('input[aria-label="c0 model"]')?.disabled).toBe(true)
    expect(el.querySelector<HTMLSelectElement>('select[aria-label="c0 thinking level"]')?.disabled).toBe(true)
    expect(el.querySelector<HTMLInputElement>('input[aria-label="c0 supports image"]')?.disabled).toBe(true)

    app.unmount()
  })
})

describe('SetupTierTable — combobox swap condition', () => {
  it('upgrades the model cell to the combobox only where the tier provider matches the discovery provider', async () => {
    const { app, el } = await mountTable({
      modelsByProvider: {
        openrouter: { models: DISCOVERED, source: 'live' },
      },
    })

    // c0 routes through openrouter (matches) → combobox.
    expect(el.querySelector('input[role="combobox"][aria-label="c0 model"]')).toBeTruthy()
    expect(el.querySelector('input[aria-label="c0 model"]:not([role="combobox"])')).toBeNull()
    // c1 routes through openai (mismatch) → plain free-text input.
    const c1 = el.querySelector<HTMLInputElement>('input[aria-label="c1 model"]')
    expect(c1?.getAttribute('role')).toBeNull()

    app.unmount()
  })

  it('matches tier providers without case or surrounding-whitespace sensitivity', async () => {
    const { app, el } = await mountTable({
      rows: [
        { ...ROWS[0], provider: ' OpenRouter ' },
        ROWS[1],
      ],
      modelsByProvider: {
        openrouter: { models: DISCOVERED, source: 'live' },
      },
    })

    expect(el.querySelector('input[role="combobox"][aria-label="c0 model"]')).toBeTruthy()
    expect(el.querySelector('input[role="combobox"][aria-label="c1 model"]')).toBeNull()
    app.unmount()
  })

  it('uses each row provider catalog independently in a mixed-provider table', async () => {
    const rows = [
      ROWS[0],
      { ...ROWS[1], provider: 'tokenrhythm', model: 'deepseek-v4-pro' },
      { ...ROWS[1], name: 'c2', provider: 'anthropic', model: 'claude-sonnet-4' },
    ]
    const { app, el } = await mountTable({
      rows,
      modelsByProvider: {
        openrouter: { models: DISCOVERED, source: 'live' },
        tokenrhythm: { models: TOKENRHYTHM_DISCOVERED, source: 'live' },
        anthropic: { models: [], source: 'none' },
      },
    })

    expect(el.querySelector('input[role="combobox"][aria-label="c0 model"]')).toBeTruthy()
    expect(el.querySelector('input[role="combobox"][aria-label="c1 model"]')).toBeTruthy()
    expect(el.querySelector('input[role="combobox"][aria-label="c2 model"]')).toBeNull()
    expect(el.querySelector<HTMLInputElement>('input[aria-label="c2 model"]')?.value).toBe('claude-sonnet-4')

    app.unmount()
  })

  it('preserves the focused input and typed value when an async catalog arrives', async () => {
    const { app, el, modelsByProvider } = await mountTableWithAsyncCatalog()
    const before = el.querySelector<HTMLInputElement>('input[aria-label="c0 model"]')!
    before.focus()
    before.value = 'user/model-being-typed'
    before.dispatchEvent(new Event('input', { bubbles: true }))
    await nextTick()

    modelsByProvider.value = {
      openrouter: { models: DISCOVERED, source: 'live' },
    }
    await nextTick()

    const after = el.querySelector<HTMLInputElement>('input[aria-label="c0 model"]')!
    expect(after).toBe(before)
    expect(document.activeElement).toBe(after)
    expect(after.value).toBe('user/model-being-typed')
    expect(after.getAttribute('role')).toBe('combobox')
    app.unmount()
  })

  it('keeps plain inputs when a provider catalog is empty or absent', async () => {
    const none = await mountTable({
      modelsByProvider: { openrouter: { models: [], source: 'none' } },
    })
    expect(none.el.querySelector('input[role="combobox"]')).toBeNull()
    none.app.unmount()

    const absent = await mountTable({ modelsByProvider: {} })
    expect(absent.el.querySelector('input[role="combobox"]')).toBeNull()
    absent.app.unmount()
  })

  it('fails closed to free text when a non-live source unexpectedly includes models', async () => {
    const { app, el } = await mountTable({
      modelsByProvider: {
        openrouter: { models: DISCOVERED, source: 'none' },
      },
    })

    expect(el.querySelector('input[role="combobox"]')).toBeNull()
    expect(el.querySelector<HTMLInputElement>('input[aria-label="c0 model"]')?.value).toBe(
      'deepseek/deepseek-v4-flash',
    )
    app.unmount()
  })

  it('never renders a combobox while the table is disabled', async () => {
    const { app, el } = await mountTable({
      modelsByProvider: { openrouter: { models: DISCOVERED, source: 'live' } },
      disabled: true,
    })
    expect(el.querySelector('input[role="combobox"]')).toBeNull()
    expect(el.querySelector<HTMLInputElement>('input[aria-label="c0 model"]')?.disabled).toBe(true)
    app.unmount()
  })
})

describe('SetupTierTable — readonly preview mode', () => {
  it('renders model and thinking as text with no editable inputs', async () => {
    const { app, el } = await mountTable({ readonly: true })

    const model = el.querySelector('[aria-label="c0 model"]')
    expect(model?.tagName).toBe('SPAN')
    expect(model?.textContent).toBe('deepseek/deepseek-v4-flash')
    expect(el.querySelector('[aria-label="c0 thinking level"]')?.tagName).toBe('SPAN')
    expect(el.querySelectorAll('select').length).toBe(0)
    expect(el.querySelector('input[role="combobox"]')).toBeNull()
    // The image switch stays visible (disabled) so the preview shows state.
    expect(el.querySelector<HTMLInputElement>('input[aria-label="c0 supports image"]')?.disabled).toBe(true)

    app.unmount()
  })
})
