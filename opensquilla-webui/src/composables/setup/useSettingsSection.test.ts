import { describe, it, expect } from 'vitest'
import { sectionFromRouteParam, isKnownSectionParam } from './useSettingsSection'
import { SETTINGS_SECTIONS } from './settingsSections'

describe('sectionFromRouteParam — /settings/:section mapping', () => {
  it('passes through every known section id unchanged', () => {
    for (const s of SETTINGS_SECTIONS) {
      expect(sectionFromRouteParam(s.id)).toBe(s.id)
    }
  })

  it('maps the new Connection section', () => {
    expect(sectionFromRouteParam('connection')).toBe('connection')
  })

  it('falls back to the default first section for unknown, missing, or sentinel params', () => {
    // `auto` is a routing sentinel (/setup → /settings/auto), not a real
    // section, so the param mapper treats it as unknown and defaults.
    expect(sectionFromRouteParam('auto')).toBe('provider')
    expect(sectionFromRouteParam('does-not-exist')).toBe('provider')
    expect(sectionFromRouteParam(undefined)).toBe('provider')
    expect(sectionFromRouteParam('')).toBe('provider')
    // vue-router can hand back an array for a repeated param.
    expect(sectionFromRouteParam(['provider'])).toBe('provider')
  })
})

describe('isKnownSectionParam', () => {
  it('recognises real sections and rejects sentinels/unknowns', () => {
    expect(isKnownSectionParam('connection')).toBe(true)
    expect(isKnownSectionParam('capabilities')).toBe(true)
    expect(isKnownSectionParam('auto')).toBe(false)
    expect(isKnownSectionParam('nope')).toBe(false)
    expect(isKnownSectionParam(undefined)).toBe(false)
  })
})
