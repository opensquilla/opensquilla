<script setup lang="ts">
// Platform type gallery for the compose takeover: quiet cards, three-up,
// real buttons. Card metadata (label, transport, description) comes from the
// onboarding catalog — the same module-scope cache the editor uses — with
// descriptions localized through the channel-catalog overlay.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import ChannelBrandMark from '@/components/setup/ChannelBrandMark.vue'
import { useChannelCatalogI18n } from '@/composables/setup/useChannelCatalogI18n'
import type { ChannelEditorSpec } from '@/composables/channels/useChannelEditor'

const props = defineProps<{
  channels: ChannelEditorSpec[]
  pending: boolean
  error?: string
}>()

const emit = defineEmits<{
  pick: [type: string]
  retry: []
}>()

const { t } = useI18n()
const { localizeDescription } = useChannelCatalogI18n()

const sorted = computed(() => [...props.channels].sort((a, b) => a.label.localeCompare(b.label)))

function humanize(value: string): string {
  return value.replace(/[_-]+/g, ' ').replace(/\b\w/g, char => char.toUpperCase())
}
</script>

<template>
  <div class="ctg" :aria-label="t('console.channels.compose.galleryLabel')" role="group">
    <div v-if="pending && channels.length === 0" class="ctg__grid" aria-hidden="true">
      <span v-for="n in 6" :key="n" class="ctg__skeleton"></span>
    </div>
    <p v-else-if="error && channels.length === 0" class="ctg__error" role="alert">
      <span>{{ t('console.channels.compose.catalogFailed', { error }) }}</span>
      <button type="button" class="btn btn--ghost" @click="emit('retry')">{{ t('console.common.retry') }}</button>
    </p>
    <div v-else class="ctg__grid">
      <button
        v-for="c in sorted"
        :key="c.type"
        type="button"
        class="ctg__card"
        :data-channel-type="c.type"
        @click="emit('pick', c.type)"
      >
        <span class="ctg__head">
          <ChannelBrandMark :type="c.type" :label="c.label" />
          <span class="ctg__id">
            <strong class="ctg__name">{{ c.label }}</strong>
            <span v-if="c.transport && c.transport !== 'unknown'" class="ctg__transport">{{ humanize(c.transport) }}</span>
          </span>
        </span>
        <span v-if="c.description" class="ctg__desc">{{ localizeDescription(c.type, c.description) }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.ctg__grid { display: grid; gap: var(--sp-2); grid-template-columns: repeat(3, 1fr); }
.ctg__card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  cursor: pointer;
  display: grid;
  font: inherit;
  gap: var(--sp-2);
  padding: 12px 14px;
  text-align: left;
}
.ctg__card:hover, .ctg__card:focus-visible { background: var(--bg-elevated); border-color: var(--border-strong, var(--border)); }
.ctg__card:focus-visible { box-shadow: var(--focus-ring); outline: 0; }
.ctg__head { align-items: center; display: flex; gap: 10px; min-width: 0; }
.ctg__id { display: grid; gap: 4px; min-width: 0; }
.ctg__name { color: var(--text); font-size: var(--fs-md); font-weight: 600; line-height: 1.2; }
.ctg__transport {
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  color: var(--text-muted);
  font-size: var(--fs-xs);
  justify-self: start;
  line-height: 1.4;
  padding: 0 8px;
  white-space: nowrap;
}
.ctg__desc { color: var(--text-muted); font-size: var(--fs-sm); line-height: 1.5; min-width: 0; overflow-wrap: anywhere; }
.ctg__skeleton { background: var(--bg-surface-2); border-radius: var(--radius-md); display: block; min-height: 84px; }
.ctg__error { align-items: center; color: var(--danger); display: flex; flex-wrap: wrap; font-size: var(--fs-sm); gap: var(--sp-2); justify-content: space-between; margin: 0; }

@media (max-width: 768px) {
  .ctg__grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 400px) {
  .ctg__grid { grid-template-columns: 1fr; }
}
</style>
