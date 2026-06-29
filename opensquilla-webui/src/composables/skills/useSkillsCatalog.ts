import { computed, ref, type ComputedRef, type Ref } from 'vue'
import i18n from '@/i18n'
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

// Known layer keys; labels/help text resolve through i18n by key.
const KNOWN_LAYERS = new Set(LAYER_ORDER)

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
  return skill.status_detail || (skill.eligible ? i18n.global.t('cronSkills.skills.dotReady') : i18n.global.t('cronSkills.skills.dotNeedsSetup'))
}

export function skillStatusChipClass(skill: Skill): string {
  const status = skill.status || (skill.eligible ? 'ready' : 'needs_setup')
  if (status === 'ready') return 'sk-chip--ok'
  if (status === 'not_declared') return 'sk-chip--unverified'
  return 'sk-chip--warn'
}

export function skillStatusChipText(skill: Skill): string {
  const status = skill.status || (skill.eligible ? 'ready' : 'needs_setup')
  if (status === 'ready') return i18n.global.t('cronSkills.skills.statusReady')
  if (status === 'not_declared') return i18n.global.t('cronSkills.skills.statusNoDeps')
  return i18n.global.t('cronSkills.skills.statusNeedsDeps')
}

export function skillLayerLabel(layer: string | undefined): string {
  if (layer && KNOWN_LAYERS.has(layer)) return i18n.global.t(`cronSkills.skills.layerLabel.${layer}`)
  return layer || i18n.global.t('cronSkills.skills.layerLabel.unknown')
}

export function skillLayerHelp(layer: string | undefined): string {
  if (layer && KNOWN_LAYERS.has(layer)) return i18n.global.t(`cronSkills.skills.layerHelp.${layer}`)
  return i18n.global.t('cronSkills.skills.layerHelp.default')
}

export function useSkillsCatalog(
  rpc: ReturnType<typeof useRpcStore>,
  options: SkillsCatalogOptions,
): SkillsCatalog {
  const t = i18n.global.t
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
    if (filterText.value) return t('cronSkills.skills.emptyFilter')
    if (statusFilter.value === 'ready') return t('cronSkills.skills.emptyReady')
    if (statusFilter.value === 'needs-setup') return t('cronSkills.skills.emptyNeedsSetup')
    if (statusFilter.value === 'not-declared') return t('cronSkills.skills.emptyNotDeclared')
    return t('cronSkills.skills.emptyNone')
  })

  const statTiles = computed<SkillStatTile[]>(() => {
    const total = allSkills.value.length
    const ready = allSkills.value.filter(s => s.status === 'ready').length
    const needs = allSkills.value.filter(s => s.status === 'needs_setup').length
    const notDeclared = allSkills.value.filter(s => s.status === 'not_declared').length
    const layers = new Set(allSkills.value.map(s => s.layer).filter(Boolean))

    return [
      { key: 'all', label: t('cronSkills.skills.tileAll'), value: String(total), hint: t('cronSkills.skills.tileLayerCount', { count: layers.size }), mods: 'sk-stat--accent' },
      { key: 'ready', label: t('cronSkills.skills.tileReady'), value: String(ready), hint: ready ? t('cronSkills.skills.tileReadyHintSome') : t('cronSkills.skills.tileReadyHintNone'), mods: '', tone: 'sk-stat__ok' },
      { key: 'needs-setup', label: t('cronSkills.skills.tileNeedsSetup'), value: String(needs), hint: needs ? t('cronSkills.skills.tileNeedsSetupHintSome') : t('cronSkills.skills.tileNeedsSetupHintNone'), mods: '', tone: 'sk-stat__warn' },
      { key: 'not-declared', label: t('cronSkills.skills.tileNotDeclared'), value: String(notDeclared), hint: t('cronSkills.skills.tileNotDeclaredHint'), mods: '' },
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
