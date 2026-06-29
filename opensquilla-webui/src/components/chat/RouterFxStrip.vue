<template>
  <div
    class="router-fx"
    :data-state="message.routerState"
    :data-source="message.routerSource"
    :data-observe="message.routerObserve ? 'true' : undefined"
    :data-static="message.routerStatic ? 'true' : undefined"
    :data-settled="message.routerSettled ? 'true' : undefined"
    :data-panel="message.routerPanel || 'real-candidates'"
  >
    <div class="router-fx-header">
      <span class="glyph">&#8592;</span>
      <span class="title">{{ t('chat.aiModelRouter') }}</span>
      <span class="glyph">&#8594;</span>
    </div>
    <div class="router-fx-grid" :style="gridStyle">
      <div
        v-for="(cell, cellIndex) in gridCells"
        :key="cell.tiers?.join(':') || `${cell.displayName}-${cellIndex}`"
        class="router-fx-cell"
        :data-cell-idx="cellIndex"
        :class="{ win: cellIndex === message.winnerIdx }"
      >
        <span class="nm" :title="cell.displayName" :aria-label="cell.displayName">
          <span class="nm-base">{{ cell.displayName }}</span>
          <span class="nm-win" aria-hidden="true">{{ cell.displayName }}</span>
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ChatRenderedMessage } from '@/types/chat'

const { t } = useI18n()

const props = defineProps<{
  message: ChatRenderedMessage
}>()

const gridCells = computed(() => props.message.gridCells || [])
const isLegacyGrid = computed(() => props.message.routerPanel === 'legacy-grid')
const gridColumnCount = computed(() => isLegacyGrid.value ? 5 : Math.min(4, Math.max(2, gridCells.value.length)))
const mobileGridColumnCount = computed(() => isLegacyGrid.value ? 3 : (gridCells.value.length > 2 ? 2 : Math.max(1, gridCells.value.length)))
const gridStyle = computed<Record<string, string>>(() => {
  return {
    '--router-fx-cols': String(gridColumnCount.value),
    '--router-fx-mobile-cols': String(mobileGridColumnCount.value),
  }
})
</script>

<style scoped>
.router-fx {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: min(calc(100% - 48px), 620px);
  margin: 0.375rem auto 0.25rem;
  padding: 0;
  user-select: none;
  --router-accent: var(--accent);
  --router-bg: var(--bg-surface);
  --router-surface: var(--bg-elevated);
  --router-hairline: var(--hairline);
  --router-text: var(--text);
  --router-muted: var(--text-dim);
  --router-danger: var(--danger);
  --router-cell-bg: color-mix(in srgb, var(--bg-surface) 72%, transparent);
}

.router-fx-header {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 2px 0 0;
  color: var(--router-muted);
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.44em;
  white-space: nowrap;
}

@media (max-width: 480px) {
  .router-fx-header {
    gap: 8px;
    font-size: 10px;
    letter-spacing: 0.18em;
  }

  .router-fx-header .title {
    padding-left: 0.18em;
  }
}

.router-fx-header .title {
  padding-left: 0.44em;
}

.router-fx-header .glyph {
  color: var(--router-accent);
  font-size: 12px;
  letter-spacing: 0;
}

.router-fx-grid {
  position: relative;
  display: grid;
  grid-template-columns: repeat(var(--router-fx-cols, 2), 1fr);
  grid-auto-rows: 34px;
  gap: 4px;
  padding: 8px;
  background:
    radial-gradient(color-mix(in srgb, var(--router-text) 8%, transparent) 0.7px, transparent 1.2px) 0 0 / 8px 8px,
    var(--router-surface);
  border: 1px solid var(--router-hairline);
  border-radius: 8px;
  overflow: hidden;
}

.router-fx-cell {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  padding: 0 6px;
  background: var(--router-cell-bg);
  border: 1px solid var(--router-hairline);
  border-radius: 4px;
  color: var(--router-text);
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 0.01em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: transform var(--dur-base) var(--ease-out), background var(--dur-base) var(--ease-out), color var(--dur-base) var(--ease-out), border-color var(--dur-base) var(--ease-out), box-shadow var(--dur-base) var(--ease-out);
}

.router-fx[data-panel="legacy-grid"] .router-fx-grid {
  grid-auto-rows: 30px;
}

.router-fx-cell .nm {
  display: grid;
  max-width: 100%;
  min-width: 0;
}

/* Normal and bold name variants are stacked from first paint so the winner
   reveal is a pure opacity crossfade: the cell never reflows text. */
.router-fx-cell .nm-base,
.router-fx-cell .nm-win {
  grid-area: 1 / 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: center;
}

.router-fx-cell .nm-win {
  font-weight: 600;
  opacity: 0;
}

.router-fx-cell.win {
  font-style: normal;
  animation: router-fx-winner-reveal var(--dur-enter) var(--ease-out) both;
}

.router-fx-cell.win .nm-base {
  animation: router-fx-winner-name-swap-out var(--dur-enter) var(--ease-out) both;
}

.router-fx-cell.win .nm-win {
  color: var(--router-accent);
  animation: router-fx-winner-name-swap-in var(--dur-enter) var(--ease-out) both;
}

.router-fx[data-source="fallback"] .router-fx-cell.win .nm-win {
  color: var(--router-danger);
}

.router-fx-cell.win::after {
  content: '';
  position: absolute;
  top: 3px;
  right: 3px;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--router-accent);
  opacity: 1;
  animation: router-fx-winner-dot-reveal var(--dur-enter) var(--ease-out) both;
}

