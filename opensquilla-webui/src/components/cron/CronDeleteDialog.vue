<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="open" class="modal-overlay" @click="emit('cancel')">
        <div class="modal" @click.stop>
          <h3 class="modal__title">Delete schedule</h3>
          <div class="modal__body">
            <p>Delete <strong>{{ job?.name || job?.id }}</strong>? This cannot be undone.</p>
          </div>
          <div class="modal__footer">
            <button class="btn btn--danger" @click="emit('confirm')">Delete</button>
            <button class="btn btn--ghost" @click="emit('cancel')">Cancel</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import type { CronJob } from '@/types/cron'

defineProps<{
  open: boolean
  job: CronJob | null
}>()

const emit = defineEmits<{
  cancel: []
  confirm: []
}>()
</script>
