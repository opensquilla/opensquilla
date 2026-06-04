<template>
  <details v-if="skills.length" class="sk-group" :class="groupClass" open>
    <summary class="sk-group__head">
      <span class="sk-group__caret">▾</span>
      <span class="sk-group__label">{{ title }}</span>
      <span class="sk-group__count">{{ skills.length }}</span>
      <span class="sk-group__meta">{{ description }}</span>
    </summary>
    <div class="sk-grid control-card-grid" style="--control-card-min: 260px">
      <SkillCard
        v-for="skill in skills"
        :key="skill.name"
        :skill="skill"
        :meta="meta"
        @open="emit('open', $event)"
      />
    </div>
  </details>
</template>

<script setup lang="ts">
import SkillCard from '@/components/skills/SkillCard.vue'
import type { Skill } from '@/types/skills'

defineProps<{
  title: string
  description: string
  skills: Skill[]
  groupClass?: string
  meta?: boolean
}>()

const emit = defineEmits<{
  open: [skill: Skill]
}>()
</script>
