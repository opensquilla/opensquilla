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
  // Fields of the currently-selected channel spec — kept so payload() can drop
  // values of fields that show_when has hidden.
  const activeFields = ref<ChannelFieldSpec[]>([])
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
    activeFields.value = (spec?.fields ?? []) as ChannelFieldSpec[]
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
    // Only submit values for fields that are currently visible. A hidden
    // field's stale value (e.g. a Socket-mode app_token left over after the
    // user switched connection_mode to webhook) must not be sent.
    const visible = new Set(channelFieldRows(activeFields.value).map(row => row.field.name))
    const filtered: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(channelFieldValues.value)) {
      if (visible.has(key)) filtered[key] = value
    }
    return buildChannelEntry(channelType.value, filtered)
  }

  // Current value of a field (user edit, else its default) — used both to render
  // a field and to evaluate other fields' show_when conditions against it.
  function fieldCurrentValue(name: string, fields: ChannelFieldSpec[]): string {
    const v = channelFieldValues.value[name]
    if (v !== undefined) return String(v ?? '')
    const f = fields.find(x => x.name === name)
    return String(f?.default ?? '')
  }

  // A field is shown unless its show_when references a controlling field whose
  // current value doesn't match. Backend ships show_when as `field.showWhen`,
  // e.g. { connection_mode: 'socket' } or { transport_name: 'webhook' }; all
  // keys must match. This is what makes the form show the fields for the chosen
  // connection mode instead of every field at once.
  function fieldVisible(field: ChannelFieldSpec, fields: ChannelFieldSpec[]): boolean {
    const showWhen = field.showWhen as Record<string, unknown> | undefined
    if (!showWhen || typeof showWhen !== 'object') return true
    return Object.entries(showWhen).every(
      ([ctrl, expected]) => fieldCurrentValue(ctrl, fields) === String(expected),
    )
  }

  function channelFieldRows(fields: ChannelFieldSpec[]): ChannelFieldRow[] {
    return fields
      .filter(field => fieldVisible(field, fields))
      .map(field => ({ field, value: fieldCurrentValue(field.name, fields) }))
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
