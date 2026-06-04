<template>
  <div class="sk-detail">
    <header class="sk-detail__header">
      <h3>Proposal {{ proposal.proposal_id }}</h3>
      <button class="btn btn--ghost btn--sm" type="button" @click="emit('close')">Close</button>
    </header>
    <section class="sk-detail__section">
      <h4>Auto-enable Audit</h4>
      <div v-if="proposal.auto_enable_audit && proposal.auto_enable_audit.status" class="sk-audit-grid">
        <div><span>Status</span><strong>{{ proposal.auto_enable_audit.status }}</strong></div>
        <div><span>Risk</span><strong>{{ proposal.auto_enable_audit.risk_level || 'unknown' }} / {{ proposal.auto_enable_audit.max_risk || 'unknown' }}</strong></div>
        <div><span>static-safety profile</span><strong>{{ proposal.auto_enable_audit.validation_profile || 'unknown' }}</strong></div>
        <div><span>Reason</span><strong>{{ proposal.auto_enable_audit.reason || 'none' }}</strong></div>
        <div class="sk-audit-grid__wide">
          <span>Skills</span>
          <p>
            <template v-if="proposal.auto_enable_audit.skills?.length">
              <code v-for="v in proposal.auto_enable_audit.skills" :key="v">{{ v }}</code>
            </template>
            <span v-else class="sk-dim">none</span>
          </p>
        </div>
        <div class="sk-audit-grid__wide">
          <span>Tools</span>
          <p>
            <template v-if="proposal.auto_enable_audit.tools?.length">
              <code v-for="v in proposal.auto_enable_audit.tools" :key="v">{{ v }}</code>
            </template>
            <span v-else class="sk-dim">none</span>
          </p>
        </div>
        <div class="sk-audit-grid__wide">
          <span>Static-safety reasons</span>
          <p>
            <template v-if="proposal.auto_enable_audit.reasons?.length">
              <code v-for="v in proposal.auto_enable_audit.reasons" :key="v">{{ v }}</code>
            </template>
            <span v-else class="sk-dim">none</span>
          </p>
        </div>
      </div>
      <div v-else class="sk-audit-empty">No auto-enable decision recorded.</div>
    </section>
    <section class="sk-detail__section">
      <h4>SKILL.md</h4>
      <pre class="sk-detail__pre">{{ proposal.skill_md || '' }}</pre>
    </section>
    <section class="sk-detail__section">
      <h4>Gates</h4>
      <pre class="sk-detail__pre">{{ JSON.stringify(proposal.gates || {}, null, 2) }}</pre>
    </section>
  </div>
</template>

<script setup lang="ts">
import type { Proposal } from '@/types/skills'

defineProps<{
  proposal: Proposal
}>()

const emit = defineEmits<{
  close: []
}>()
</script>
