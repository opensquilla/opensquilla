<template>
  <div
    v-if="enabled"
    ref="handleRef"
    class="sidebar-resizer"
    :class="{
      'is-dragging': drag.active,
      'is-collapse-armed': collapseArmed,
    }"
    role="separator"
    tabindex="0"
    :aria-label="resizeLabel"
    aria-orientation="vertical"
    aria-controls="sidebar-nav app-main"
    :aria-valuemin="minimumWidth"
    :aria-valuemax="maximumWidth"
    :aria-valuenow="displayWidth"
    :aria-valuetext="widthValueText"
    data-testid="sidebar-resizer"
    @pointerdown="onPointerDown"
    @pointermove="onPointerMove"
    @pointerup="onPointerUp"
    @pointercancel="onPointerCancel"
    @lostpointercapture="onLostPointerCapture"
    @dblclick="resetToDefault"
    @keydown="onKeydown"
    @blur="onHandleBlur"
  >
    <span
      v-if="collapseArmed"
      class="sidebar-resizer__collapse-cue"
      aria-hidden="true"
    >
      <Icon name="panel-left-close" :size="14" />
      <span>{{ releaseToCollapseLabel }}</span>
    </span>
    <span
      class="sidebar-resizer__status"
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >{{ statusAnnouncement }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import {
  SIDEBAR_COLLAPSE_EXIT_THRESHOLD,
  SIDEBAR_COLLAPSE_THRESHOLD,
  SIDEBAR_DEFAULT_WIDTH,
  SIDEBAR_DRAG_DEADZONE,
  SIDEBAR_MIN_WIDTH,
  type SidebarWidthSource,
} from '@/utils/sidebarLayout'

const KEYBOARD_STEP = 8
const KEYBOARD_LARGE_STEP = 32
const GLOBAL_RESIZING_CLASS = 'is-sidebar-resizing'

const props = defineProps<{
  enabled: boolean
  width: number
  min: number
  max: number
  preference: number
  preferenceSource: SidebarWidthSource
}>()

const emit = defineEmits<{
  'resize-start': [width: number]
  preview: [width: number]
  commit: [width: number]
  reset: []
  collapse: []
  cancel: [width: number]
  'resize-end': [width: number]
}>()

const { t } = useI18n()
const handleRef = ref<HTMLElement | null>(null)
const collapseArmed = ref(false)
const statusAnnouncement = ref('')
const previewWidth = ref<number | null>(null)

const drag = reactive({
  active: false,
  moved: false,
  pointerId: -1,
  startX: 0,
  startWidth: SIDEBAR_DEFAULT_WIDTH,
  latestClientX: 0,
})

let pointerFrame = 0

const minimumWidth = computed(() => Math.max(
  SIDEBAR_MIN_WIDTH,
  normalizedInteger(props.min, SIDEBAR_MIN_WIDTH),
))
const maximumWidth = computed(() => Math.max(
  minimumWidth.value,
  normalizedInteger(props.max, minimumWidth.value),
))
const currentWidth = computed(() => clampWidth(props.width))
const preferredWidth = computed(() => normalizedInteger(props.preference, currentWidth.value))
const displayWidth = computed(() => previewWidth.value ?? currentWidth.value)
const preferenceLabel = computed(() => {
  const labels: Record<SidebarWidthSource, [string, string]> = {
    compact: ['settings.appearance.sidebarWidthCompact', 'Compact'],
    default: ['settings.appearance.sidebarWidthDefault', 'Default'],
    wide: ['settings.appearance.sidebarWidthWide', 'Wide'],
    custom: ['settings.appearance.sidebarWidthCustom', 'Custom'],
  }
  const [key, fallback] = labels[props.preferenceSource]
  return translated(key, {}, fallback)
})

const resizeLabel = computed(() => translated(
  'chrome.resizeSidebar',
  {},
  'Resize sidebar',
))
const releaseToCollapseLabel = computed(() => translated(
  'chrome.releaseToCollapseSidebar',
  {},
  'Release to collapse sidebar',
))
const collapseCanceledLabel = computed(() => translated(
  'chrome.sidebarCollapseCanceled',
  {},
  'Sidebar collapse canceled',
))
const widthValueText = computed(() => {
  const rendered = displayWidth.value
  const preferred = preferredWidth.value
  if (preferred !== rendered && (preferred < minimumWidth.value || preferred > maximumWidth.value)) {
    return translated(
      'chrome.sidebarWidthLimitedValue',
      { width: rendered, preference: preferred, preset: preferenceLabel.value },
      `Sidebar width ${rendered} pixels, ${preferenceLabel.value}, limited by the window; preferred ${preferred} pixels`,
    )
  }
  return translated(
    'chrome.sidebarWidthValue',
    { width: rendered, preset: preferenceLabel.value },
    `Sidebar width ${rendered} pixels, ${preferenceLabel.value}`,
  )
})

function translated(key: string, params: Record<string, number | string>, fallback: string): string {
  const value = t(key, params)
  return value === key ? fallback : value
}

function normalizedInteger(value: number, fallback: number): number {
  return Number.isFinite(value) ? Math.round(value) : fallback
}

function clampWidth(value: number): number {
  return Math.min(
    maximumWidth.value,
    Math.max(minimumWidth.value, normalizedInteger(value, minimumWidth.value)),
  )
}

function requestFrame(callback: FrameRequestCallback): number {
  if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
    return window.requestAnimationFrame(callback)
  }
  return window.setTimeout(() => callback(performance.now()), 0)
}

