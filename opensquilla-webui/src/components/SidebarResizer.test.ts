// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  createApp,
  defineComponent,
  h,
  nextTick,
  ref,
  type App,
  type ComponentPublicInstance,
} from 'vue'
import { createI18n } from 'vue-i18n'
import SidebarResizer from './SidebarResizer.vue'

interface MountOptions {
  enabled?: boolean
  width?: number
  min?: number
  max?: number
  preference?: number
  preferenceSource?: 'compact' | 'default' | 'wide' | 'custom'
}

interface ExposedResizer {
  cancel: () => boolean
}

const mountedApps: App<Element>[] = []
let animationFrames = new Map<number, FrameRequestCallback>()
let nextAnimationFrame = 1

function i18n() {
  return createI18n({
    legacy: false,
    locale: 'en',
    messages: {
      en: {
        chrome: {
          resizeSidebar: 'Resize sidebar',
          sidebarWidthValue: 'Sidebar width {width} pixels, {preset}',
          sidebarWidthLimitedValue: 'Sidebar width {width} pixels, {preset}, limited by the window; preferred {preference} pixels',
          releaseToCollapseSidebar: 'Release to collapse sidebar',
          sidebarCollapseCanceled: 'Sidebar collapse canceled',
        },
        settings: {
          appearance: {
            sidebarWidthCompact: 'Compact',
            sidebarWidthDefault: 'Default',
            sidebarWidthWide: 'Wide',
            sidebarWidthCustom: 'Custom',
          },
        },
      },
    },
  })
}

async function mountResizer(options: MountOptions = {}) {
  const enabled = ref(options.enabled ?? true)
  const width = ref(options.width ?? 260)
  const min = ref(options.min ?? 240)
  const max = ref(options.max ?? 420)
  const preference = ref(options.preference ?? width.value)
  const preferenceSource = ref(options.preferenceSource ?? 'custom')
  const componentRef = ref<ComponentPublicInstance & ExposedResizer>()
  const calls = {
    resizeStart: vi.fn<(value: number) => void>(),
    preview: vi.fn<(value: number) => void>(),
    commit: vi.fn<(value: number) => void>(),
    reset: vi.fn<() => void>(),
    collapse: vi.fn<() => void>(),
    cancel: vi.fn<(value: number) => void>(),
    resizeEnd: vi.fn<(value: number) => void>(),
  }
  const host = document.createElement('div')
  document.body.appendChild(host)
  const Root = defineComponent(() => () => h(SidebarResizer, {
    ref: componentRef,
    enabled: enabled.value,
    width: width.value,
    min: min.value,
    max: max.value,
    preference: preference.value,
    preferenceSource: preferenceSource.value,
    onResizeStart: calls.resizeStart,
    onPreview: (value: number) => {
      calls.preview(value)
      width.value = value
    },
    onCommit: calls.commit,
    onReset: () => {
      calls.reset()
      preference.value = 260
      preferenceSource.value = 'default'
      width.value = 260
    },
    onCollapse: calls.collapse,
    onCancel: calls.cancel,
    onResizeEnd: calls.resizeEnd,
  }))
  const app = createApp(Root)
  app.use(i18n())
  app.mount(host)
  mountedApps.push(app)
  await nextTick()
  return {
    app,
    host,
    handle: () => host.querySelector<HTMLElement>('[data-testid="sidebar-resizer"]'),
    componentRef,
    enabled,
    width,
    min,
    max,
    preference,
    preferenceSource,
    calls,
  }
}

function pointerEvent(
  type: string,
  clientX: number,
  options: {
    pointerId?: number
    pointerType?: string
    isPrimary?: boolean
    button?: number
  } = {},
): PointerEvent {
  const event = new MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    clientX,
    button: options.button ?? 0,
  })
  Object.defineProperties(event, {
    pointerId: { configurable: true, value: options.pointerId ?? 7 },
    pointerType: { configurable: true, value: options.pointerType ?? 'mouse' },
    isPrimary: { configurable: true, value: options.isPrimary ?? true },
  })
  return event as unknown as PointerEvent
}

function installPointerCapture(handle: HTMLElement) {
  const captured = new Set<number>()
  const setPointerCapture = vi.fn((pointerId: number) => captured.add(pointerId))
  const releasePointerCapture = vi.fn((pointerId: number) => captured.delete(pointerId))
  const hasPointerCapture = vi.fn((pointerId: number) => captured.has(pointerId))
  Object.assign(handle, { setPointerCapture, releasePointerCapture, hasPointerCapture })
  return { setPointerCapture, releasePointerCapture, hasPointerCapture }
}

