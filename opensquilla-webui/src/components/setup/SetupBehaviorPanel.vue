<script setup lang="ts">
import ControlSwitch from '@/components/ControlSwitch.vue'

interface BehaviorPanelContract {
  autoSessionTitles: boolean
  autoSessionTitlesDirty: boolean
  statusText: string
}

defineProps<{
  panel: BehaviorPanelContract
}>()

const emit = defineEmits<{
  updateAutoSessionTitles: [enabled: boolean]
  save: []
}>()
</script>

<template>
  <section class="control-section">
    <div class="control-section__head">
      <h3 class="control-section__title">Session behavior</h3>
      <p class="control-section__desc">{{ panel.statusText }}</p>
    </div>
    <label class="control-row">
      <div class="control-row__label-block">
        <span class="control-row__label">Auto session titles</span>
        <span class="control-row__desc">Generate short titles after the first message; off uses the first-message fallback.</span>
      </div>
      <div class="control-row__control">
        <ControlSwitch
          :checked="panel.autoSessionTitles"
          name="setup_auto_session_titles"
          aria-label="Auto session titles"
          @change="(value) => emit('updateAutoSessionTitles', value)"
        />
      </div>
    </label>
    <div class="control-section__actions">
      <button class="btn btn--primary" :disabled="!panel.autoSessionTitlesDirty" @click="emit('save')">Save behavior</button>
    </div>
  </section>
</template>
