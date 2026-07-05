import { describe, it, expect } from 'vitest'
import { sectionFromRouteParam, isKnownSectionParam } from './useSettingsSection'
import { SETTINGS_SECTIONS } from './settingsSections'
import en from '@/locales/en.json'

describe('settings section IA', () => {
  it('has one Model Strategy section instead of split Router and Ensemble sections', () => {
    const ids = SETTINGS_SECTIONS.map(s => s.id)
    expect(ids).toContain('modelStrategy')
    expect(ids).not.toContain('router')
    expect(ids).not.toContain('ensemble')
    expect(ids.indexOf('provider')).toBeLessThan(ids.indexOf('modelStrategy'))
    expect(ids.indexOf('modelStrategy')).toBeLessThan(ids.indexOf('capabilities'))
  })

  it('passes through every canonical section id unchanged', () => {
    for (const s of SETTINGS_SECTIONS) {
      expect(sectionFromRouteParam(s.id)).toBe(s.id)
      expect(isKnownSectionParam(s.id)).toBe(true)
    }
  })

  it('has an English rail label for every canonical section id', () => {
    for (const s of SETTINGS_SECTIONS) {
      expect(en.settings.rail).toHaveProperty(s.id)
    }
  })

  it('aliases stale Router and Ensemble deep links to Model Strategy', () => {
    expect(sectionFromRouteParam('router')).toBe('modelStrategy')
    expect(sectionFromRouteParam('ensemble')).toBe('modelStrategy')
    expect(isKnownSectionParam('router')).toBe(true)
    expect(isKnownSectionParam('ensemble')).toBe(true)
  })

  it('aliases Chat Model deep links to the provider-backed section', () => {
    expect(sectionFromRouteParam('chatModel')).toBe('provider')
    expect(sectionFromRouteParam('provider')).toBe('provider')
    expect(isKnownSectionParam('chatModel')).toBe(true)
  })

  it('falls back to Provider for unknown, missing, and sentinel params', () => {
    expect(sectionFromRouteParam('auto')).toBe('provider')
    expect(sectionFromRouteParam('does-not-exist')).toBe('provider')
    expect(sectionFromRouteParam(undefined)).toBe('provider')
    expect(sectionFromRouteParam('')).toBe('provider')
    expect(sectionFromRouteParam(['provider'])).toBe('provider')
  })
})
