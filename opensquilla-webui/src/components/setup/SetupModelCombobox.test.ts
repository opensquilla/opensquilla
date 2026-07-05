// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import i18n from '@/i18n'
import SetupModelCombobox from './SetupModelCombobox.vue'
import type { DiscoveredModel } from '@/composables/setup/useSetupProviderForm'

const MODELS: DiscoveredModel[] = [
  {
    id: 'test-vendor/alpha',
    name: 'Alpha',
    contextWindow: 262144,
    maxOutputTokens: 16384,
    capabilities: ['chat', 'tools'],
    pricing: null,
    capabilitySource: 'provider',
  },
  {
    id: 'test-vendor/beta-vision',
    name: 'Beta Vision',
    contextWindow: 128000,
    maxOutputTokens: null,
    capabilities: ['chat', 'vision'],
    pricing: null,
    capabilitySource: 'synthesized',
  },
]

const FIELD = { name: 'model', label: 'Model' }

async function mountCombobox(props: Record<string, unknown> = {}) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(SetupModelCombobox, {
    field: FIELD,
    value: '',
    models: MODELS,
    modelSource: 'live',
    ...props,
  })
  app.use(i18n)
  app.mount(el)
  await nextTick()
  return { app, el }
}

async function openList(el: HTMLElement) {
  const input = el.querySelector<HTMLInputElement>('input[role="combobox"]')!
  input.dispatchEvent(new Event('focus'))
  await nextTick()
  return input
}

beforeEach(() => {
  i18n.global.locale.value = 'en'
  document.body.innerHTML = ''
})

describe('SetupModelCombobox', () => {
  it('is a plain text input until opened — free text always works', async () => {
    const { app, el } = await mountCombobox({ value: 'my/custom-model' })
    const input = el.querySelector<HTMLInputElement>('input[name="setup_provider_model"]')
    expect(input?.value).toBe('my/custom-model')
    expect(el.querySelector('[role="listbox"]')).toBeNull()
    app.unmount()
  })

  it('opens on focus and lists models with compact context window and capability hints', async () => {
    const { app, el } = await mountCombobox()
    await openList(el)

    const rows = Array.from(el.querySelectorAll('[role="option"]'))
    expect(rows).toHaveLength(2)
    expect(rows[0].textContent).toContain('test-vendor/alpha')
    expect(rows[0].textContent).toContain('262k')
    expect(rows[0].textContent).toContain('tools')
    expect(rows[0].textContent).not.toContain('chat') // baseline capability is noise
    expect(rows[1].textContent).toContain('128k')
    expect(rows[1].textContent).toContain('vision')
    app.unmount()
  })

  it('filters rows against the typed value and offers a free-text escape row', async () => {
    const { app, el } = await mountCombobox({ value: 'beta' })
    await openList(el)

    const rows = Array.from(el.querySelectorAll('[role="option"]'))
    // one match + the "use what you typed" escape row
    expect(rows).toHaveLength(2)
    expect(rows[0].textContent).toContain('test-vendor/beta-vision')
    expect(rows[1].textContent).toContain('Use "beta"')
    app.unmount()
  })

  it('emits update with the model id when a row is clicked and closes the list', async () => {
    const onUpdate = vi.fn()
    const { app, el } = await mountCombobox({ onUpdate })
    await openList(el)

    const rows = el.querySelectorAll<HTMLButtonElement>('[role="option"]')
    rows[1].click()
    await nextTick()

    expect(onUpdate).toHaveBeenCalledWith('test-vendor/beta-vision')
    expect(el.querySelector('[role="listbox"]')).toBeNull()
    app.unmount()
  })

  it('clicking the free-text escape row keeps the typed value and just closes', async () => {
    const onUpdate = vi.fn()
    const { app, el } = await mountCombobox({ value: 'my/custom-model', onUpdate })
    await openList(el)

    const rows = Array.from(el.querySelectorAll<HTMLButtonElement>('[role="option"]'))
    const escapeRow = rows[rows.length - 1]
    expect(escapeRow.textContent).toContain('Use "my/custom-model"')
    escapeRow.click()
    await nextTick()

    expect(onUpdate).not.toHaveBeenCalled() // the typed value is already the field value
    expect(el.querySelector('[role="listbox"]')).toBeNull()
    app.unmount()
  })

  it('typing emits update and reopens the list', async () => {
    const onUpdate = vi.fn()
    const { app, el } = await mountCombobox({ onUpdate })
    const input = el.querySelector<HTMLInputElement>('input[role="combobox"]')!
    input.value = 'alp'
    input.dispatchEvent(new Event('input'))
    await nextTick()

    expect(onUpdate).toHaveBeenCalledWith('alp')
    expect(el.querySelector('[role="listbox"]')).toBeTruthy()
    app.unmount()
  })

  it('selects the active row with Enter after arrow-key navigation', async () => {
    const onUpdate = vi.fn()
    const { app, el } = await mountCombobox({ onUpdate })
    const input = await openList(el)

    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown' }))
    await nextTick()
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await nextTick()

    expect(onUpdate).toHaveBeenCalledWith('test-vendor/alpha')
    app.unmount()
  })

  it('shows provenance once in a muted footer, not per-row badges', async () => {
    const { app, el } = await mountCombobox()
    await openList(el)

    const footers = Array.from(el.querySelectorAll('.setup-model-combobox__footer'))
    const provenance = footers.map(f => f.textContent || '').join(' ')
    expect(provenance).toContain('provider, synthesized')
    // per-row rows never carry the capabilitySource enum
    const rows = Array.from(el.querySelectorAll('[role="option"]'))
    expect(rows.every(row => !(row.textContent || '').includes('synthesized'))).toBe(true)
    app.unmount()
  })
})
