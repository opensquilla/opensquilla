<template>
  <button
    type="button"
    class="sk-card control-card control-card--interactive"
    :class="{ 'sk-card--meta': isMetaSkill(skill) || meta }"
    :title="skill.name + (skill.description ? ': ' + skill.description : '')"
    @click="emit('open', skill)"
  >
    <div class="sk-card__head">
      <span class="sk-card__dot" :class="skillStatusDotClass(skill)" :title="skillStatusDotTitle(skill)" />
      <span v-if="skill.emoji" class="sk-card__emoji">{{ skill.emoji }}</span>
      <span class="sk-card__name" :title="skill.name">{{ skill.name }}</span>
      <span v-if="skill.kind === 'meta_sop'" class="sk-card__kind-badge" title="meta_sop">SOP</span>
      <span v-else-if="isMetaSkill(skill)" class="sk-card__kind-badge" title="meta">META</span>
    </div>
    <p class="sk-card__desc" :title="skill.description || ''">{{ skill.description || '' }}</p>
    <div v-if="skill.sub_skills && skill.sub_skills.length" class="sk-card__sub-row" title="Sub-skills used by this meta-skill">
      <span class="sk-card__sub-label">uses</span>
      <span v-for="n in skill.sub_skills.slice(0, 6)" :key="n" class="sk-card__sub-chip">{{ n }}</span>
      <span v-if="skill.sub_skills.length > 6" class="sk-card__sub-chip sk-card__sub-chip--more">+{{ skill.sub_skills.length - 6 }}</span>
    </div>
  </button>
</template>

<script setup lang="ts">
import type { Skill } from '@/types/skills'
import {
  isMetaSkill,
  skillStatusDotClass,
  skillStatusDotTitle,
} from '@/composables/skills/useSkillsCatalog'

defineProps<{
  skill: Skill
  meta?: boolean
}>()

const emit = defineEmits<{
  open: [skill: Skill]
}>()
</script>
