// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, h, nextTick, reactive, type App } from 'vue'
import i18n from '@/i18n'
import KnowledgeProfileSelector from './KnowledgeProfileSelector.vue'

const mountedApps: App[] = []

interface SelectorProps {
  profiles: Array<{ id: string; label: string }>
  providerDefault: string | null
  savedOverride: string | null
  draft: string | null
  saving: boolean
  disabled: boolean
  error: string
}

async function mountSelector(overrides: Partial<SelectorProps> = {}) {
  const root = document.createElement('div')
  document.body.appendChild(root)
  const onChange = vi.fn()
  const onSave = vi.fn()
  const props = reactive<SelectorProps>({
    profiles: [
      { id: 'vector', label: 'Vector' },
      { id: 'hybrid', label: 'Hybrid' },
    ],
    providerDefault: 'hybrid',
    savedOverride: null,
    draft: null,
    saving: false,
    disabled: false,
    error: '',
    ...overrides,
  })
  const app = createApp({
    render: () => h(KnowledgeProfileSelector, { ...props, onChange, onSave }),
  })
  app.use(i18n)
  app.mount(root)
  mountedApps.push(app)
  await nextTick()
  return { root, props, onChange, onSave }
}

beforeEach(() => {
  i18n.global.locale.value = 'en'
  i18n.global.mergeLocaleMessage('en', {
    rag: {
      profile: {
        title: 'Default retrieval method',
        followProvider: 'Follow provider default',
        notDeclared: 'Not declared',
        providerDefaultBadge: 'Provider default',
        activeBadge: 'Active',
        unavailable: 'The saved retrieval method is no longer available.',
        unsaved: 'Unsaved changes',
        saving: 'Saving',
        save: 'Save',
      },
    },
  })
})

afterEach(() => {
  while (mountedApps.length) mountedApps.pop()?.unmount()
  document.body.innerHTML = ''
})

