import { describe, it, expect } from 'vitest'
import {
  isValueThemeId,
  normalizeThemeId,
  LEGACY_THEME_IDS,
  themePickerOptions,
} from './registry'

describe('theme registry', () => {
  it('registers the renamed themes and no longer registers the old ids', () => {
    expect(isValueThemeId('arctic')).toBe(true)
    expect(isValueThemeId('crt-green')).toBe(true)
    // The pre-rename ids are not registered themes anymore.
    expect(isValueThemeId('nord')).toBe(false)
    expect(isValueThemeId('phosphor')).toBe(false)
  })

  it('maps legacy persisted ids to their current canonical id', () => {
    expect(normalizeThemeId('nord')).toBe('arctic')
    expect(normalizeThemeId('phosphor')).toBe('crt-green')
    expect(LEGACY_THEME_IDS).toMatchObject({ nord: 'arctic', phosphor: 'crt-green' })
  })

  it('a legacy persisted id resolves to a real value theme (not a fallback)', () => {
    const resolved = normalizeThemeId('nord')
    expect(resolved).toBe('arctic')
    expect(isValueThemeId(resolved)).toBe(true)
  })

  it('passes through current ids, system, and unknown ids unchanged', () => {
    expect(normalizeThemeId('arctic')).toBe('arctic')
    expect(normalizeThemeId('system')).toBe('system')
    expect(normalizeThemeId('vapor')).toBe('vapor')
    expect(normalizeThemeId('ferrari-red')).toBe('ferrari-red')
  })

  it('basic scope lists only light / dark / system — no custom themes', () => {
    const modes = themePickerOptions({ scope: 'basic' }).map((o) => o.mode)
    expect(modes).toEqual(['light', 'dark', 'system'])
  })

  it('all scope lists every value theme plus system, with system last', () => {
    const modes = themePickerOptions({ scope: 'all' }).map((o) => o.mode)
    expect(modes).toEqual(expect.arrayContaining(['light', 'dark', 'system']))
    expect(modes).toContain('arctic')
    expect(modes).toContain('crt-green')
    expect(modes).toContain('synthwave')
    expect(modes.length).toBeGreaterThan(4)
    expect(modes[modes.length - 1]).toBe('system')
    // the topbar (basic) list is a strict subset of the full (all) list
    for (const m of themePickerOptions({ scope: 'basic' }).map((o) => o.mode)) {
      expect(modes).toContain(m)
    }
  })

  it('defaults to the full list', () => {
    expect(themePickerOptions().map((o) => o.mode)).toContain('arctic')
  })
})
