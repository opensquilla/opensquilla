<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import SetupField from '@/components/SetupField.vue'
import SetupNeedList from '@/components/SetupNeedList.vue'

const { t } = useI18n()

interface ChannelSpec {
  type: string
  label: string
  fields?: FieldSpec[]
  whatYouNeed?: string[]
}

interface FieldSpec {
  name: string
  label: string
  default?: string | boolean | number
  [key: string]: unknown
}

interface ChannelFieldRow {
  field: FieldSpec
  value: string
}

interface RuntimeRow {
  name: string
  type?: string
  connected?: boolean
  status?: string
  enabled?: boolean
}

interface ChannelsPanelContract {
  channelRuntimeRows: RuntimeRow[]
  channelType: string
  catalogChannels: ChannelSpec[]
  channelSpec: ChannelSpec | null
  channelFields: readonly ChannelFieldRow[]
}

defineProps<{
  panel: ChannelsPanelContract
}>()

const emit = defineEmits<{
  updateChannelType: [value: string]
  channelTypeChange: []
  updateChannelField: [name: string, value: unknown]
  save: []
  enableChannel: [name: string]
  disableChannel: [name: string]
  removeChannel: [name: string]
}>()

function onChannelTypeSelect(event: Event) {
  emit('updateChannelType', (event.target as HTMLSelectElement).value)
  emit('channelTypeChange')
}
</script>

<template>
  <div class="setup-channels">
    <section class="control-section">
      <div class="control-section__head">
        <h3 class="control-section__title">{{ t('setup.channels.title') }}</h3>
        <p class="control-section__desc">{{ t('setup.channels.configuredCount', { count: panel.channelRuntimeRows.length }) }}</p>
      </div>
      <label class="control-row">
        <div class="control-row__label-block"><span class="control-row__label">{{ t('setup.channels.channelType') }}</span></div>
        <div class="control-row__control">
          <select class="control-input" :value="panel.channelType" name="setup_channel_type" @change="onChannelTypeSelect">
            <option v-for="c in panel.catalogChannels" :key="c.type" :value="c.type">{{ c.label }}</option>
          </select>
        </div>
      </label>
      <SetupNeedList :items="panel.channelSpec?.whatYouNeed" :label="t('setup.channels.needs')" />
      <SetupField
        v-for="row in panel.channelFields"
        :key="row.field.name"
        :field="row.field"
        :value="row.value"
        scope="channel"
        @update="(name, val) => emit('updateChannelField', name, val)"
      />
      <div class="control-section__actions">
        <button class="btn btn--primary" @click="emit('save')">{{ t('setup.channels.save') }}</button>
      </div>
    </section>
    <section class="control-section setup-runtime">
      <h3 class="control-section__title">{{ t('setup.channels.runtimeStatus') }}</h3>
      <template v-if="panel.channelRuntimeRows.length > 0">
        <div v-for="row in panel.channelRuntimeRows" :key="row.name" class="setup-runtime__row" :class="row.connected === true ? 'is-ok' : 'is-warn'">
          <span>{{ row.name }}</span>
          <span>{{ row.type || '' }}</span>
          <strong>{{ row.enabled === false ? t('setup.channels.disabled') : (row.connected === true ? t('setup.channels.connected') : (row.status === 'stopped' ? t('setup.channels.actionNeeded') : row.status || t('setup.channels.connecting'))) }}</strong>
          <span class="setup-channels__actions">
            <button v-if="row.enabled === false" type="button" class="btn btn--ghost setup-channels__action" @click="emit('enableChannel', row.name)">{{ t('setup.channels.enable') }}</button>
            <button v-else type="button" class="btn btn--ghost setup-channels__action" @click="emit('disableChannel', row.name)">{{ t('setup.channels.disable') }}</button>
            <button type="button" class="btn btn--ghost setup-channels__action setup-channels__remove" @click="emit('removeChannel', row.name)">{{ t('setup.channels.remove') }}</button>
          </span>
        </div>
      </template>
      <p v-else class="setup-muted">{{ t('setup.channels.none') }}</p>
    </section>
  </div>
</template>

<style scoped>
.setup-channels__actions {
  display: flex;
  gap: var(--sp-2);
}

.setup-channels__action {
  padding: 2px 10px;
  font-size: var(--fs-sm);
}

.setup-channels__remove {
  color: var(--danger);
}
</style>
