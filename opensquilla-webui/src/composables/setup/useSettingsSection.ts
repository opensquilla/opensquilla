import { ref } from 'vue'

export function useSettingsSection(initialSection: string) {
  const section = ref(initialSection)

  function setSection(next: string) {
    if (!next || next === section.value) return
    section.value = next
  }

  return { section, setSection }
}