describe('KnowledgeProfileSelector', () => {
  it('renders provider profiles without hard-coded profile ids', async () => {
    const { root } = await mountSelector()
    expect(root.querySelectorAll('[role="radio"]')).toHaveLength(3)
    expect(root.textContent).toContain('Vector')
    expect(root.textContent).toContain('Hybrid')
    expect(root.textContent).toContain('vector')
  })

  it('emits a draft change without saving immediately', async () => {
    const { root, onChange, onSave } = await mountSelector()
    root.querySelector<HTMLButtonElement>('[data-profile-id="vector"]')!.click()
    await nextTick()
    expect(onChange).toHaveBeenCalledWith('vector')
    expect(onSave).not.toHaveBeenCalled()
  })

  it('emits null for follow-provider and enables save only when dirty', async () => {
    const { root, onChange, onSave } = await mountSelector({ draft: 'vector' })
    root.querySelector<HTMLButtonElement>('[data-profile-id="provider-default"]')!.click()
    root.querySelector<HTMLButtonElement>('[data-testid="rag-profile-save"]')!.click()
    await nextTick()
    expect(onChange).toHaveBeenCalledWith(null)
    expect(onSave).toHaveBeenCalledTimes(1)
  })

  it('keeps save disabled when the draft matches the saved override', async () => {
    const { root, onSave } = await mountSelector()
    const save = root.querySelector<HTMLButtonElement>('[data-testid="rag-profile-save"]')!
    expect(save.disabled).toBe(true)
    save.click()
    expect(onSave).not.toHaveBeenCalled()
  })

  it('keeps exactly one selected profile in the tab order', async () => {
    const { root } = await mountSelector({ draft: 'vector' })
    const radios = Array.from(root.querySelectorAll<HTMLButtonElement>('[role="radio"]'))
    expect(radios.filter(radio => radio.tabIndex === 0)).toHaveLength(1)
    expect(root.querySelector<HTMLButtonElement>('[data-profile-id="vector"]')!.tabIndex).toBe(0)
  })

  it('moves right and down with wrapping without waiting for controlled writeback', async () => {
    const { root, onChange, onSave } = await mountSelector({ draft: 'vector' })
    const provider = root.querySelector<HTMLButtonElement>('[data-profile-id="provider-default"]')!
    const vector = root.querySelector<HTMLButtonElement>('[data-profile-id="vector"]')!
    const hybrid = root.querySelector<HTMLButtonElement>('[data-profile-id="hybrid"]')!

    vector.focus()
    vector.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    await nextTick()
    expect(document.activeElement).toBe(hybrid)
    expect(hybrid.tabIndex).toBe(0)

    // Deliberately do not write the emitted value back to draft before the next key.
    hybrid.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
    await nextTick()
    expect(document.activeElement).toBe(provider)
    expect(provider.tabIndex).toBe(0)
    expect(onChange.mock.calls).toEqual([['hybrid'], [null]])
    expect(onSave).not.toHaveBeenCalled()
  })

  it('moves left and up with wrapping without saving', async () => {
    const { root, onChange, onSave } = await mountSelector({ draft: 'vector' })
    const provider = root.querySelector<HTMLButtonElement>('[data-profile-id="provider-default"]')!
    const vector = root.querySelector<HTMLButtonElement>('[data-profile-id="vector"]')!
    const hybrid = root.querySelector<HTMLButtonElement>('[data-profile-id="hybrid"]')!

    vector.focus()
    vector.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }))
    await nextTick()
    expect(document.activeElement).toBe(provider)

    provider.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }))
    await nextTick()
    expect(document.activeElement).toBe(hybrid)
    expect(hybrid.tabIndex).toBe(0)
    expect(onChange.mock.calls).toEqual([[null], ['hybrid']])
    expect(onSave).not.toHaveBeenCalled()
  })

  it('syncs the tab stop when a controlled parent changes the draft', async () => {
    const { root, props } = await mountSelector()
    const provider = root.querySelector<HTMLButtonElement>('[data-profile-id="provider-default"]')!
    const vector = root.querySelector<HTMLButtonElement>('[data-profile-id="vector"]')!

    provider.focus()
    provider.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    await nextTick()
    expect(vector.tabIndex).toBe(0)

    props.draft = 'hybrid'
    await nextTick()
    const hybrid = root.querySelector<HTMLButtonElement>('[data-profile-id="hybrid"]')!
    const tabbable = Array.from(root.querySelectorAll<HTMLButtonElement>('[role="radio"]'))
      .filter(radio => radio.tabIndex === 0)
    expect(hybrid.getAttribute('aria-checked')).toBe('true')
    expect(tabbable).toEqual([hybrid])
  })

  it('syncs the fallback when profile updates invalidate and restore the draft', async () => {
    const { root, props } = await mountSelector({ draft: 'vector' })
    const vector = root.querySelector<HTMLButtonElement>('[data-profile-id="vector"]')!

    vector.focus()
    vector.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    await nextTick()

    props.profiles = [{ id: 'hybrid', label: 'Hybrid' }]
    await nextTick()
    const provider = root.querySelector<HTMLButtonElement>('[data-profile-id="provider-default"]')!
    let tabbable = Array.from(root.querySelectorAll<HTMLButtonElement>('[role="radio"]'))
      .filter(radio => radio.tabIndex === 0)
    expect(tabbable).toEqual([provider])

    props.profiles = [
      { id: 'vector', label: 'Vector' },
      { id: 'hybrid', label: 'Hybrid' },
    ]
    await nextTick()
    const restoredVector = root.querySelector<HTMLButtonElement>('[data-profile-id="vector"]')!
    tabbable = Array.from(root.querySelectorAll<HTMLButtonElement>('[role="radio"]'))
      .filter(radio => radio.tabIndex === 0)
    expect(restoredVector.getAttribute('aria-checked')).toBe('true')
    expect(tabbable).toEqual([restoredVector])
  })

  it('keeps a fallback tab stop when the draft profile is unavailable', async () => {
    const { root } = await mountSelector({ savedOverride: 'removed', draft: 'removed' })
    const tabbable = Array.from(root.querySelectorAll<HTMLButtonElement>('[role="radio"]'))
      .filter(radio => radio.tabIndex === 0)
    expect(tabbable).toHaveLength(1)
    expect(tabbable[0].dataset.profileId).toBe('provider-default')
  })

  it('marks a saved profile that is no longer advertised as unavailable', async () => {
    const { root } = await mountSelector({ savedOverride: 'removed', draft: 'removed' })
    expect(root.querySelector('[data-testid="rag-profile-unavailable"]')).not.toBeNull()
  })
})