function cancelFrame(frame: number) {
  if (!frame || typeof window === 'undefined') return
  if (typeof window.cancelAnimationFrame === 'function') window.cancelAnimationFrame(frame)
  else window.clearTimeout(frame)
}

function isSupportedPointer(event: PointerEvent): boolean {
  return event.isPrimary !== false
    && event.button === 0
    && (event.pointerType === 'mouse' || event.pointerType === 'pen')
}

function capturePointer(target: HTMLElement, pointerId: number) {
  try {
    target.setPointerCapture?.(pointerId)
  } catch {
    // Pointer capture can fail if the originating pointer has already ended.
  }
}

function releasePointer(target: HTMLElement | null, pointerId: number) {
  if (!target || pointerId < 0) return
  try {
    if (!target.hasPointerCapture || target.hasPointerCapture(pointerId)) {
      target.releasePointerCapture?.(pointerId)
    }
  } catch {
    // Losing capture is already an accepted terminal state for this gesture.
  }
}

function onPointerDown(event: PointerEvent) {
  if (!props.enabled || drag.active || !isSupportedPointer(event)) return
  event.preventDefault()
  const target = event.currentTarget
  if (!(target instanceof HTMLElement)) return

  drag.active = true
  drag.moved = false
  drag.pointerId = event.pointerId
  drag.startX = event.clientX
  drag.latestClientX = event.clientX
  drag.startWidth = currentWidth.value
  previewWidth.value = currentWidth.value
  collapseArmed.value = false
  statusAnnouncement.value = ''
  setGlobalResizing(true)
  target.focus({ preventScroll: true })
  capturePointer(target, event.pointerId)
  emit('resize-start', drag.startWidth)
}

function onPointerMove(event: PointerEvent) {
  if (!drag.active || event.pointerId !== drag.pointerId) return
  drag.latestClientX = event.clientX
  if (pointerFrame) return
  pointerFrame = requestFrame(() => {
    pointerFrame = 0
    applyPointerPosition(drag.latestClientX)
  })
}

