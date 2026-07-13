<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import ChannelStatusPill from '@/components/ChannelStatusPill.vue'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import PendingRestartBanner from '@/components/PendingRestartBanner.vue'
import SetupChannelSecretField from '@/components/setup/SetupChannelSecretField.vue'
import SetupField from '@/components/SetupField.vue'
import SetupNeedList from '@/components/SetupNeedList.vue'
import { usePendingRestart } from '@/composables/usePendingRestart'
import { lastErrorClass } from '@/lib/channelStatus'
import type { ChannelSecretRow } from '@/composables/setup/useSetupChannelsForm'
import type { ChannelEditState, ChannelTestState } from '@/composables/setup/useSetupCatalog'

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
  secretRows: readonly ChannelSecretRow[]
  mode: 'compose' | 'edit'
  editName: string
}

const props = defineProps<{
  panel: ChannelsPanelContract
  test?: ChannelTestState
  edit?: ChannelEditState
  duplicate?: RuntimeRow | null
}>()

const emit = defineEmits<{
  updateChannelType: [value: string]
  channelTypeChange: []
  updateChannelField: [name: string, value: unknown]
  save: []
  test: []
  editChannel: [name: string]
  addNew: []
  duplicateAsNew: []
  retryEdit: []
  replaceSecret: [name: string]
  cancelSecretReplace: [name: string]
  enableChannel: [name: string]
  disableChannel: [name: string]
  removeChannel: [name: string]
}>()

function onChannelTypeSelect(event: Event) {
  emit('updateChannelType', (event.target as HTMLSelectElement).value)
  emit('channelTypeChange')
}

const isEdit = computed(() => props.panel.mode === 'edit')
const editLoading = computed(() => props.edit?.phase === 'loading')
const editError = computed(() => (props.edit?.phase === 'error' ? props.edit : null))
const editRetryable = computed(() => {
  const code = editError.value?.code
  return code !== 'UNAUTHORIZED' && code !== 'NOT_FOUND'
})
const typeLabel = computed(() => {
  const spec = props.panel.catalogChannels.find(c => c.type === props.panel.channelType)
  return spec?.label || props.panel.channelType
})

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
        <template v-if="isEdit || editLoading || editError">
          <h3 class="control-section__title">{{ t('setup.channels.editTitle', { name: edit?.name || panel.editName }) }}</h3>
          <p class="control-section__desc setup-channels__edithead">
            <span v-if="isEdit" class="setup-channels__typechip">{{ typeLabel }}</span>
            <button type="button" class="setup-channels__link" @click="emit('addNew')">
              {{ t('setup.channels.addNewInstead') }}
            </button>
          </p>
        </template>
        <template v-else>
          <h3 class="control-section__title">{{ t('setup.channels.title') }}</h3>
          <p class="control-section__desc">{{ t('setup.channels.configuredCount', { count: panel.channelRuntimeRows.length }) }}</p>
        </template>
      </div>

      <div v-if="editLoading" class="setup-channels__loading"><LoadingSpinner /></div>

      <div v-else-if="editError" class="setup-channels__errorcard" role="alert">
        <strong>{{ editError.code === 'UNAUTHORIZED'
          ? t('setup.channels.editForbidden')
          : editError.code === 'NOT_FOUND'
            ? t('setup.channels.editGone', { name: editError.name })
            : t('setup.channels.editLoadFailed') }}</strong>
        <p v-if="editRetryable && editError.message">{{ editError.message }}</p>
        <div class="setup-channels__erroractions">
          <button v-if="editRetryable" type="button" class="btn btn--primary" @click="emit('retryEdit')">
            {{ t('setup.channels.editRetry') }}
          </button>
          <button type="button" class="btn btn--ghost" @click="emit('addNew')">
            {{ editError.code === 'NOT_FOUND' ? t('setup.channels.editSetUpNew') : t('setup.channels.editBack') }}
          </button>
        </div>
      </div>

      <template v-else>
        <label v-if="!isEdit" class="control-row">
          <div class="control-row__label-block"><span class="control-row__label">{{ t('setup.channels.channelType') }}</span></div>
          <div class="control-row__control">
            <select class="control-input" :value="panel.channelType" name="setup_channel_type" @change="onChannelTypeSelect">
              <option v-for="c in panel.catalogChannels" :key="c.type" :value="c.type">{{ c.label }}</option>
            </select>
          </div>
        </label>
        <SetupNeedList v-if="!isEdit" :items="panel.channelSpec?.whatYouNeed" :label="t('setup.channels.needs')" />
        <template v-for="row in panel.channelFields" :key="row.field.name">
          <div v-if="isEdit && row.field.name === 'name'" class="control-row">
            <div class="control-row__label-block">
              <span class="control-row__label">{{ row.field.label }}</span>
              <span class="control-row__desc">{{ t('setup.channels.nameLocked') }}</span>
            </div>
            <div class="control-row__control">
              <input class="control-input" type="text" readonly :value="panel.editName" name="setup_channel_name" />
            </div>
          </div>
          <SetupField
            v-else
            :field="row.field"
            :value="row.value"
            scope="channel"
            @update="(name, val) => emit('updateChannelField', name, val)"
          />
        </template>
        <SetupChannelSecretField
          v-for="row in panel.secretRows"
          :key="row.field.name"
          :field="row.field"
          :has-stored="row.hasStored"
          :replacing="row.replacing"
          :value="row.value"
          @replace="name => emit('replaceSecret', name)"
          @cancel-replace="name => emit('cancelSecretReplace', name)"
          @update="(name, val) => emit('updateChannelField', name, val)"
        />
        <div v-if="!isEdit && duplicate" class="setup-channels__dupwarn" role="alert">
          <span>{{ t('setup.channels.duplicateWarn', { name: duplicate.name, type: duplicate.type || '?' }) }}</span>
          <button type="button" class="btn btn--ghost setup-channels__action" @click="emit('editChannel', duplicate.name)">
            {{ t('setup.channels.editInstead') }}
          </button>
        </div>
        <div class="control-section__actions">
          <button v-if="isEdit" type="button" class="btn btn--ghost" @click="emit('duplicateAsNew')">
            {{ t('setup.channels.duplicateAsNew') }}
          </button>
          <button class="btn btn--ghost" type="button" :disabled="testing" @click="emit('test')">
            {{ testing ? t('setup.channels.testing') : t('setup.channels.testConnection') }}
          </button>
          <button class="btn btn--primary" @click="emit('save')">
            {{ isEdit ? t('setup.channels.saveChanges') : t('setup.channels.save') }}
          </button>
        </div>
        <p v-if="testLine" :class="['setup-channels__test', testTone]" role="status">{{ testLine }}</p>
      </template>
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
            <button type="button" class="btn btn--ghost setup-channels__action" @click="emit('editChannel', row.name)">{{ t('setup.channels.edit') }}</button>
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

