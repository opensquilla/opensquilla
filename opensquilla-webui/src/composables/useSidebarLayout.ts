import { computed, onMounted, onScopeDispose, ref } from 'vue'
import { useAppStore } from '@/stores/app'
import {
  SIDEBAR_COMPACT_MAX_WIDTH,
  sidebarDynamicMax,
  sidebarEffectiveWidth,
  sidebarLayoutMode,
} from '@/utils/sidebarLayout'

const FINE_POINTER_QUERY = '(any-pointer: fine)'
const COARSE_POINTER_QUERY = '(any-pointer: coarse)'

function initialViewportWidth(): number {
  return typeof window === 'undefined' ? 0 : window.innerWidth
}

function initialViewportHeight(): number {
  return typeof window === 'undefined' ? 0 : window.innerHeight
}

function initialMediaMatch(query: string): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia(query).matches
}

// Module-level facts make App.vue and the Appearance panel consume one source
// of truth. A ref-counted listener keeps the composable safe for independently
// mounted component tests while avoiding duplicate resize/media-query handlers.
const viewportWidth = ref(initialViewportWidth())
const viewportHeight = ref(initialViewportHeight())
const anyFinePointer = ref(initialMediaMatch(FINE_POINTER_QUERY))
const anyCoarsePointer = ref(initialMediaMatch(COARSE_POINTER_QUERY))

let consumers = 0
let listening = false
let fineMedia: MediaQueryList | null = null
let coarseMedia: MediaQueryList | null = null

function syncViewport() {
  if (typeof window === 'undefined') return
  viewportWidth.value = window.innerWidth
  viewportHeight.value = window.innerHeight
}

function syncFinePointer(event?: MediaQueryListEvent) {
  anyFinePointer.value = event?.matches ?? fineMedia?.matches ?? false
}

function syncCoarsePointer(event?: MediaQueryListEvent) {
  anyCoarsePointer.value = event?.matches ?? coarseMedia?.matches ?? false
}

function attachListeners() {
  if (listening || typeof window === 'undefined') return
  listening = true
  syncViewport()
  window.addEventListener('resize', syncViewport, { passive: true })
  if (typeof window.matchMedia !== 'function') return
  fineMedia = window.matchMedia(FINE_POINTER_QUERY)
  coarseMedia = window.matchMedia(COARSE_POINTER_QUERY)
  syncFinePointer()
  syncCoarsePointer()
  fineMedia.addEventListener('change', syncFinePointer)
  coarseMedia.addEventListener('change', syncCoarsePointer)
}

function detachListeners() {
  if (!listening || typeof window === 'undefined') return
  listening = false
  window.removeEventListener('resize', syncViewport)
  fineMedia?.removeEventListener('change', syncFinePointer)
  coarseMedia?.removeEventListener('change', syncCoarsePointer)
  fineMedia = null
  coarseMedia = null
}

export function useSidebarLayout() {
  const appStore = useAppStore()
  const coarseOnly = computed(() => anyCoarsePointer.value && !anyFinePointer.value)
  const mode = computed(() => sidebarLayoutMode({
    viewportWidth: viewportWidth.value,
    viewportHeight: viewportHeight.value,
    anyCoarse: anyCoarsePointer.value,
    coarseOnly: coarseOnly.value,
  }))
  const dynamicMax = computed(() => mode.value === 'resizable'
    ? sidebarDynamicMax(viewportWidth.value)
    : SIDEBAR_COMPACT_MAX_WIDTH)
  const effectiveWidth = computed(() => sidebarEffectiveWidth(
    appStore.sidebarWidthPreference,
    mode.value,
    viewportWidth.value,
  ))
  const preferenceLimited = computed(() => mode.value !== 'resizable'
    || effectiveWidth.value !== appStore.sidebarWidthPreference.width)

  onMounted(() => {
    consumers += 1
    attachListeners()
  })
  onScopeDispose(() => {
    consumers = Math.max(0, consumers - 1)
    if (consumers === 0) detachListeners()
  })

  return {
    viewportWidth,
    viewportHeight,
    anyFinePointer,
    anyCoarsePointer,
    coarseOnly,
    mode,
    dynamicMax,
    effectiveWidth,
    preferenceLimited,
    syncViewport,
  }
}