function applyPointerPosition(clientX: number) {
  if (!drag.active) return
  const delta = clientX - drag.startX
  if (!drag.moved && Math.abs(delta) < SIDEBAR_DRAG_DEADZONE) return
  drag.moved = true

  const rawWidth = drag.startWidth + delta
  if (!collapseArmed.value && rawWidth <= SIDEBAR_COLLAPSE_THRESHOLD) {
    collapseArmed.value = true
    statusAnnouncement.value = releaseToCollapseLabel.value
  } else if (collapseArmed.value && rawWidth >= SIDEBAR_COLLAPSE_EXIT_THRESHOLD) {
    collapseArmed.value = false
    statusAnnouncement.value = collapseCanceledLabel.value
  }

  const nextWidth = clampWidth(rawWidth)
  if (nextWidth === previewWidth.value) return
  previewWidth.value = nextWidth
  emit('preview', nextWidth)
}

function flushPointerPosition(clientX: number) {
  cancelFrame(pointerFrame)
  pointerFrame = 0
  applyPointerPosition(clientX)
}

function onPointerUp(event: PointerEvent) {
  if (!drag.active || event.pointerId !== drag.pointerId) return
  flushPointerPosition(event.clientX)

  const finalWidth = previewWidth.value ?? drag.startWidth
  const shouldCollapse = drag.moved && collapseArmed.value
  // A round trip back to the effective start width is a cancel, not a custom
  // preference. This is especially important when a wider named preference is
  // temporarily viewport-clamped: a no-op gesture must not overwrite it.
  const shouldCommit = drag.moved && !shouldCollapse && finalWidth !== drag.startWidth
  const startWidth = drag.startWidth
  const pointerId = drag.pointerId
  finishGestureState()
  releasePointer(handleRef.value, pointerId)

  if (shouldCollapse) emit('collapse')
  else if (shouldCommit) emit('commit', finalWidth)
  else emit('cancel', startWidth)
  emit('resize-end', shouldCommit ? finalWidth : startWidth)
}

function onPointerCancel(event: PointerEvent) {
  if (!drag.active || event.pointerId !== drag.pointerId) return
  rollbackActiveDrag()
}

function onLostPointerCapture(event: PointerEvent) {
  if (!drag.active || event.pointerId !== drag.pointerId) return
  rollbackActiveDrag(false)
}

function onHandleBlur() {
  if (drag.active) rollbackActiveDrag()
}

function onWindowBlur() {
  if (drag.active) rollbackActiveDrag()
}

function finishGestureState() {
  cancelFrame(pointerFrame)
  pointerFrame = 0
  drag.active = false
  drag.moved = false
  drag.pointerId = -1
  collapseArmed.value = false
  statusAnnouncement.value = ''
  previewWidth.value = null
  setGlobalResizing(false)
}

function setGlobalResizing(active: boolean) {
  if (typeof document === 'undefined') return
  document.documentElement.classList.toggle(GLOBAL_RESIZING_CLASS, active)
}

function rollbackActiveDrag(releaseCapture = true): boolean {
  if (!drag.active) return false
  const startWidth = drag.startWidth
  const pointerId = drag.pointerId
  finishGestureState()
  if (releaseCapture) releasePointer(handleRef.value, pointerId)
  emit('preview', startWidth)
  emit('cancel', startWidth)
  emit('resize-end', startWidth)
  return true
}

function commitDiscreteWidth(next: number) {
  if (!props.enabled || drag.active) return
  const startWidth = currentWidth.value
  const targetWidth = clampWidth(next)
  if (targetWidth === startWidth) return
  emit('resize-start', startWidth)
  emit('preview', targetWidth)
  emit('commit', targetWidth)
  emit('resize-end', targetWidth)
}

function resetToDefault(event: MouseEvent) {
  if (event.button !== 0) return
  event.preventDefault()
  if (!props.enabled || drag.active) return
  const startWidth = currentWidth.value
  if (startWidth === SIDEBAR_DEFAULT_WIDTH && props.preferenceSource === 'default') return
  emit('resize-start', startWidth)
  emit('preview', SIDEBAR_DEFAULT_WIDTH)
  emit('reset')
  emit('resize-end', SIDEBAR_DEFAULT_WIDTH)
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && drag.active) {
    event.preventDefault()
    rollbackActiveDrag()
    return
  }

  let nextWidth: number | null = null
  const step = event.shiftKey ? KEYBOARD_LARGE_STEP : KEYBOARD_STEP
  if (event.key === 'ArrowLeft') nextWidth = displayWidth.value - step
  else if (event.key === 'ArrowRight') nextWidth = displayWidth.value + step
  else if (event.key === 'Home') nextWidth = minimumWidth.value
  else if (event.key === 'End') nextWidth = maximumWidth.value
  if (nextWidth === null) return

  event.preventDefault()
  commitDiscreteWidth(nextWidth)
}

