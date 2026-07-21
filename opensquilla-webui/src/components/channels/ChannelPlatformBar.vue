<script setup lang="ts">
// Tier-2 add entry for the /channels dashboard: a titled row of small platform
// chips shown BELOW the channel-card grid when 1–3 channels exist. Each chip is
// an "add entry" (not a channel instance) — picking one opens the compose form
// pre-picked for that platform, so multiple channels of the same platform stay
// possible. Types already configured are skipped, the rest are locale-ordered
// like the compose gallery, capped at six with a trailing "+N more" chip that
// opens the full compose gallery. This component is presentation + event wiring
// only; the catalog and used-types come from the host view.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import ChannelBrandMark from '@/components/setup/ChannelBrandMark.vue'
import { useChannelCatalogI18n } from '@/composables/setup/useChannelCatalogI18n'
import { orderChannelSpecs } from '@/composables/setup/channelPlatformOrder'
import type { ChannelEditorSpec } from '@/composables/channels/useChannelEditor'

// The chip row shows at most this many platforms; the remainder collapses into
// the "+N more" chip that opens the full compose gallery.
const PLATFORM_BAR_VISIBLE_CHIPS = 6

const props = defineProps<{
  channels: ChannelEditorSpec[]
  usedTypes: string[]
  pending: boolean
}>()

const emit = defineEmits<{
  pick: [type: string]
  more: []
}>()

const { t, locale } = useI18n()
const { localizeLabel } = useChannelCatalogI18n()

function displayLabel(spec: ChannelEditorSpec): string {
  return localizeLabel(spec.type, spec.label)
}

// Platforms NOT already configured, locale-ordered like the compose gallery.
const available = computed(() => {
  const used = new Set(props.usedTypes.map(type => String(type)))
  const unused = props.channels.filter(spec => !used.has(String(spec.type)))
  return orderChannelSpecs(unused, String(locale.value), displayLabel)
})

const shown = computed(() => available.value.slice(0, PLATFORM_BAR_VISIBLE_CHIPS))
const overflow = computed(() => Math.max(0, available.value.length - shown.value.length))
</script>

<template>
  <section
    v-if="pending || available.length > 0"
    class="ch-platbar"
    :aria-label="t('console.channels.home.platformBarLabel')"
  >
    <div class="ch-platbar__label">
      <Icon name="plus" :size="14" aria-hidden="true" />
      <span>{{ t('console.channels.home.platformBarLabel') }}</span>
    </div>
    <div class="ch-platbar__row">
      <button
        v-for="spec in shown"
        :key="spec.type"
        type="button"
        class="ch-platbar__chip"
        :data-channel-type="spec.type"
        @click="emit('pick', spec.type)"
      >
        <ChannelBrandMark class="ch-platbar__mark" :type="spec.type" :label="displayLabel(spec)" />
        <span class="ch-platbar__name">{{ displayLabel(spec) }}</span>
      </button>
      <button
        v-if="overflow > 0"
        type="button"
        class="ch-platbar__chip ch-platbar__chip--more"
        @click="emit('more')"
      >
        <span class="ch-platbar__name">{{ t('console.channels.home.platformBarMore', { count: overflow }) }}</span>
      </button>
    </div>
  </section>
</template>

<style scoped>
.ch-platbar {
  animation: ch-platbar-in var(--dur-base) var(--ease-out);
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  margin-top: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
}
@keyframes ch-platbar-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: none; }
}
.ch-platbar__label {
  align-items: center;
  color: var(--text-dim);
  display: flex;
  font-size: var(--fs-sm);
  gap: var(--sp-1);
  margin-bottom: var(--sp-2);
}
.ch-platbar__row { display: flex; flex-wrap: wrap; gap: var(--sp-2); }
.ch-platbar__chip {
  align-items: center;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  color: var(--text);
  cursor: pointer;
  display: inline-flex;
  font: inherit;
  gap: var(--sp-2);
  padding: 5px 13px 5px 6px;
  transition: border-color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}
.ch-platbar__chip:hover { background: var(--bg-elevated); border-color: var(--border-strong, var(--text)); }
.ch-platbar__chip:focus-visible { box-shadow: var(--focus-ring); outline: 0; }
.ch-platbar__chip :deep(.brand-mark) { font-size: 11px; height: 24px; width: 24px; }
.ch-platbar__name { font-size: var(--fs-sm); font-weight: 500; }
.ch-platbar__chip--more { border-style: dashed; color: var(--text-dim); padding-left: 13px; }
.ch-platbar__chip--more:hover { color: var(--text); }

@media (prefers-reduced-motion: reduce) {
  .ch-platbar { animation: none; }
  .ch-platbar__chip { transition: none; }
}
</style>
