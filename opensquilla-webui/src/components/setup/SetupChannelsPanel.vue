<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import ChannelStatusPill from '@/components/ChannelStatusPill.vue'
import PendingRestartBanner from '@/components/PendingRestartBanner.vue'
import SetupField from '@/components/SetupField.vue'
import SetupNeedList from '@/components/SetupNeedList.vue'
import { usePendingRestart } from '@/composables/usePendingRestart'
import { lastErrorClass } from '@/lib/channelStatus'
import type { ChannelTestState } from '@/composables/setup/useSetupCatalog'

const { t } = useI18n()
const pendingRestart = usePendingRestart()

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
  diagnostics?: Record<string, unknown>
}

interface ChannelsPanelContract {
  channelRuntimeRows: RuntimeRow[]
  channelType: string
  catalogChannels: ChannelSpec[]
  channelSpec: ChannelSpec | null
  channelFields: readonly ChannelFieldRow[]
}

const props = defineProps<{
  panel: ChannelsPanelContract
  test?: ChannelTestState
}>()

const emit = defineEmits<{
  updateChannelType: [value: string]
  channelTypeChange: []
  updateChannelField: [name: string, value: unknown]
  save: []
  test: []
  enableChannel: [name: string]
  disableChannel: [name: string]
  removeChannel: [name: string]
}>()

function onChannelTypeSelect(event: Event) {
  emit('updateChannelType', (event.target as HTMLSelectElement).value)
  emit('channelTypeChange')
}

const testing = computed(() => props.test?.phase === 'testing')

// Persistent inline verdict (not a toast) — it describes the current draft
// and is cleared by the composable the moment the draft changes.
const testLine = computed(() => {
  const test = props.test
  if (!test || test.phase !== 'done') return ''
  switch (test.status) {
    case 'verified':
      return t('setup.channels.testVerified', { ms: test.latencyMs ?? 0 })
    case 'failed':
      return t('setup.channels.testFailed', { detail: test.detail || t('setup.channels.testNoDetail') })
    case 'unsupported':
      return test.detail || t('setup.channels.testUnsupported')
    default:
      return t('setup.channels.testError', { error: test.detail || '' })
  }
})

const testTone = computed(() => {
  switch (props.test?.status) {
    case 'verified': return 'is-ok'
    case 'failed':
    case 'error': return 'is-danger'
    default: return 'is-muted'
  }
})
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
        <button class="btn btn--ghost" type="button" :disabled="testing" @click="emit('test')">
          {{ testing ? t('setup.channels.testing') : t('setup.channels.testConnection') }}
        </button>
        <button class="btn btn--primary" @click="emit('save')">{{ t('setup.channels.save') }}</button>
      </div>
      <p v-if="testLine" :class="['setup-channels__test', testTone]" role="status">{{ testLine }}</p>
    </section>
    <section class="control-section setup-runtime">
      <h3 class="control-section__title">{{ t('setup.channels.runtimeStatus') }}</h3>
      <PendingRestartBanner />
      <template v-if="panel.channelRuntimeRows.length > 0">
        <div v-for="row in panel.channelRuntimeRows" :key="row.name" class="setup-runtime__row">
          <span>{{ row.name }}</span>
          <span>{{ row.type || '' }}</span>
          <ChannelStatusPill
            :status="row.status"
            :enabled="row.enabled"
            :pending-restart="pendingRestart.isPending(row.name)"
            :error-class="lastErrorClass(row.diagnostics)"
            show-cause
          />
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

.setup-channels__test {
  font-size: var(--fs-sm);
  margin: var(--sp-2) 0 0;
}

.setup-channels__test.is-ok { color: var(--ok); }
.setup-channels__test.is-danger { color: var(--danger); }
.setup-channels__test.is-muted { color: var(--text-muted); }
</style>