watch(() => props.enabled, enabled => {
  if (!enabled) rollbackActiveDrag()
})

watch([() => props.min, () => props.max], () => {
  if (drag.active) rollbackActiveDrag()
})

watch(() => props.width, nextWidth => {
  if (!drag.active) return
  // A parent may mirror our preview event back through the width prop. That is
  // part of the same gesture; any different width is an external layout change
  // and invalidates the pointer's start geometry.
  const expectedWidth = previewWidth.value ?? drag.startWidth
  if (clampWidth(nextWidth) !== expectedWidth) rollbackActiveDrag()
})

onMounted(() => {
  window.addEventListener('blur', onWindowBlur)
})

onBeforeUnmount(() => {
  window.removeEventListener('blur', onWindowBlur)
  rollbackActiveDrag()
  setGlobalResizing(false)
})

defineExpose({
  cancel: rollbackActiveDrag,
})
</script>

<style scoped>
.sidebar-resizer {
  position: fixed;
  inset-block: 0;
  left: var(--sidebar-width);
  z-index: 205;
  width: 10px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text-muted);
  cursor: col-resize;
  touch-action: auto;
}

.sidebar-resizer::before {
  position: absolute;
  inset: 0 auto 0 0;
  width: 1px;
  background: var(--border);
  content: '';
  transition:
    width var(--dur-fast) var(--ease-out),
    background-color var(--dur-fast) var(--ease-out);
}

.sidebar-resizer:hover::before,
.sidebar-resizer:focus-visible::before,
.sidebar-resizer.is-dragging::before {
  width: 2px;
  background: var(--accent);
}

.sidebar-resizer:focus-visible {
  outline: none;
}

.sidebar-resizer.is-dragging {
  user-select: none;
}

:global(html.is-sidebar-resizing),
:global(html.is-sidebar-resizing *) {
  cursor: col-resize !important;
  user-select: none !important;
}

.sidebar-resizer.is-collapse-armed::before {
  width: 3px;
  background: var(--warn);
}

.sidebar-resizer__collapse-cue {
  position: absolute;
  top: 50%;
  left: calc(100% + var(--sp-2));
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  width: max-content;
  max-width: min(16rem, calc(100vw - 3rem));
  padding: var(--sp-2) var(--sp-3);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  background: var(--bg-elevated);
  color: var(--text);
  box-shadow: var(--shadow-md);
  font-size: var(--fs-xs);
  font-weight: 600;
  line-height: 1.3;
  pointer-events: none;
  transform: translateY(-50%);
  white-space: nowrap;
}

.sidebar-resizer__status {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  clip-path: inset(50%);
  border: 0;
  white-space: nowrap;
}

@media (prefers-reduced-motion: reduce) {
  .sidebar-resizer::before {
    transition: none;
  }
}

@media (forced-colors: active) {
  .sidebar-resizer {
    color: CanvasText;
    forced-color-adjust: auto;
  }

  .sidebar-resizer::before {
    background: CanvasText;
  }

  .sidebar-resizer:hover::before,
  .sidebar-resizer:focus-visible::before,
  .sidebar-resizer.is-dragging::before,
  .sidebar-resizer.is-collapse-armed::before {
    width: 3px;
    background: Highlight;
  }

  .sidebar-resizer:focus-visible {
    outline: 2px solid Highlight;
    outline-offset: -2px;
  }

  .sidebar-resizer__collapse-cue {
    border: 2px solid Highlight;
    background: Canvas;
    color: CanvasText;
    box-shadow: none;
  }
}
</style>