function flushAnimationFrames() {
  const pending = [...animationFrames.values()]
  animationFrames.clear()
  pending.forEach(callback => callback(performance.now()))
}

function beginDrag(handle: HTMLElement, clientX = 260) {
  const capture = installPointerCapture(handle)
  handle.dispatchEvent(pointerEvent('pointerdown', clientX))
  return capture
}

beforeEach(() => {
  animationFrames = new Map()
  nextAnimationFrame = 1
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation(callback => {
    const id = nextAnimationFrame++
    animationFrames.set(id, callback)
    return id
  })
  vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(id => {
    animationFrames.delete(id)
  })
})

afterEach(() => {
  mountedApps.splice(0).forEach(app => app.unmount())
  document.documentElement.classList.remove('is-sidebar-resizing')
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('SidebarResizer', () => {
  it('exposes a complete focusable separator contract and a constrained preferred value', async () => {
    const mounted = await mountResizer({
      width: 320,
      max: 320,
      preference: 360,
      preferenceSource: 'wide',
    })
    const handle = mounted.handle()!

    expect(handle.getAttribute('role')).toBe('separator')
    expect(handle.tabIndex).toBe(0)
    expect(handle.getAttribute('aria-label')).toBe('Resize sidebar')
    expect(handle.getAttribute('aria-orientation')).toBe('vertical')
    expect(handle.getAttribute('aria-controls')).toBe('sidebar-nav app-main')
    expect(handle.getAttribute('aria-valuemin')).toBe('240')
    expect(handle.getAttribute('aria-valuemax')).toBe('320')
    expect(handle.getAttribute('aria-valuenow')).toBe('320')
    expect(handle.getAttribute('aria-valuetext')).toBe(
      'Sidebar width 320 pixels, Wide, limited by the window; preferred 360 pixels',
    )
  })

  it('has no DOM node or tab stop while disabled', async () => {
    const mounted = await mountResizer({ enabled: false })
    expect(mounted.handle()).toBeNull()
  })

  it('accepts only primary mouse or pen input', async () => {
    const mounted = await mountResizer()
    const handle = mounted.handle()!

    const touch = pointerEvent('pointerdown', 260, { pointerType: 'touch' })
    handle.dispatchEvent(touch)
    expect(touch.defaultPrevented).toBe(false)
    handle.dispatchEvent(pointerEvent('pointerdown', 260, { button: 2 }))
    handle.dispatchEvent(pointerEvent('pointerdown', 260, { pointerType: 'pen', isPrimary: false }))
    expect(mounted.calls.resizeStart).not.toHaveBeenCalled()

    const capture = installPointerCapture(handle)
    handle.dispatchEvent(pointerEvent('pointerdown', 260, { pointerType: 'pen' }))
    expect(mounted.calls.resizeStart).toHaveBeenCalledWith(260)
    expect(capture.setPointerCapture).toHaveBeenCalledWith(7)
    handle.dispatchEvent(pointerEvent('pointercancel', 260, { pointerType: 'pen' }))
  })

  it('honors the 4px deadzone and coalesces pointer previews into one animation frame', async () => {
    const mounted = await mountResizer()
    const handle = mounted.handle()!
    const capture = beginDrag(handle)
    expect(document.documentElement.classList.contains('is-sidebar-resizing')).toBe(true)

    handle.dispatchEvent(pointerEvent('pointermove', 263))
    flushAnimationFrames()
    expect(mounted.calls.preview).not.toHaveBeenCalled()

    for (let clientX = 201; clientX <= 300; clientX += 1) {
      handle.dispatchEvent(pointerEvent('pointermove', clientX))
    }
    expect(mounted.calls.preview).not.toHaveBeenCalled()
    flushAnimationFrames()
    expect(mounted.calls.preview).toHaveBeenCalledTimes(1)
    expect(mounted.calls.preview).toHaveBeenLastCalledWith(300)

    handle.dispatchEvent(pointerEvent('pointerup', 300))
    expect(mounted.calls.commit).toHaveBeenCalledWith(300)
    expect(mounted.calls.resizeEnd).toHaveBeenCalledWith(300)
    expect(capture.releasePointerCapture).toHaveBeenCalledWith(7)
    expect(document.documentElement.classList.contains('is-sidebar-resizing')).toBe(false)
  })

  it('activates exactly at the edge of the 4px deadzone', async () => {
    const mounted = await mountResizer()
    const handle = mounted.handle()!
    beginDrag(handle)

    handle.dispatchEvent(pointerEvent('pointermove', 264))
    flushAnimationFrames()
    expect(mounted.calls.preview).toHaveBeenLastCalledWith(264)
    handle.dispatchEvent(pointerEvent('pointerup', 264))
  })

  it('treats a drag round trip as a cancel and preserves a clamped named preference', async () => {
    const mounted = await mountResizer({
      width: 320,
      max: 320,
      preference: 360,
      preferenceSource: 'wide',
    })
    const handle = mounted.handle()!
    beginDrag(handle, 320)

    handle.dispatchEvent(pointerEvent('pointermove', 280))
    flushAnimationFrames()
    handle.dispatchEvent(pointerEvent('pointermove', 320))
    flushAnimationFrames()
    handle.dispatchEvent(pointerEvent('pointerup', 320))

    expect(mounted.calls.commit).not.toHaveBeenCalled()
    expect(mounted.calls.cancel).toHaveBeenLastCalledWith(320)
    expect(mounted.preference.value).toBe(360)
    expect(mounted.preferenceSource.value).toBe('wide')
  })

  it('uses 200px/216px collapse hysteresis while keeping the actual width at 240px', async () => {
    const mounted = await mountResizer()
    const handle = mounted.handle()!
    beginDrag(handle)

    handle.dispatchEvent(pointerEvent('pointermove', 200))
    flushAnimationFrames()
    await nextTick()
    expect(handle.classList.contains('is-collapse-armed')).toBe(true)
    expect(handle.getAttribute('aria-valuenow')).toBe('240')
    expect(handle.textContent).toContain('Release to collapse sidebar')

    handle.dispatchEvent(pointerEvent('pointermove', 215))
    flushAnimationFrames()
    await nextTick()
    expect(handle.classList.contains('is-collapse-armed')).toBe(true)

    handle.dispatchEvent(pointerEvent('pointermove', 216))
    flushAnimationFrames()
    await nextTick()
    expect(handle.classList.contains('is-collapse-armed')).toBe(false)
    expect(handle.textContent).toContain('Sidebar collapse canceled')

    handle.dispatchEvent(pointerEvent('pointerup', 216))
    expect(mounted.calls.collapse).not.toHaveBeenCalled()
    expect(mounted.calls.commit).toHaveBeenCalledWith(240)
  })

  it('collapses only when pointerup occurs while the threshold is armed', async () => {
    const mounted = await mountResizer()
    const handle = mounted.handle()!
    beginDrag(handle)
    handle.dispatchEvent(pointerEvent('pointermove', 200))
    flushAnimationFrames()

    handle.dispatchEvent(pointerEvent('pointerup', 200))
    expect(mounted.calls.collapse).toHaveBeenCalledOnce()
    expect(mounted.calls.commit).not.toHaveBeenCalled()
    expect(mounted.calls.resizeEnd).toHaveBeenLastCalledWith(260)
    expect(document.documentElement.classList.contains('is-sidebar-resizing')).toBe(false)
  })

  it.each(['pointercancel', 'lostpointercapture'])(
    'rolls back on %s',
    async eventName => {
      const mounted = await mountResizer()
      const handle = mounted.handle()!
      beginDrag(handle)
      handle.dispatchEvent(pointerEvent('pointermove', 300))
      flushAnimationFrames()

      handle.dispatchEvent(pointerEvent(eventName, 300))
      expect(mounted.calls.preview).toHaveBeenLastCalledWith(260)
      expect(mounted.calls.cancel).toHaveBeenLastCalledWith(260)
      expect(mounted.calls.resizeEnd).toHaveBeenLastCalledWith(260)
      expect(mounted.calls.commit).not.toHaveBeenCalled()
      expect(document.documentElement.classList.contains('is-sidebar-resizing')).toBe(false)
    },
  )

  it('rolls back on Escape, handle blur, and window blur', async () => {
    const run = async (cancelEvent: (handle: HTMLElement) => void) => {
      const mounted = await mountResizer()
      const handle = mounted.handle()!
      beginDrag(handle)
      handle.dispatchEvent(pointerEvent('pointermove', 300))
      flushAnimationFrames()
      cancelEvent(handle)
      expect(mounted.calls.cancel).toHaveBeenLastCalledWith(260)
      expect(mounted.calls.preview).toHaveBeenLastCalledWith(260)
      mounted.app.unmount()
      mountedApps.splice(mountedApps.indexOf(mounted.app), 1)
    }

    await run(handle => handle.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'Escape', bubbles: true, cancelable: true,
    })))
    await run(handle => handle.dispatchEvent(new FocusEvent('blur')))
    await run(() => window.dispatchEvent(new Event('blur')))
  })

  it('rolls back through the exposed cancel method and on unmount', async () => {
    const exposed = await mountResizer()
    const exposedHandle = exposed.handle()!
    beginDrag(exposedHandle)
    exposedHandle.dispatchEvent(pointerEvent('pointermove', 300))
    flushAnimationFrames()
    expect(exposed.componentRef.value?.cancel()).toBe(true)
    expect(exposed.calls.cancel).toHaveBeenCalledWith(260)

    const unmounted = await mountResizer()
    const unmountedHandle = unmounted.handle()!
    beginDrag(unmountedHandle)
    unmountedHandle.dispatchEvent(pointerEvent('pointermove', 300))
    flushAnimationFrames()
    unmounted.app.unmount()
    mountedApps.splice(mountedApps.indexOf(unmounted.app), 1)
    expect(unmounted.calls.cancel).toHaveBeenCalledWith(260)
    expect(unmounted.calls.resizeEnd).toHaveBeenCalledWith(260)
    expect(document.documentElement.classList.contains('is-sidebar-resizing')).toBe(false)
  })

  it('rolls back when enabled, max, or an unrelated width changes during a drag', async () => {
    const enabledChange = await mountResizer()
    beginDrag(enabledChange.handle()!)
    enabledChange.enabled.value = false
    await nextTick()
    expect(enabledChange.calls.cancel).toHaveBeenCalledWith(260)
    expect(enabledChange.handle()).toBeNull()

    const maxChange = await mountResizer()
    beginDrag(maxChange.handle()!)
    maxChange.max.value = 400
    await nextTick()
    expect(maxChange.calls.cancel).toHaveBeenCalledWith(260)

    const widthChange = await mountResizer()
    beginDrag(widthChange.handle()!)
    widthChange.width.value = 280
    await nextTick()
    expect(widthChange.calls.cancel).toHaveBeenCalledWith(260)
  })

  it('supports Arrow, Shift+Arrow, Home, and End without moving focus', async () => {
    const mounted = await mountResizer({ width: 300 })
    const handle = mounted.handle()!
    handle.focus()

    const press = async (key: string, shiftKey = false) => {
      const event = new KeyboardEvent('keydown', {
        key,
        shiftKey,
        bubbles: true,
        cancelable: true,
      })
      handle.dispatchEvent(event)
      await nextTick()
      expect(event.defaultPrevented).toBe(true)
      expect(document.activeElement).toBe(handle)
    }

    await press('ArrowRight')
    expect(mounted.calls.commit).toHaveBeenLastCalledWith(308)
    await press('ArrowLeft', true)
    expect(mounted.calls.commit).toHaveBeenLastCalledWith(276)
    await press('Home')
    expect(mounted.calls.commit).toHaveBeenLastCalledWith(240)
    await press('End')
    expect(mounted.calls.commit).toHaveBeenLastCalledWith(420)
    expect(handle.getAttribute('aria-valuenow')).toBe('420')
  })

  it('resets to the 260px default on double click', async () => {
    const mounted = await mountResizer({
      width: 320,
      preference: 320,
      preferenceSource: 'custom',
    })
    const handle = mounted.handle()!
    handle.dispatchEvent(new MouseEvent('dblclick', {
      bubbles: true,
      cancelable: true,
      button: 0,
    }))
    await nextTick()

    expect(mounted.calls.resizeStart).toHaveBeenCalledWith(320)
    expect(mounted.calls.preview).toHaveBeenCalledWith(260)
    expect(mounted.calls.commit).not.toHaveBeenCalled()
    expect(mounted.calls.reset).toHaveBeenCalledOnce()
    expect(mounted.calls.resizeEnd).toHaveBeenCalledWith(260)
    expect(handle.getAttribute('aria-valuenow')).toBe('260')
    expect(handle.getAttribute('aria-valuetext')).toBe('Sidebar width 260 pixels, Default')
  })
})
