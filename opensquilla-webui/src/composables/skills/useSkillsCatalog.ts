import { computed, ref, type ComputedRef, type Ref } from 'vue'
import type { useRpcStore } from '@/stores/rpc'
import type { AutoEnabledSkill, ProposalsSettings, Skill, SkillLayerGroup, SkillStatTile } from '@/types/skills'

interface SkillsListData {
  skills?: Skill[]
}

export interface SkillsCatalogOptions {
  proposals: Ref<unknown[]>
  autoEnabledSkills: Ref<AutoEnabledSkill[]>
  proposalsSettings: Ref<ProposalsSettings>
  loadProposals: () => Promise<void>
}

export interface SkillsCatalog {
  allSkills: Ref<Skill[]>
  filterText: Ref<string>
  statusFilter: Ref<string>
  filteredSkills: ComputedRef<Skill[]>
  metaSkills: ComputedRef<Skill[]>
  visibleLayerGroups: ComputedRef<SkillLayerGroup[]>
  installedEmpty: ComputedRef<boolean>
  emptyMessage: ComputedRef<string>
  statTiles: ComputedRef<SkillStatTile[]>
  loadData: () => Promise<void>
  setStatusFilter: (key: string) => void
}

const LAYER_ORDER = ['workspace', 'bundled', 'managed', 'personal', 'project', 'extra']

export const LAYER_LABEL: Record<string, string> = {
  workspace: 'Workspace',
  bundled: 'Bundled',
  managed: 'Managed',
  personal: 'Personal',
  project: 'Project',
  extra: 'Extra',
}

export const LAYER_HELP: Record<string, string> = {
  workspace: 'Workspace skills are local to the active workspace.',
  bundled: 'Bundled skills ship with OpenSquilla.',
  managed: 'Managed skills are locally installed into OpenSquilla state.',
  personal: 'Personal skills are local user installs, not bundled.',
  project: 'Project skills are local to the current project.',
  extra: 'Extra skills come from configured local directories.',
}

export function isMetaSkill(skill: Skill): boolean {
  return skill.kind === 'meta' || skill.kind === 'meta_sop'
}

export function skillReadyRank(skill: Skill): number {
  if (skill.status === 'ready') return 0
  if (skill.status === 'not_declared') return 1
  return 2
}

export function sortSkillsByReady(list: Skill[]): Skill[] {
  return [...list].sort((a, b) => {
    const ra = skillReadyRank(a)
    const rb = skillReadyRank(b)
    if (ra !== rb) return ra - rb
    return (a.name || '').localeCompare(b.name || '')
  })
}

export function skillStatusDotClass(skill: Skill): string {
  const status = skill.status || (skill.eligible ? 'ready' : 'needs_setup')
  if (status === 'ready') return 'is-ready'
  if (status === 'needs_setup') return 'is-needs'
  return 'is-unverified'
}

export function skillStatusDotTitle(skill: Skill): string {
  return skill.status_detail || (skill.eligible ? 'Ready' : 'Needs setup')
}

export function skillStatusChipClass(skill: Skill): string {
  const status = skill.status || (skill.eligible ? 'ready' : 'needs_setup')
  if (status === 'ready') return 'sk-chip--ok'
  if (status === 'not_declared') return 'sk-chip--unverified'
  return 'sk-chip--warn'
}

export function skillStatusChipText(skill: Skill): string {
  const status = skill.status || (skill.eligible ? 'ready' : 'needs_setup')
  if (status === 'ready') return 'ready'
  if (status === 'not_declared') return 'no deps declared'
  return 'needs deps'
}

export function skillLayerLabel(layer: string | undefined): string {
  return LAYER_LABEL[layer || ''] || layer || 'Unknown'
}

export function skillLayerHelp(layer: string | undefined): string {
  return LAYER_HELP[layer || ''] || 'Configured local skill directory.'
}

