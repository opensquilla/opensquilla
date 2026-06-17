import { computed, ref, type ComputedRef, type Ref } from 'vue'
import type { useRpcStore } from '@/stores/rpc'
import type { AutoEnabledSkill, Proposal, ProposalsSettings } from '@/types/skills'

interface ProposalsListData {
  proposals?: Proposal[]
}

interface AutoEnabledListData {
  skills?: AutoEnabledSkill[]
}

interface ProposalSettingsData {
  settings?: ProposalsSettings
  status?: string
  reason?: string
}

interface ProposalShowData {
  status?: string
  reason?: string
  skill_md?: string
  gates?: Record<string, unknown>
  auto_enable_audit?: Proposal['auto_enable_audit']
}

interface ProposalActionData {
  status?: string
  reason?: string
}

export interface SkillProposals {
  proposals: Ref<Proposal[]>
  autoEnabledSkills: Ref<AutoEnabledSkill[]>
  proposalsSettings: Ref<ProposalsSettings>
  proposalsSettingsOn: ComputedRef<boolean>
  loadProposals: () => Promise<void>
  toggleAutoPropose: (key: string, value: boolean) => Promise<void>
  setAutoEnableRisk: (value: string) => Promise<void>
  showProposal: (proposalId: string) => Promise<Proposal | null>
  acceptProposal: (proposalId: string) => Promise<void>
  rejectProposal: (proposalId: string) => Promise<void>
  disableAutoEnabled: (name: string) => Promise<void>
}

const DEFAULT_PROPOSAL_SETTINGS: ProposalsSettings = {
  available: false,
  enabled: false,
  on_dream_complete: false,
  auto_enable: false,
  auto_enable_max_risk: 'low',
}

export function useSkillProposals(
  rpc: ReturnType<typeof useRpcStore>,
  loadData: () => Promise<void>,
): SkillProposals {
  const proposals = ref<Proposal[]>([])
  const autoEnabledSkills = ref<AutoEnabledSkill[]>([])
  const proposalsSettings = ref<ProposalsSettings>({ ...DEFAULT_PROPOSAL_SETTINGS })

  const proposalsSettingsOn = computed(() => {
    const s = proposalsSettings.value
    return s.enabled || s.on_dream_complete || s.auto_enable
  })

  async function loadProposals() {
    try {
      const data = await rpc.call<ProposalsListData>('exec.proposals.list')
      proposals.value = data.proposals || []
    } catch {
      proposals.value = []
    }
    try {
      const data = await rpc.call<AutoEnabledListData>('exec.proposals.auto_enabled.list')
      autoEnabledSkills.value = data.skills || []
    } catch {
      autoEnabledSkills.value = []
    }
    try {
      const data = await rpc.call<ProposalSettingsData>('exec.proposals.settings.get')
      proposalsSettings.value = data.settings || proposalsSettings.value
    } catch {
      proposalsSettings.value = { ...DEFAULT_PROPOSAL_SETTINGS }
    }
  }

  async function toggleAutoPropose(key: string, value: boolean) {
    try {
      const out = await rpc.call<ProposalSettingsData>('exec.proposals.settings.set', { [key]: value })
      if (out && out.status === 'error') {
        console.warn('Settings update failed:', out.reason || 'unknown')
        return
      }
      proposalsSettings.value = out.settings || proposalsSettings.value
      await loadData()
    } catch (err) {
      console.warn('Settings update failed:', (err as Error).message)
    }
  }

  async function setAutoEnableRisk(value: string) {
    try {
      const out = await rpc.call<ProposalSettingsData>('exec.proposals.settings.set', { auto_enable_max_risk: value })
      if (out && out.status === 'error') {
        console.warn('Settings update failed:', out.reason || 'unknown')
        return
      }
      proposalsSettings.value = out.settings || proposalsSettings.value
    } catch (err) {
      console.warn('Settings update failed:', (err as Error).message)
    }
  }

  async function showProposal(proposalId: string): Promise<Proposal | null> {
    try {
      const data = await rpc.call<ProposalShowData>('exec.proposals.show', { proposal_id: proposalId })
      if (data.status !== 'ok') {
        console.warn('Show failed:', data.reason || 'unknown')
        return null
      }
      return { proposal_id: proposalId, ...data }
    } catch (err) {
      console.warn('Show failed:', (err as Error).message)
      return null
    }
  }

  async function acceptProposal(proposalId: string) {
    try {
      let data = await rpc.call<ProposalActionData>('exec.proposals.accept', { proposal_id: proposalId })
      if (data.status === 'refused' && data.reason && data.reason.indexOf('gates') !== -1) {
        if (!confirm(`Proposal ${proposalId} did not pass all gates.\n\n${data.reason}\n\nAccept anyway (force)?`)) return
        data = await rpc.call<ProposalActionData>('exec.proposals.accept', { proposal_id: proposalId, force: true })
      }
      if (data.status !== 'ok') {
        console.warn('Accept failed:', data.reason || data.status)
        return
      }
      await loadData()
    } catch (err) {
      console.warn('Accept failed:', (err as Error).message)
    }
  }

  async function rejectProposal(proposalId: string) {
    if (!confirm(`Reject and delete proposal ${proposalId}? This cannot be undone.`)) return
    try {
      const data = await rpc.call<ProposalActionData>('exec.proposals.reject', { proposal_id: proposalId })
      if (data.status !== 'ok') {
        console.warn('Reject failed:', data.reason || data.status)
        return
      }
      await loadData()
    } catch (err) {
      console.warn('Reject failed:', (err as Error).message)
    }
  }

  async function disableAutoEnabled(name: string) {
    if (!confirm(`Disable auto-enabled skill ${name} and move it back to pending proposals?`)) return
    try {
      const data = await rpc.call<ProposalActionData>('exec.proposals.auto_enabled.disable', { name })
      if (data.status !== 'ok') {
        console.warn('Disable failed:', data.reason || data.status)
        return
      }
      await loadData()
    } catch (err) {
      console.warn('Disable failed:', (err as Error).message)
    }
  }

  return {
    proposals,
    autoEnabledSkills,
    proposalsSettings,
    proposalsSettingsOn,
    loadProposals,
    toggleAutoPropose,
    setAutoEnableRisk,
    showProposal,
    acceptProposal,
    rejectProposal,
    disableAutoEnabled,
  }
}
