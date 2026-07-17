import { describe, expect, it } from 'vitest'
import {
  SIDEBAR_COLLAPSE_EXIT_THRESHOLD,
  SIDEBAR_COLLAPSE_THRESHOLD,
  SIDEBAR_DEFAULT_WIDTH,
  SIDEBAR_DRAG_DEADZONE,
  SIDEBAR_DRAWER_WIDTH,
  SIDEBAR_MAX_WIDTH,
  SIDEBAR_MIN_WIDTH,
  SIDEBAR_WIDTH_PRESETS,
  normalizeSidebarWidthPreference,
  parseSidebarWidthPreference,
  sidebarDynamicMax,
  sidebarEffectiveWidth,
  sidebarLayoutMode,
  type SidebarWidthPreference,
} from './sidebarLayout'

describe('sidebarLayoutMode', () => {
  it('keeps the resize interaction constants stable', () => {
    expect(SIDEBAR_COLLAPSE_THRESHOLD).toBe(200)
    expect(SIDEBAR_COLLAPSE_EXIT_THRESHOLD).toBe(216)
    expect(SIDEBAR_DRAG_DEADZONE).toBe(4)
    expect(SIDEBAR_WIDTH_PRESETS.wide).toEqual({ version: 1, width: 360, source: 'wide' })
  })

  it('keeps the viewport boundaries exact', () => {
    expect(sidebarLayoutMode({ viewportWidth: 768, viewportHeight: 900 })).toBe('drawer')
    expect(sidebarLayoutMode({ viewportWidth: 769, viewportHeight: 900 })).toBe('compact')
    expect(sidebarLayoutMode({ viewportWidth: 959, viewportHeight: 900 })).toBe('compact')
    expect(sidebarLayoutMode({ viewportWidth: 960, viewportHeight: 900 })).toBe('resizable')
  })

  it('uses the drawer on coarse-only surfaces at any viewport size', () => {
    expect(sidebarLayoutMode({
      viewportWidth: 1920,
      viewportHeight: 1080,
      coarseOnly: true,
    })).toBe('drawer')
    expect(sidebarLayoutMode({
      viewportWidth: 1920,
      viewportHeight: 1080,
      coarseOnly: false,
      anyCoarse: true,
    })).toBe('resizable')
  })

  it('uses the drawer for bounded mobile landscape surfaces with any coarse input', () => {
    expect(sidebarLayoutMode({
      viewportWidth: 1024,
      viewportHeight: 520,
      anyCoarse: true,
    })).toBe('drawer')
    expect(sidebarLayoutMode({
      viewportWidth: 1024,
      viewportHeight: 521,
      anyCoarse: true,
    })).toBe('resizable')
    expect(sidebarLayoutMode({
      viewportWidth: 1025,
      viewportHeight: 520,
      anyCoarse: true,
    })).toBe('resizable')
  })
})

describe('sidebar width resolution', () => {
  it('applies the dynamic desktop cap', () => {
    expect(sidebarDynamicMax(960)).toBe(260)
    expect(sidebarDynamicMax(1000)).toBe(300)
    expect(sidebarDynamicMax(1024)).toBe(324)
    expect(sidebarDynamicMax(1100)).toBe(400)
    expect(sidebarDynamicMax(1200)).toBe(480)
    expect(sidebarDynamicMax(2000)).toBe(480)
    expect(sidebarDynamicMax(Number.NaN)).toBe(260)
  })

  it('resolves drawer, compact, and resizable widths without mutating the preference', () => {
    const preference: SidebarWidthPreference = { version: 1, width: 420, source: 'custom' }

    expect(sidebarEffectiveWidth(preference, 'drawer', 1440)).toBe(SIDEBAR_DRAWER_WIDTH)
    expect(sidebarEffectiveWidth(preference, 'drawer', 280)).toBe(256)
    expect(sidebarEffectiveWidth(preference, 'compact', 900)).toBe(260)
    expect(sidebarEffectiveWidth(preference, 'resizable', 1000)).toBe(300)
    expect(preference).toEqual({ version: 1, width: 420, source: 'custom' })
  })

  it('preserves widths inside the compact band', () => {
    expect(sidebarEffectiveWidth(
      { version: 1, width: 250, source: 'custom' },
      'compact',
      900,
    )).toBe(250)
    expect(sidebarEffectiveWidth(SIDEBAR_WIDTH_PRESETS.compact, 'compact', 900)).toBe(240)
  })
})

describe('sidebar width preference parsing', () => {
  const fallback = { version: 1, width: SIDEBAR_DEFAULT_WIDTH, source: 'default' }

  it('falls back for absent, malformed, or wrong-version storage', () => {
    expect(parseSidebarWidthPreference(null)).toEqual(fallback)
    expect(parseSidebarWidthPreference('{bad json')).toEqual(fallback)
    expect(parseSidebarWidthPreference(JSON.stringify({
      version: 2,
      width: 320,
      source: 'custom',
    }))).toEqual(fallback)
    expect(parseSidebarWidthPreference(JSON.stringify({
      version: 1,
      width: '320',
      source: 'custom',
    }))).toEqual(fallback)
  })

  it('bounds custom widths and retains their source', () => {
    expect(parseSidebarWidthPreference(JSON.stringify({
      version: 1,
      width: 999,
      source: 'custom',
    }))).toEqual({ version: 1, width: SIDEBAR_MAX_WIDTH, source: 'custom' })
    expect(parseSidebarWidthPreference(JSON.stringify({
      version: 1,
      width: 20,
      source: 'custom',
    }))).toEqual({ version: 1, width: SIDEBAR_MIN_WIDTH, source: 'custom' })
  })

  it('canonicalizes named preset widths', () => {
    expect(normalizeSidebarWidthPreference({
      version: 1,
      width: 333,
      source: 'compact',
    })).toEqual(SIDEBAR_WIDTH_PRESETS.compact)
    expect(normalizeSidebarWidthPreference({
      version: 1,
      width: 333,
      source: 'wide',
    })).toEqual(SIDEBAR_WIDTH_PRESETS.wide)
  })
})
