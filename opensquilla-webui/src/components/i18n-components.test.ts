// @vitest-environment happy-dom
import { describe, it, expect, beforeEach } from 'vitest'
import { createApp, nextTick, type Component } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import i18n from '@/i18n'
import { useAppStore } from '@/stores/app'
import SettingsAppearancePanel from '@/components/settings/SettingsAppearancePanel.vue'
import LanguageSwitcher from '@/components/LanguageSwitcher.vue'

// Mount a component with the real i18n + a fresh pinia into a happy-dom node, so
// the switcher surfaces can be exercised without the SettingsDialog `loaded`
// gate (which needs a live gateway).
async function mount(Comp: Component) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const pinia = createPinia()
  setActivePinia(pinia)
  const app = createApp(Comp)
  app.use(pinia)
  app.use(i18n)
  app.mount(el)
  await nextTick()
  return { el, app }
}

const settle = () => new Promise((r) => setTimeout(r, 60))

beforeEach(() => {
  i18n.global.locale.value = 'en'
  localStorage.clear()
  document.documentElement.removeAttribute('lang')
})

describe('SettingsAppearancePanel — Language row', () => {
  it('renders a Language radiogroup with native English / 中文 labels', async () => {
    const { el } = await mount(SettingsAppearancePanel)
    const group = el.querySelector('[data-testid="settings-language-group"]')
    expect(group).toBeTruthy()
    expect(el.querySelector('[data-testid="settings-language-en"]')).toBeTruthy()
    expect(el.querySelector('[data-testid="settings-language-zh-Hans"]')).toBeTruthy()
    expect(group!.textContent).toContain('English')
    expect(group!.textContent).toContain('中文')
  })

  it('switching the radio sets the locale, persists it, and reactively localizes the panel', async () => {
    const { el } = await mount(SettingsAppearancePanel)
    const store = useAppStore()
    expect(el.querySelector('.control-section__title')!.textContent).toContain('Appearance')

    const zh = el.querySelector('[data-testid="settings-language-zh-Hans"]') as HTMLInputElement
    zh.checked = true
    zh.dispatchEvent(new Event('change', { bubbles: true }))
    await settle()
    await nextTick()

    expect(store.locale).toBe('zh-Hans')
    expect(localStorage.getItem('opensquilla-locale')).toBe('zh-Hans')
    expect(document.documentElement.getAttribute('lang')).toBe('zh-Hans')
    // section title re-renders in Chinese (reactive t())
    expect(el.querySelector('.control-section__title')!.textContent).toContain('外观')
  })
})

describe('LanguageSwitcher — topbar dropdown', () => {
  it('shows the active locale label and opens a menu of options', async () => {
    const { el } = await mount(LanguageSwitcher)
    const trigger = el.querySelector('[data-testid="language-switcher-trigger"]') as HTMLButtonElement
    expect(trigger).toBeTruthy()
    expect(trigger.textContent).toContain('English')
    expect(trigger.getAttribute('aria-expanded')).toBe('false')

    trigger.click()
    await nextTick()
    expect(trigger.getAttribute('aria-expanded')).toBe('true')
    expect(el.querySelector('[data-testid="language-option-en"]')).toBeTruthy()
    expect(el.querySelector('[data-testid="language-option-zh-Hans"]')).toBeTruthy()
  })

  it('picking 中文 sets the locale and closes the menu', async () => {
    const { el } = await mount(LanguageSwitcher)
    const store = useAppStore()
    const trigger = el.querySelector('[data-testid="language-switcher-trigger"]') as HTMLButtonElement

    trigger.click()
    await nextTick()
    ;(el.querySelector('[data-testid="language-option-zh-Hans"]') as HTMLButtonElement).click()
    await settle()
    await nextTick()

    expect(store.locale).toBe('zh-Hans')
    expect(trigger.textContent).toContain('中文')
    expect(trigger.getAttribute('aria-expanded')).toBe('false')
  })
})
