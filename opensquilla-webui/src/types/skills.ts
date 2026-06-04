import type { SkillStatTile } from '@/components/skills/SkillsStats.vue'

export interface SkillInstall {
  id: string
  kind: string
  label?: string
  bins?: string[]
}

export interface Skill {
  name: string
  description?: string
  emoji?: string
  status?: string
  status_detail?: string
  eligible?: boolean
  layer?: string
  kind?: string
  sub_skills?: string[]
  triggers?: string[]
  missing_bins?: string[]
  missing_env?: string[]
  install?: SkillInstall[]
  homepage?: string
  file_path?: string
}

export interface Proposal {
  proposal_id: string
  auto_enable_eligible?: boolean
  triggered_by?: string
  auto_enable?: {
    status?: string
    reason?: string
    validation_profile?: string
  }
  chain_hash?: string
  skill_md?: string
  gates?: Record<string, unknown>
  auto_enable_audit?: {
    status?: string
    risk_level?: string
    max_risk?: string
    validation_profile?: string
    reason?: string
    skills?: string[]
    tools?: string[]
    reasons?: string[]
  }
}

export interface AutoEnabledSkill {
  name: string
  risk_level?: string
  triggered_by?: string
  validation_profile?: string
  skills?: string[]
  proposal_id?: string
}

export interface ProposalsSettings {
  available: boolean
  enabled: boolean
  on_dream_complete: boolean
  auto_enable: boolean
  auto_enable_max_risk: string
  cron?: string
}

export interface RegistryResult {
  name: string
  description?: string
  identifier?: string
  source?: string
  trust_level?: string
  installed?: boolean
}

export interface SkillLayerGroup {
  key: string
  skills: Skill[]
}

export type { SkillStatTile }
