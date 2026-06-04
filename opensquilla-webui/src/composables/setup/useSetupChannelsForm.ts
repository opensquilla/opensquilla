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

  function initFromCatalog(channels: ChannelSpec[]) {
    if (channels.length > 0 && !channelType.value) {
      channelType.value = channels[0].type
    }
  }

  function resetForSpec(spec: ChannelSpec | null | undefined) {
    channelFieldValues.value = {}
    spec?.fields?.forEach(field => {
      channelFieldValues.value[field.name] = field.default ?? ''
    })
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
    initFromCatalog,
    resetForSpec,
    selectChannelType,
    updateField,
    payload,
    createPanel,
  }
}
