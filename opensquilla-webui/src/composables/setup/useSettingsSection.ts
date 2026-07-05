import { ref } from 'vue'
import { SETTINGS_SECTIONS, type SettingsSectionId } from '@/composables/setup/settingsSections'

const DEFAULT_SECTION: SettingsSectionId = 'provider'
const SECTION_ALIASES: Record<string, SettingsSectionId> = {
  router: 'modelStrategy',
  ensemble: 'modelStrategy',
  chatModel: 'provider',
}

function sectionIdFor(value: unknown): SettingsSectionId | null {
  if (typeof value !== 'string') return null
  const canonical = SETTINGS_SECTIONS.find(s => s.id === value)
  if (canonical) return canonical.id
  return SECTION_ALIASES[value] || null
}

export function sectionFromRouteParam(param: unknown): SettingsSectionId {
  return sectionIdFor(param) || DEFAULT_SECTION
}

export function isKnownSectionParam(param: unknown): boolean {
  return sectionIdFor(param) !== null
}

export function useSettingsSection(initialSection: string) {
  const section = ref(initialSection)

  function setSection(next: string) {
    if (!next || next === section.value) return
    section.value = next
  }

  return { section, setSection }
}
