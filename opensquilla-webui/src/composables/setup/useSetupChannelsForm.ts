import { computed, ref, type ComputedRef } from 'vue'

interface ChannelSpec {
  type: string
  label: string
  fields?: Array<{ name: string; label: string; default?: string | boolean | number; [key: string]: unknown }>
  whatYouNeed?: string[]
}

interface ChannelFieldSpec {
  name: string
  label: string
  default?: string | boolean | number
  [key: string]: unknown
}

interface ChannelFieldRow {
  field: ChannelFieldSpec
  value: string
}

interface ChannelRuntimeRow {
  name: string
  type?: string
  connected?: boolean
  status?: string
}

interface ChannelsPanelContext {
  channelRuntimeRows: ComputedRef<ChannelRuntimeRow[]>
  catalogChannels: ComputedRef<ChannelSpec[]>
  channelSpec: ComputedRef<ChannelSpec | null>
  channelSpecFields: ComputedRef<ChannelFieldSpec[]>
}

export function buildChannelEntry(type: string, values: Record<string, unknown>): Record<string, unknown> {
  const entry: Record<string, unknown> = { type }
  Object.entries(values).forEach(([key, value]) => {
    if (value !== '' && value !== undefined) entry[key] = value
  })
  return entry
}

export function useSetupChannelsForm() {
  const channelType = ref('')
  const channelFieldValues = ref<Record<string, unknown>>({})
  const selectedChannelType = computed(() => channelType.value)

  const serialized = computed(() => JSON.stringify({ t: channelType.value, v: channelFieldValues.value }))
  // Seed from the initial state so the pristine form is never dirty while config loads.
  const baseline = ref(serialized.value)
  const isDirty = computed(() => serialized.value !== baseline.value)

  // The channels form is an entry composer: every (re)load resets the draft
  // to the selected type's defaults, so Discard and post-save reloads clear it.
  function initFromCatalog(channels: ChannelSpec[]) {
    if (channels.length > 0 && !channelType.value) {
      channelType.value = channels[0].type
    }
    resetForSpec(channels.find(c => c.type === channelType.value))
  }

  // Switching channel type resets the entry form; type choice alone is not an unsaved edit.
  function resetForSpec(spec: ChannelSpec | null | undefined) {
    channelFieldValues.value = {}
    spec?.fields?.forEach(field => {
      channelFieldValues.value[field.name] = field.default ?? ''
    })
    baseline.value = serialized.value
  }

  function updateField(name: string, value: unknown) {
    channelFieldValues.value[name] = value
  }

  function selectChannelType(value: string) {
    channelType.value = value
  }

  function payload(): Record<string, unknown> {
    return buildChannelEntry(channelType.value, channelFieldValues.value)
  }

  function channelFieldRows(fields: ChannelFieldSpec[]): ChannelFieldRow[] {
    return fields.map(field => ({
      field,
      value: String(channelFieldValues.value[field.name] ?? field.default ?? ''),
    }))
  }

  function createPanel(context: ChannelsPanelContext) {
    return computed(() => ({
      channelRuntimeRows: context.channelRuntimeRows.value,
      channelType: channelType.value,
      catalogChannels: context.catalogChannels.value,
      channelSpec: context.channelSpec.value,
      channelFields: channelFieldRows(context.channelSpecFields.value),
    }))
  }

  return {
    selectedChannelType,
    isDirty,
    initFromCatalog,
    resetForSpec,
    selectChannelType,
    updateField,
    payload,
    createPanel,
  }
}
