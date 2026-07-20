<script setup lang="ts">
// One configuration row on the shared 148px label rail. Read mode renders the
// value as text inside the same box metrics the edit-mode control uses, so
// flipping read ⇄ edit swaps the control IN PLACE — same rail, same x/y
// geometry, zero reflow. That geometric identity is the point of this file.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import ControlSwitch from '@/components/ControlSwitch.vue'
import type { ChannelEditorFieldSpec } from '@/composables/channels/useChannelEditor'

export interface ConfigRowModel {
  kind: 'name' | 'field' | 'secret'
  field: ChannelEditorFieldSpec
  value: string
  edited: boolean
  hasStored?: boolean
  replacing?: boolean
}

const props = defineProps<{
  row: ConfigRowModel
  edit: boolean
  error?: string
}>()

const emit = defineEmits<{
  update: [name: string, value: unknown]
  replace: [name: string]
  cancelReplace: [name: string]
}>()

const { t } = useI18n()

const fieldType = computed(() => String(props.row.field.type || 'text'))
const inputId = computed(() => `cfge-${props.row.field.name.replace(/[^a-zA-Z0-9_-]+/g, '-')}`)
// Compose mode routes secret fields through here as plain rows (nothing is
// stored yet) — they must still render as password inputs, never text.
const isSecretInput = computed(
  () => props.row.field.secret === true || fieldType.value === 'password',
)
const inputType = computed(() => {
  if (isSecretInput.value) return 'password'
  if (fieldType.value === 'int' || fieldType.value === 'float') return 'number'
  return 'text'
})
const placeholder = computed(() => {
  if (props.row.field.placeholder) return props.row.field.placeholder
  return isSecretInput.value ? t('setup.field.secretComposePlaceholder') : ''
})
const displayValue = computed(() => (props.row.value === '' ? '—' : props.row.value))

function onInput(event: Event) {
  emit('update', props.row.field.name, (event.target as HTMLInputElement | HTMLSelectElement).value)
}
</script>

<template>
  <div class="cfge__row" :data-field="row.field.name">
    <div class="cfge__rail">
      <label class="cfge__label" :for="inputId">
        {{ row.field.label }}<span v-if="row.field.required" aria-hidden="true"> *</span>
      </label>
      <span
        v-if="edit && row.edited"
        class="cfge__tick"
        :title="t('console.channels.editor.edited')"
        :aria-label="t('console.channels.editor.edited')"
      >●</span>
    </div>
    <div class="cfge__control">
      <!-- Name: identity key. In edit mode it is locked text with a lock
           glyph — deliberately not a disabled input. -->
      <template v-if="row.kind === 'name'">
        <span v-if="!edit" class="cfge__value">{{ displayValue }}</span>
        <span v-else class="cfge__value cfge__value--locked" :title="t('setup.channels.nameLocked')">
          <span>{{ row.value }}</span>
          <Icon name="lock" :size="13" aria-hidden="true" />
          <span class="cfge__sr-only">{{ t('setup.channels.nameLocked') }}</span>
        </span>
      </template>

      <!-- Secret: a stored credential reads materially different from an
           empty input; Replace swaps to a fresh password box in place. -->
      <template v-else-if="row.kind === 'secret'">
        <template v-if="row.hasStored && (!edit || !row.replacing)">
          <span class="cfge__secretline">
            <span class="cfge__value cfge__value--secret">{{ t('console.channels.editor.storedSecret') }}</span>
            <button
              v-if="edit"
              type="button"
              class="btn btn--ghost cfge__secretbtn"
              @click="emit('replace', row.field.name)"
            >{{ t('setup.channels.secretReplace') }}</button>
          </span>
        </template>
        <template v-else-if="!edit">
          <span class="cfge__value">—</span>
        </template>
        <template v-else>
          <span class="cfge__secretline">
            <input
              :id="inputId"
              class="cfge__input"
              type="password"
              autocomplete="new-password"
              data-secret="true"
              :value="row.value"
              :placeholder="t('setup.channels.secretReplacePlaceholder')"
              :name="`setup_channel_${row.field.name}`"
              @input="onInput"
            />
            <button
              v-if="row.hasStored"
              type="button"
              class="btn btn--ghost cfge__secretbtn"
              @click="emit('cancelReplace', row.field.name)"
            >{{ t('setup.channels.secretKeepStored') }}</button>
          </span>
        </template>
      </template>

      <template v-else-if="fieldType === 'bool'">
        <span v-if="!edit" class="cfge__value">{{ displayValue }}</span>
        <span v-else class="cfge__switchline">
          <ControlSwitch
            :id="inputId"
            :checked="row.value === 'true'"
            :name="`setup_channel_${row.field.name}`"
            :aria-label="row.field.label"
            @change="value => emit('update', row.field.name, value)"
          />
        </span>
      </template>

      <template v-else-if="fieldType === 'select'">
        <span v-if="!edit" class="cfge__value">{{ displayValue }}</span>
        <select
          v-else
          :id="inputId"
          class="cfge__input cfge__input--select"
          :name="`setup_channel_${row.field.name}`"
          :value="row.value"
          @change="onInput"
        >
          <option v-for="choice in row.field.choices || []" :key="choice" :value="choice">{{ choice }}</option>
        </select>
      </template>

      <template v-else>
        <span v-if="!edit" class="cfge__value">{{ displayValue }}</span>
        <input
          v-else
          :id="inputId"
          class="cfge__input"
          :type="inputType"
          :value="row.value"
          :placeholder="placeholder"
          :name="`setup_channel_${row.field.name}`"
          :autocomplete="isSecretInput ? 'new-password' : undefined"
          :data-secret="isSecretInput ? 'true' : undefined"
          @input="onInput"
        />
      </template>

      <span v-if="row.field.description" class="cfge__desc">{{ row.field.description }}</span>
      <p v-if="edit && error" class="cfge__field-error" role="alert">{{ error }}</p>
    </div>
  </div>
</template>
