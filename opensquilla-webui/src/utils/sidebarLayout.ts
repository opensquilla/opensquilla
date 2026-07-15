export const SIDEBAR_WIDTH_STORAGE_KEY = 'opensquilla.sidebar.width.v1'

export const SIDEBAR_MIN_WIDTH = 240
export const SIDEBAR_DEFAULT_WIDTH = 260
export const SIDEBAR_MAX_WIDTH = 480
export const SIDEBAR_DRAWER_WIDTH = 280
export const SIDEBAR_COMPACT_MAX_WIDTH = 260
export const SIDEBAR_COLLAPSE_THRESHOLD = 200
export const SIDEBAR_COLLAPSE_EXIT_THRESHOLD = 216
export const SIDEBAR_DRAG_DEADZONE = 4
export const SIDEBAR_RESIZABLE_MIN_VIEWPORT_WIDTH = 960
export const SIDEBAR_DRAWER_MAX_VIEWPORT_WIDTH = 768
export const SIDEBAR_MOBILE_LANDSCAPE_MAX_WIDTH = 1024
export const SIDEBAR_MOBILE_LANDSCAPE_MAX_HEIGHT = 520
export const SIDEBAR_MIN_MAIN_WIDTH = 700
export const SIDEBAR_MAX_VIEWPORT_RATIO = 0.4

export type SidebarLayoutMode = 'drawer' | 'compact' | 'resizable'
export type SidebarWidthSource = 'compact' | 'default' | 'wide' | 'custom'

export interface SidebarWidthPreference {
  version: 1
  width: number
  source: SidebarWidthSource
}

export interface SidebarLayoutInput {
  viewportWidth: number
  viewportHeight: number
  coarseOnly?: boolean
  anyCoarse?: boolean
}

type SidebarPresetSource = Exclude<SidebarWidthSource, 'custom'>

const PRESET_WIDTHS: Record<SidebarPresetSource, number> = {
  compact: SIDEBAR_MIN_WIDTH,
  default: SIDEBAR_DEFAULT_WIDTH,
  wide: 360,
}

export const SIDEBAR_WIDTH_PRESETS: Readonly<Record<SidebarPresetSource, SidebarWidthPreference>> = {
  compact: { version: 1, width: SIDEBAR_MIN_WIDTH, source: 'compact' },
  default: { version: 1, width: SIDEBAR_DEFAULT_WIDTH, source: 'default' },
  wide: { version: 1, width: PRESET_WIDTHS.wide, source: 'wide' },
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function finiteDimension(value: number): number {
  return Number.isFinite(value) ? Math.max(0, value) : 0
}

function defaultPreference(): SidebarWidthPreference {
  return { ...SIDEBAR_WIDTH_PRESETS.default }
}

function isSidebarWidthSource(value: unknown): value is SidebarWidthSource {
  return value === 'compact' || value === 'default' || value === 'wide' || value === 'custom'
}

/**
 * Resolve the shell behavior from viewport and input-capability facts. This is
 * deliberately independent from the saved width: changing a preference must
 * never turn the mobile drawer into a docked desktop sidebar.
 */
export function sidebarLayoutMode(input: SidebarLayoutInput): SidebarLayoutMode {
  const width = finiteDimension(input.viewportWidth)
  const height = finiteDimension(input.viewportHeight)
  const mobileLandscape = Boolean(
    input.anyCoarse
    && width > height
    && width <= SIDEBAR_MOBILE_LANDSCAPE_MAX_WIDTH
    && height <= SIDEBAR_MOBILE_LANDSCAPE_MAX_HEIGHT,
  )

  if (width <= SIDEBAR_DRAWER_MAX_VIEWPORT_WIDTH || input.coarseOnly || mobileLandscape) {
    return 'drawer'
  }
  if (width < SIDEBAR_RESIZABLE_MIN_VIEWPORT_WIDTH) return 'compact'
  return 'resizable'
}

/** Maximum sidebar width for a resizable viewport, always in CSS pixels. */
export function sidebarDynamicMax(viewportWidth: number): number {
  const width = finiteDimension(viewportWidth)
  return Math.floor(Math.max(
    SIDEBAR_DEFAULT_WIDTH,
    Math.min(
      SIDEBAR_MAX_WIDTH,
      width * SIDEBAR_MAX_VIEWPORT_RATIO,
      width - SIDEBAR_MIN_MAIN_WIDTH,
    ),
  ))
}

/**
 * Normalize a persisted or caller-supplied preference. Named presets are
 * canonical; custom widths retain their source while being bounded globally.
 */
export function normalizeSidebarWidthPreference(
  preference: SidebarWidthPreference,
): SidebarWidthPreference {
  if (preference.version !== 1 || !isSidebarWidthSource(preference.source)) {
    return defaultPreference()
  }
  if (preference.source !== 'custom') {
    return {
      version: 1,
      width: PRESET_WIDTHS[preference.source],
      source: preference.source,
    }
  }
  if (!Number.isFinite(preference.width)) return defaultPreference()
  return {
    version: 1,
    width: clamp(Math.round(preference.width), SIDEBAR_MIN_WIDTH, SIDEBAR_MAX_WIDTH),
    source: 'custom',
  }
}

/** Parse the versioned localStorage payload, falling back safely on any error. */
export function parseSidebarWidthPreference(raw: string | null): SidebarWidthPreference {
  if (!raw) return defaultPreference()
  try {
    const value = JSON.parse(raw) as Partial<SidebarWidthPreference> | null
    if (
      !value
      || value.version !== 1
      || typeof value.width !== 'number'
      || !isSidebarWidthSource(value.source)
    ) {
      return defaultPreference()
    }
    return normalizeSidebarWidthPreference(value as SidebarWidthPreference)
  } catch {
    return defaultPreference()
  }
}

/** Resolve the applied width without mutating or downgrading the preference. */
export function sidebarEffectiveWidth(
  preference: SidebarWidthPreference,
  mode: SidebarLayoutMode,
  viewportWidth: number,
): number {
  const normalized = normalizeSidebarWidthPreference(preference)
  if (mode === 'drawer') {
    return Math.max(0, Math.min(
      SIDEBAR_DRAWER_WIDTH,
      finiteDimension(viewportWidth) - 24,
    ))
  }
  if (mode === 'compact') {
    return clamp(normalized.width, SIDEBAR_MIN_WIDTH, SIDEBAR_COMPACT_MAX_WIDTH)
  }
  return clamp(normalized.width, SIDEBAR_MIN_WIDTH, sidebarDynamicMax(viewportWidth))
}
