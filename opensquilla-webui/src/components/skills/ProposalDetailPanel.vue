<template>
  <div class="sk-detail">
    <header class="sk-detail__header">
      <h3>{{ t('cronSkills.proposalDetail.heading', { id: proposal.proposal_id }) }}</h3>
      <button class="btn btn--ghost btn--sm" type="button" @click="emit('close')">{{ t('common.close') }}</button>
    </header>
    <section class="sk-detail__section">
      <h4>{{ t('cronSkills.proposalDetail.auditTitle') }}</h4>
      <div v-if="proposal.auto_enable_audit && proposal.auto_enable_audit.status" class="sk-audit-grid">
        <div><span>{{ t('cronSkills.proposalDetail.status') }}</span><strong>{{ proposal.auto_enable_audit.status }}</strong></div>
        <div><span>{{ t('cronSkills.proposalDetail.risk') }}</span><strong>{{ proposal.auto_enable_audit.risk_level || t('cronSkills.proposalDetail.unknown') }} / {{ proposal.auto_enable_audit.max_risk || t('cronSkills.proposalDetail.unknown') }}</strong></div>
        <div><span>{{ t('cronSkills.proposalDetail.staticSafetyProfile') }}</span><strong>{{ proposal.auto_enable_audit.validation_profile || t('cronSkills.proposalDetail.unknown') }}</strong></div>
        <div><span>{{ t('cronSkills.proposalDetail.reason') }}</span><strong>{{ proposal.auto_enable_audit.reason || t('cronSkills.proposalDetail.none') }}</strong></div>
        <div class="sk-audit-grid__wide">
          <span>{{ t('cronSkills.proposalDetail.skills') }}</span>
          <p>
            <template v-if="proposal.auto_enable_audit.skills?.length">
              <code v-for="v in proposal.auto_enable_audit.skills" :key="v">{{ v }}</code>
            </template>
            <span v-else class="sk-dim">{{ t('cronSkills.proposalDetail.none') }}</span>
          </p>
        </div>
        <div class="sk-audit-grid__wide">
          <span>{{ t('cronSkills.proposalDetail.tools') }}</span>
          <p>
            <template v-if="proposal.auto_enable_audit.tools?.length">
              <code v-for="v in proposal.auto_enable_audit.tools" :key="v">{{ v }}</code>
            </template>
            <span v-else class="sk-dim">{{ t('cronSkills.proposalDetail.none') }}</span>
          </p>
        </div>
        <div class="sk-audit-grid__wide">
          <span>{{ t('cronSkills.proposalDetail.staticSafetyReasons') }}</span>
          <p>
            <template v-if="proposal.auto_enable_audit.reasons?.length">
              <code v-for="v in proposal.auto_enable_audit.reasons" :key="v">{{ v }}</code>
            </template>
            <span v-else class="sk-dim">{{ t('cronSkills.proposalDetail.none') }}</span>
          </p>
        </div>
      </div>
      <div v-else class="sk-audit-empty">{{ t('cronSkills.proposalDetail.noAudit') }}</div>
    </section>
    <section class="sk-detail__section">
      <h4>SKILL.md</h4>
      <pre class="sk-detail__pre">{{ proposal.skill_md || '' }}</pre>
    </section>
    <section class="sk-detail__section">
      <h4>{{ t('cronSkills.proposalDetail.gates') }}</h4>
      <pre class="sk-detail__pre">{{ JSON.stringify(proposal.gates || {}, null, 2) }}</pre>
    </section>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { Proposal } from '@/types/skills'

const { t } = useI18n()

defineProps<{
  proposal: Proposal
}>()

const emit = defineEmits<{
  close: []
}>()
</script>
