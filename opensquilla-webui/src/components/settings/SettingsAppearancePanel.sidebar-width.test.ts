// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import i18n from '@/i18n'
import { useAppStore } from '@/stores/app'
import {
  SIDEBAR_MAX_WIDTH,
  SIDEBAR_WIDTH_PRESETS,
  SIDEBAR_WIDTH_STORAGE_KEY,
} from '@/utils/sidebarLayout'
import SettingsAppearancePanel from './SettingsAppearancePanel.vue'

const mountedApps: Array<{ app: ReturnType<typeof createApp>, el: HTMLElement }> = []

function setViewport(width: number, height = 900) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width, writable: true })
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: height, writable: true })
  window.dispatchEvent(new Event('resize'))
}

async function mountPanel() {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const pinia = createPinia()
  setActivePinia(pinia)
  const app = createApp(SettingsAppearancePanel)
  app.use(pinia)
  app.use(i18n)
  app.mount(el)
  mountedApps.push({ app, el })
  await nextTick()
  return { el, store: useAppStore() }
}

function changeRadio(el: HTMLElement, source: string): HTMLInputElement {
  const radio = el.querySelector<HTMLInputElement>(`[data-testid="settings-sidebar-width-${source}"]`)!
  radio.checked = true
  radio.dispatchEvent(new Event('change', { bubbles: true }))
  return radio
}

function typeNumber(input: HTMLInputElement, value: string) {
  input.value = value
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

beforeEach(() => {
  localStorage.clear()
  i18n.global.locale.value = 'en'
  setViewport(1200)
})

afterEach(() => {
  while (mountedApps.length) {
    const mounted = mountedApps.pop()!
    mounted.app.unmount()
    mounted.el.remove()
  }
  vi.useRealTimers()
})

describe('SettingsAppearancePanel — sidebar width', () => {
  it('renders four native radio options with the canonical preset widths', async () => {
    const { el } = await mountPanel()
    const group = el.querySelector('[data-testid="settings-sidebar-width-group"]')!

    expect(group.getAttribute('role')).toBe('radiogroup')
    expect(group.textContent).toContain('Compact')
    expect(group.textContent).toContain('240px')
    expect(group.textContent).toContain('Default')
    expect(group.textContent).toContain('260px')
    expect(group.textContent).toContain('Wide')
    expect(group.textContent).toContain('360px')
    expect(group.textContent).toContain('Custom')
    expect(el.querySelectorAll<HTMLInputElement>('input[name="appearance-sidebar-width"]')).toHaveLength(4)
    expect(el.querySelector<HTMLInputElement>('[data-testid="settings-sidebar-width-default"]')!.checked).toBe(true)
  })

  it('persists named presets immediately without replacing the focused radio', async () => {
    const { el, store } = await mountPanel()
    const wide = el.querySelector<HTMLInputElement>('[data-testid="settings-sidebar-width-wide"]')!
    wide.focus()
    changeRadio(el, 'wide')
    await nextTick()

    expect(store.sidebarWidthPreference).toEqual(SIDEBAR_WIDTH_PRESETS.wide)
    expect(JSON.parse(localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY)!)).toEqual(SIDEBAR_WIDTH_PRESETS.wide)
    expect(document.activeElement).toBe(wide)

    const defaultRadio = el.querySelector<HTMLInputElement>('[data-testid="settings-sidebar-width-default"]')!
    defaultRadio.focus()
    changeRadio(el, 'default')
    await nextTick()
    expect(store.sidebarWidthPreference).toEqual(SIDEBAR_WIDTH_PRESETS.default)
    expect(localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY)).toBeNull()
    expect(document.activeElement).toBe(defaultRadio)
  })

  it('keeps custom edits local until Apply and rejects values outside the global range', async () => {
    const { el, store } = await mountPanel()
    changeRadio(el, 'custom')
    await nextTick()
    expect(store.sidebarWidthPreference).toEqual(SIDEBAR_WIDTH_PRESETS.default)

    const input = el.querySelector<HTMLInputElement>('[data-testid="settings-sidebar-width-value"]')!
    const apply = el.querySelector<HTMLButtonElement>('[data-testid="settings-sidebar-width-apply"]')!
    expect(input.disabled).toBe(false)

    typeNumber(input, String(SIDEBAR_MAX_WIDTH + 1))
    await nextTick()
    expect(input.getAttribute('aria-invalid')).toBe('true')
    expect(apply.disabled).toBe(true)

    typeNumber(input, '321')
    await nextTick()
    expect(apply.disabled).toBe(false)
    apply.focus()
    apply.click()
    await nextTick()

    expect(store.sidebarWidthPreference).toEqual({ version: 1, width: 321, source: 'custom' })
    expect(document.activeElement).toBe(apply)
  })

  it('repeats a held step after 400ms and every 60ms without saving before Apply', async () => {
    vi.useFakeTimers()
    const { el, store } = await mountPanel()
    changeRadio(el, 'custom')
    await nextTick()

    const input = el.querySelector<HTMLInputElement>('[data-testid="settings-sidebar-width-value"]')!
    const increase = el.querySelector<HTMLButtonElement>('[data-testid="settings-sidebar-width-increase"]')!
    increase.focus()
    increase.dispatchEvent(new PointerEvent('pointerdown', {
      bubbles: true,
      button: 0,
      pointerId: 7,
    }))
    await nextTick()
    expect(input.value).toBe('261')

    vi.advanceTimersByTime(399)
    await nextTick()
    expect(input.value).toBe('261')

    vi.advanceTimersByTime(121)
    await nextTick()
    expect(input.value).toBe('264')
    expect(document.activeElement).toBe(increase)

    increase.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 7 }))
    vi.advanceTimersByTime(180)
    await nextTick()
    expect(input.value).toBe('264')
    expect(store.sidebarWidthPreference).toEqual(SIDEBAR_WIDTH_PRESETS.default)
  })

  it('explains the active layout and a viewport-clamped desktop preference', async () => {
    setViewport(1000)
    const { el, store } = await mountPanel()
    store.setSidebarWidthPreference({ version: 1, width: 420, source: 'custom' })
    await nextTick()

    const status = el.querySelector<HTMLElement>('[data-testid="settings-sidebar-width-status"]')!
    expect(status.textContent).toContain('Resizable')
    expect(status.textContent).toContain('Saved 420px')
    expect(status.textContent).toContain('300px')

    setViewport(900)
    await nextTick()
    expect(status.textContent).toContain('Compact layout')
    expect(status.textContent).toContain('260px')
    expect(status.textContent).toContain('420px')
  })

  it('localizes the new setting in Simplified Chinese', async () => {
    const { el, store } = await mountPanel()
    await store.setLocale('zh-Hans')
    await nextTick()
    const group = el.querySelector('[data-testid="settings-sidebar-width-group"]')!
    expect(el.textContent).toContain('侧边栏宽度')
    expect(group.textContent).toContain('紧凑')
    expect(group.textContent).toContain('默认')
    expect(group.textContent).toContain('自定义')
  })
})