export function useSkillsCatalog(
  rpc: ReturnType<typeof useRpcStore>,
  options: SkillsCatalogOptions,
): SkillsCatalog {
  const allSkills = ref<Skill[]>([])
  const filterText = ref('')
  const statusFilter = ref('all')

  const filteredSkills = computed(() => {
    let skills = allSkills.value
    if (filterText.value) {
      const ft = filterText.value.toLowerCase()
      skills = skills.filter(s =>
        (s.name || '').toLowerCase().includes(ft) ||
        (s.description || '').toLowerCase().includes(ft) ||
        (s.triggers || []).some(t => t.toLowerCase().includes(ft))
      )
    }
    if (statusFilter.value === 'ready') {
      skills = skills.filter(s => s.status === 'ready')
    } else if (statusFilter.value === 'needs-setup') {
      skills = skills.filter(s => s.status === 'needs_setup')
    } else if (statusFilter.value === 'not-declared') {
      skills = skills.filter(s => s.status === 'not_declared')
    }
    return skills
  })

  const metaSkills = computed(() => sortSkillsByReady(filteredSkills.value.filter(s => isMetaSkill(s))))

  const layerGroups = computed(() => {
    const groups: Record<string, Skill[]> = {}
    filteredSkills.value.forEach(s => {
      if (isMetaSkill(s)) return
      const l = s.layer || 'extra'
      if (!groups[l]) groups[l] = []
      groups[l].push(s)
    })
    return groups
  })

  const visibleLayerGroups = computed(() => {
    return LAYER_ORDER
      .map(key => ({ key, skills: sortSkillsByReady(layerGroups.value[key] || []) }))
      .filter(g => g.skills.length > 0)
  })

  const installedEmpty = computed(() => {
    return filteredSkills.value.length === 0 &&
      !options.proposals.value.length &&
      !options.autoEnabledSkills.value.length &&
      !options.proposalsSettings.value.available
  })

  const emptyMessage = computed(() => {
    if (filterText.value) return 'No skills match the current filter.'
    if (statusFilter.value === 'ready') return 'No skills are ready. Install dependencies to enable them.'
    if (statusFilter.value === 'needs-setup') return 'No skills currently need setup.'
    if (statusFilter.value === 'not-declared') return 'No skills without declared dependencies.'
    return 'No skills installed.'
  })

  const statTiles = computed<SkillStatTile[]>(() => {
    const total = allSkills.value.length
    const ready = allSkills.value.filter(s => s.status === 'ready').length
    const needs = allSkills.value.filter(s => s.status === 'needs_setup').length
    const notDeclared = allSkills.value.filter(s => s.status === 'not_declared').length
    const layers = new Set(allSkills.value.map(s => s.layer).filter(Boolean))

    return [
      { key: 'all', label: 'All skills', value: String(total), hint: `${layers.size} layer${layers.size === 1 ? '' : 's'}`, mods: 'sk-stat--accent' },
      { key: 'ready', label: 'Ready', value: String(ready), hint: ready ? 'install-ready' : 'none ready', mods: '', tone: 'sk-stat__ok' },
      { key: 'needs-setup', label: 'Needs setup', value: String(needs), hint: needs ? 'awaiting deps' : 'all set', mods: '', tone: 'sk-stat__warn' },
      { key: 'not-declared', label: 'Not declared', value: String(notDeclared), hint: 'no manifest', mods: '' },
    ]
  })

  function setStatusFilter(key: string) {
    statusFilter.value = key
  }

  async function loadData() {
    try {
      await rpc.waitForConnection()
    } catch {
      return
    }
    try {
      const data = await rpc.call<SkillsListData>('skills.list')
      allSkills.value = data.skills || []
      await options.loadProposals()
    } catch (err) {
      console.warn('Failed to load skills:', (err as Error).message)
    }
  }

  return {
    allSkills,
    filterText,
    statusFilter,
    filteredSkills,
    metaSkills,
    visibleLayerGroups,
    installedEmpty,
    emptyMessage,
    statTiles,
    loadData,
    setStatusFilter,
  }
}