.setup-channels__edithead { align-items: center; display: flex; gap: var(--sp-2); }
.setup-channels__typechip {
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  color: var(--text-muted);
  font-size: var(--fs-sm);
  padding: 1px 10px;
  white-space: nowrap;
}
.setup-channels__link {
  background: transparent;
  border: 0;
  color: var(--accent);
  cursor: pointer;
  font: inherit;
  font-size: var(--fs-sm);
  padding: 0;
}
.setup-channels__link:hover { text-decoration: underline; }

.setup-channels__loading { display: flex; justify-content: center; padding: var(--sp-5) 0; }

.setup-channels__errorcard {
  background: color-mix(in srgb, var(--danger) 6%, var(--bg-surface));
  border: 1px solid color-mix(in srgb, var(--danger) 36%, var(--border));
  border-radius: var(--radius-md);
  display: grid;
  gap: var(--sp-2);
  padding: var(--sp-3) var(--sp-4);
}
.setup-channels__errorcard strong { color: var(--danger); font-size: var(--fs-sm); }
.setup-channels__errorcard p { color: var(--text-muted); font-size: var(--fs-sm); margin: 0; }
.setup-channels__erroractions { display: flex; gap: var(--sp-2); }

.setup-channels__dupwarn {
  align-items: center;
  background: color-mix(in srgb, var(--warn) 8%, var(--bg-surface));
  border: 1px solid color-mix(in srgb, var(--warn) 38%, var(--border));
  border-radius: var(--radius-md);
  color: var(--text-muted);
  display: flex;
  flex-wrap: wrap;
  font-size: var(--fs-sm);
  gap: var(--sp-2);
  justify-content: space-between;
  margin-top: var(--sp-2);
  padding: 8px 12px;
}
</style>
