<script setup lang="ts">
import { useI18n } from 'vue-i18n'

// Edit-mode stored-credential row (credential-card idiom): masked value with
// Replace, or a password input with Cancel while replacing. Channel secrets
// have no reveal RPC, so there is deliberately no reveal affordance.
const props = defineProps<{
  field: { name: string; label: string; description?: string; required?: boolean }
  hasStored: boolean
  replacing: boolean
  value: string
}>()

const emit = defineEmits<{
  replace: [name: string]
  cancelReplace: [name: string]
  update: [name: string, value: string]
}>()

const { t } = useI18n()

function onInput(event: Event) {
  emit('update', props.field.name, (event.target as HTMLInputElement).value)
}
</script>

<template>
  <div class="control-row">
    <div class="control-row__label-block">
      <span class="control-row__label">{{ field.label }}<template v-if="field.required"> *</template></span>
      <span v-if="field.description" class="control-row__desc">{{ field.description }}</span>
    </div>
    <div class="control-row__control scs">
      <template v-if="hasStored && !replacing">
        <input
          class="control-input scs__masked"
          type="text"
          readonly
          :value="t('setup.channels.secretStored')"
          :name="`setup_channel_${field.name}`"
        />
        <button type="button" class="btn btn--ghost scs__btn" @click="emit('replace', field.name)">
          {{ t('setup.channels.secretReplace') }}
        </button>
      </template>
      <template v-else>
        <input
          class="control-input scs__input"
          type="password"
          autocomplete="new-password"
          :value="value"
          :placeholder="t('setup.channels.secretReplacePlaceholder')"
          :name="`setup_channel_${field.name}`"
          data-secret="true"
          @input="onInput"
        />
        <button
          v-if="hasStored"
          type="button"
          class="btn btn--ghost scs__btn"
          @click="emit('cancelReplace', field.name)"
        >
          {{ t('setup.channels.secretKeepStored') }}
        </button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.scs { align-items: center; display: flex; flex-wrap: wrap; gap: var(--sp-2); }
.scs__masked { color: var(--text-dim); flex: 1 1 140px; letter-spacing: 0.08em; min-width: 0; }
.scs__btn { flex: 0 0 auto; font-size: var(--fs-sm); padding: 3px 10px; white-space: nowrap; }
.scs__input { flex: 1 1 140px; min-width: 0; }
</style>
