<template>
  <details v-if="skills.length" class="sk-group sk-group--proposals" open>
    <summary class="sk-group__head">
      <span class="sk-group__caret">▾</span>
      <span class="sk-group__label">Auto-Enabled Meta-Skills</span>
      <span class="sk-group__count">{{ skills.length }}</span>
      <span class="sk-group__meta">Promoted by auto-enable. Disable moves the skill back to pending proposals.</span>
    </summary>
    <div class="sk-proposals-list">
      <div v-for="s in skills" :key="s.name" class="sk-proposal-row">
        <div class="sk-proposal-row__head">
          <code class="sk-proposal-row__id">{{ s.name }}</code>
          <span class="sk-prop-chip sk-prop-chip--ok">enabled</span>
          <span class="sk-prop-chip sk-prop-chip--auto">{{ s.triggered_by || 'unknown' }}</span>
          <span class="sk-prop-chip">risk: {{ s.risk_level || 'unknown' }}</span>
          <span class="sk-prop-chip">{{ s.validation_profile || 'unknown' }}</span>
          <span v-if="Array.isArray(s.skills) && s.skills.length" class="sk-prop-chip" :title="s.skills.join(', ')">{{ s.skills.slice(0, 4).join(', ') }}</span>
          <span v-if="s.proposal_id" class="sk-prop-hash" title="proposal id">{{ s.proposal_id }}</span>
        </div>
        <div class="sk-proposal-row__actions">
          <button class="btn btn--ghost btn--sm" type="button" @click="emit('disable', s.name)">Disable</button>
        </div>
      </div>
    </div>
  </details>
</template>

<script setup lang="ts">
import type { AutoEnabledSkill } from '@/types/skills'

defineProps<{
  skills: AutoEnabledSkill[]
}>()

const emit = defineEmits<{
  disable: [name: string]
}>()
</script>
