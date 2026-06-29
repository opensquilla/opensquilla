<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="open" class="modal-overlay" @click="emit('cancel')">
        <div class="modal" @click.stop>
          <h3 class="modal__title">{{ t('cronSkills.deleteDialog.title') }}</h3>
          <div class="modal__body">
            <i18n-t keypath="cronSkills.deleteDialog.body" tag="p">
              <template #name><strong>{{ job?.name || job?.id }}</strong></template>
            </i18n-t>
          </div>
          <div class="modal__footer">
            <button class="btn btn--danger" @click="emit('confirm')">{{ t('cronSkills.deleteDialog.confirm') }}</button>
            <button class="btn btn--ghost" @click="emit('cancel')">{{ t('common.cancel') }}</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { CronJob } from '@/types/cron'

const { t } = useI18n()

defineProps<{
  open: boolean
  job: CronJob | null
}>()

const emit = defineEmits<{
  cancel: []
  confirm: []
}>()
</script>