.router-fx[data-source="fallback"] .router-fx-cell.win {
  animation-name: router-fx-winner-reveal-fallback;
}

.router-fx[data-source="fallback"] .router-fx-cell.win::after {
  background: var(--router-danger);
}

.router-fx[data-settled="true"] .router-fx-cell,
.router-fx[data-settled="true"] .router-fx-cell.win,
.router-fx[data-settled="true"] .router-fx-cell.win::after,
.router-fx[data-settled="true"] .router-fx-cell .nm-base,
.router-fx[data-settled="true"] .router-fx-cell .nm-win,
.router-fx[data-settled="true"] .router-fx-header .glyph {
  animation: none !important;
}

.router-fx[data-settled="true"] .router-fx-cell.win {
  background: color-mix(in srgb, var(--router-accent) 9%, var(--router-bg));
  border-color: var(--router-accent);
}

.router-fx[data-settled="true"] .router-fx-cell.win .nm-base {
  opacity: 0;
}

.router-fx[data-settled="true"] .router-fx-cell.win .nm-win {
  opacity: 1;
}

.router-fx[data-settled="true"][data-source="fallback"] .router-fx-cell.win {
  background: color-mix(in srgb, var(--router-danger) 9%, var(--router-bg));
  border-color: var(--router-danger);
}

@keyframes router-fx-winner-reveal {
  0% {
    background: var(--router-cell-bg);
    border-color: var(--router-hairline);
    transform: translateY(0);
    box-shadow: none;
  }
  100% {
    background: color-mix(in srgb, var(--router-accent) 9%, var(--router-bg));
    border-color: var(--router-accent);
    transform: translateY(-1px);
    box-shadow: 0 1px 0 color-mix(in srgb, var(--router-accent) 35%, transparent);
  }
}

@keyframes router-fx-winner-reveal-fallback {
  0% {
    background: var(--router-cell-bg);
    border-color: var(--router-hairline);
    transform: translateY(0);
    box-shadow: none;
  }
  100% {
    background: color-mix(in srgb, var(--router-danger) 9%, var(--router-bg));
    border-color: var(--router-danger);
    transform: translateY(-1px);
    box-shadow: 0 1px 0 color-mix(in srgb, var(--router-danger) 35%, transparent);
  }
}

@keyframes router-fx-winner-name-swap-out {
  0% { opacity: 1; }
  100% { opacity: 0; }
}

@keyframes router-fx-winner-name-swap-in {
  0% { opacity: 0; }
  100% { opacity: 1; }
}

@keyframes router-fx-winner-dot-reveal {
  0% { opacity: 0.72; }
  100% { opacity: 1; }
}

.router-fx[data-observe="true"] {
  opacity: 0.55;
}

.router-fx[data-observe="true"] .router-fx-header::after {
  content: 'observe';
  margin-left: 12px;
  padding: 1px 6px;
  border-radius: 3px;
  background: color-mix(in srgb, var(--router-muted) 16%, transparent);
  color: var(--router-muted);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.router-fx[data-observe="true"] .router-fx-cell.win {
  animation: none;
  background: color-mix(in srgb, var(--router-muted) 8%, transparent);
  border-color: color-mix(in srgb, var(--router-muted) 35%, transparent);
  color: var(--router-muted);
  font-weight: 500;
}

.router-fx[data-observe="true"] .router-fx-cell.win .nm-base,
.router-fx[data-observe="true"] .router-fx-cell.win .nm-win {
  animation: none;
}

.router-fx[data-observe="true"] .router-fx-cell.win .nm-base {
  opacity: 1;
}

.router-fx[data-observe="true"] .router-fx-cell.win .nm-win {
  opacity: 0;
}

.router-fx[data-static="true"] .router-fx-cell,
.router-fx[data-static="true"] .router-fx-cell .nm-base,
.router-fx[data-static="true"] .router-fx-cell .nm-win {
  animation: none;
}

.router-fx[data-static="true"] .router-fx-cell.win {
  animation: none;
  background: color-mix(in srgb, var(--router-accent) 9%, var(--router-bg));
  border-color: var(--router-accent);
  transform: translateY(-1px);
  box-shadow: 0 1px 0 color-mix(in srgb, var(--router-accent) 35%, transparent);
}

.router-fx[data-static="true"] .router-fx-cell.win .nm-base {
  opacity: 0;
}

.router-fx[data-static="true"] .router-fx-cell.win .nm-win {
  opacity: 1;
}

.router-fx[data-static="true"][data-source="fallback"] .router-fx-cell.win {
  background: color-mix(in srgb, var(--router-danger) 9%, var(--router-bg));
  border-color: var(--router-danger);
  box-shadow: 0 1px 0 color-mix(in srgb, var(--router-danger) 35%, transparent);
}

.router-fx[data-static="true"] .router-fx-cell.win::after {
  animation: none;
  opacity: 1;
}

@media (prefers-reduced-motion: reduce) {
  .router-fx-cell,
  .router-fx-cell .nm-base,
  .router-fx-cell .nm-win {
    animation: none !important;
    transition: none !important;
  }
}

@media (max-width: 640px) {
  .router-fx {
    width: min(calc(100% - 24px), 620px);
  }

  .router-fx-grid {
    grid-template-columns: repeat(var(--router-fx-mobile-cols, var(--router-fx-cols, 2)), 1fr);
    grid-auto-rows: 30px;
    padding: 6px;
    gap: 3px;
  }

  .router-fx-cell {
    font-size: 10px;
    padding: 0 5px;
  }

  .router-fx-header {
    font-size: 9.5px;
    letter-spacing: 0.36em;
  }
}
</style>
