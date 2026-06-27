import { ref } from 'vue'
import { SETTINGS_SECTIONS, type SettingsSectionId } from '@/composables/setup/settingsSections'

const DEFAULT_SECTION: SettingsSectionId = 'provider'

function isSettingsSectionId(value: unknown): value is SettingsSectionId {
  return typeof value === 'string' && SETTINGS_SECTIONS.some(s => s.id === value)
}

/**
 * Map a `/settings/:section` route param to a rail section id. An unknown or
 * missing param falls back to the default first section so a stale or
 * hand-typed URL never lands on a blank rail. Pure: safe to unit-test.
 */
export function sectionFromRouteParam(param: unknown): SettingsSectionId {
  return isSettingsSectionId(param) ? param : DEFAULT_SECTION
}

/**
 * Whether a route param is a recognised section. Lets the route layer decide
 * between replacing the URL with the canonical section vs. leaving it.
 */
export function isKnownSectionParam(param: unknown): param is SettingsSectionId {
  return isSettingsSectionId(param)
}

export function useSettingsSection(initialSection: string) {
  const section = ref(initialSection)

  function setSection(next: string) {
    if (!next || next === section.value) return
    section.value = next
  }

  return { section, setSection }
}
