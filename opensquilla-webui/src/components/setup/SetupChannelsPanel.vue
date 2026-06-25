<script setup lang="ts">
import SetupField from '@/components/SetupField.vue'
import SetupNeedList from '@/components/SetupNeedList.vue'

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
}>()

function onChannelTypeSelect(event: Event) {
  emit('updateChannelType', (event.target as HTMLSelectElement).value)
  emit('channelTypeChange')
}
</script>

<template>
  <section class="setup-panel">
    <header class="setup-panel__head">
      <h3>Channels</h3>
      <p>{{ panel.channelRuntimeRows.length }} configured</p>
    </header>
    <div class="setup-channel-grid">
      <div class="setup-form">
        <label>
          <span>Channel type</span>
          <select :value="panel.channelType" name="setup_channel_type" @change="onChannelTypeSelect">
            <option v-for="c in panel.catalogChannels" :key="c.type" :value="c.type">{{ c.label }}</option>
          </select>
        </label>
        <SetupNeedList :items="panel.channelSpec?.whatYouNeed" label="Channel needs" />
        <div class="setup-channel-fields">
          <SetupField
            v-for="row in panel.channelFields"
            :key="row.field.name"
            :field="row.field"
            :value="row.value"
            scope="channel"
            @update="(name, val) => emit('updateChannelField', name, val)"
          />
        </div>
        <div class="setup-actions">
          <button class="setup-btn setup-btn--primary" @click="emit('save')">Save Channel</button>
        </div>
      </div>
      <div class="setup-runtime">
        <h4>Runtime status</h4>
        <template v-if="panel.channelRuntimeRows.length > 0">
          <div v-for="row in panel.channelRuntimeRows" :key="row.name" class="setup-runtime__row" :class="row.connected === true ? 'is-ok' : 'is-warn'">
            <span>{{ row.name }}</span>
            <span>{{ row.type || '' }}</span>
            <strong>{{ row.connected === true ? 'Connected' : (row.status === 'stopped' ? 'Action needed' : row.status || 'connecting') }}</strong>
          </div>
        </template>
        <p v-else class="setup-muted">No channels configured.</p>
      </div>
    </div>
  </section>
</template>
