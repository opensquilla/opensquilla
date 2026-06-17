<template>
  <dialog ref="dialogRef" class="sk-dialog" @click="onBackdropClick">
    <div v-if="skill" class="sk-detail">
      <header class="sk-detail__header">
        <div class="sk-detail__head-left">
          <span v-if="skill.emoji" class="sk-detail__emoji">{{ skill.emoji }}</span>
          <strong class="sk-detail__name">{{ skill.name }}</strong>
          <div class="sk-detail__chips">
            <span class="sk-chip" :title="skillLayerHelp(skill.layer)">{{ skillLayerLabel(skill.layer) }}</span>
            <span class="sk-chip" :class="skillStatusChipClass(skill)">{{ skillStatusChipText(skill) }}</span>
          </div>
        </div>
        <button type="button" class="sk-iconbtn" aria-label="Close" @click="emit('close')">
          <Icon name="x" :size="18" />
        </button>
      </header>
      <section class="sk-detail__body">
        <p class="sk-detail__desc">{{ skill.description || '' }}</p>

        <div v-if="isMetaSkill(skill) && skill.triggers && skill.triggers.length" class="sk-detail__section">
          <div class="sk-detail__section-title">Triggers</div>
          <div class="sk-detail__sub-list">
            <code v-for="t in skill.triggers" :key="t" class="sk-chip sk-chip--trigger">{{ t }}</code>
          </div>
        </div>

        <div v-if="isMetaSkill(skill) && skill.sub_skills && skill.sub_skills.length" class="sk-detail__section">
          <div class="sk-detail__section-title">Composition ({{ skill.kind === 'meta_sop' ? 'meta_sop' : 'meta' }}, {{ skill.sub_skills.length }} sub-skills)</div>
          <div class="sk-detail__sub-list">
            <span v-for="n in skill.sub_skills" :key="n" class="sk-chip sk-chip--sub">{{ n }}</span>
          </div>
        </div>

        <div v-if="skill.status === 'needs_setup' && (skill.missing_bins?.length || skill.missing_env?.length)" class="sk-detail__section">
          <div class="sk-detail__section-title">Missing</div>
          <ul class="sk-detail__missing">
            <li v-for="b in skill.missing_bins" :key="b"><code>{{ b }}</code> <span class="sk-dim">binary</span></li>
            <li v-for="e in skill.missing_env" :key="e"><code>{{ e }}</code> <span class="sk-dim">env var</span></li>
          </ul>
        </div>

        <div v-if="skill.missing_bins?.length && skill.install?.length" class="sk-detail__section">
          <div class="sk-detail__section-title">Install</div>
          <div v-for="i in skill.install" :key="i.id" class="sk-detail__install-row">
            <span>{{ i.label || `Install via ${i.kind}` }}{{ i.bins?.length ? ` (${i.bins.join(', ')})` : '' }}</span>
            <button
              class="btn btn--primary btn--sm"
              :disabled="installingDepsId === i.id"
              @click="emit('installDeps', skill.name, i.id)"
            >
              {{ installingDepsId === i.id ? 'Installing...' : `Install via ${i.kind}` }}
            </button>
          </div>
        </div>

        <div v-if="skill.homepage" class="sk-detail__section">
          <a :href="skill.homepage" target="_blank" rel="noopener" class="sk-detail__link">Homepage</a>
        </div>
      </section>
      <footer class="sk-detail__foot">
        <small v-if="skill.file_path" class="sk-dim sk-detail__path">{{ skill.file_path }}</small>
        <button v-if="skill.layer === 'managed'" class="btn btn--sm" :disabled="uninstallingName === skill.name" @click="emit('uninstall', skill.name)">
          {{ uninstallingName === skill.name ? 'Removing...' : 'Remove' }}
        </button>
      </footer>
    </div>

    <ProposalDetailPanel v-else-if="proposal" :proposal="proposal" @close="emit('close')" />
  </dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import ProposalDetailPanel from '@/components/skills/ProposalDetailPanel.vue'
import type { Proposal, Skill } from '@/types/skills'
import {
  isMetaSkill,
  skillLayerHelp,
  skillLayerLabel,
  skillStatusChipClass,
  skillStatusChipText,
} from '@/composables/skills/useSkillsCatalog'

const props = defineProps<{
  skill: Skill | null
  proposal: Proposal | null
  installingDepsId: string | null
  uninstallingName: string | null
}>()

const emit = defineEmits<{
  close: []
  installDeps: [name: string, installId: string]
  uninstall: [name: string]
}>()

const dialogRef = ref<HTMLDialogElement | null>(null)

watch(
  () => Boolean(props.skill || props.proposal),
  (open) => {
    const dialog = dialogRef.value
    if (!dialog) return
    if (open) {
      if (dialog.open) dialog.close()
      dialog.showModal()
      return
    }
    if (dialog.open) dialog.close()
  },
)

function onBackdropClick(e: MouseEvent) {
  if (e.target === dialogRef.value) {
    emit('close')
  }
}
</script>
