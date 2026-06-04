<template>
  <div
    class="router-fx"
    :data-state="message.routerState"
    :data-source="message.routerSource"
    :data-observe="message.routerObserve ? 'true' : undefined"
    :data-static="message.routerStatic ? 'true' : undefined"
    :data-settled="message.routerSettled ? 'true' : undefined"
  >
    <div class="router-fx-header">
      <span class="glyph">&#8592;</span>
      <span class="title">model router</span>
      <span class="glyph">&#8594;</span>
    </div>
    <div class="router-fx-grid">
      <div
        v-for="(cell, cellIndex) in gridCells"
        :key="cellIndex"
        class="router-fx-cell"
        :data-kind="cell.kind"
        :data-cell-idx="cellIndex"
        :data-tiers="cell.tiers?.join(',')"
        :class="{ win: cellIndex === message.winnerIdx }"
      >
        <span class="nm">{{ cell.displayName }}</span>
      </div>
      <div
        v-if="hasWinner"
        class="router-fx-selector visible lock"
        :class="{ 'lock-impact': !message.routerStatic && !message.routerSettled }"
        :style="selectorStyle"
        aria-hidden="true"
      />
      <div
        v-if="hasWinner && !message.routerStatic && !message.routerSettled"
        class="router-fx-burst"
        :style="burstStyle"
        aria-hidden="true"
      >
        <i v-for="n in 6" :key="n" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ChatRenderedMessage } from '@/types/chat'

const props = defineProps<{
  message: ChatRenderedMessage
}>()

const ROUTER_FX_GRID_COLS = 4

const gridCells = computed(() => props.message.gridCells || [])

const hasWinner = computed(() => Number(props.message.winnerIdx) >= 0)

const selectorStyle = computed<Record<string, string>>(() => {
  const idx = Math.max(0, Number(props.message.winnerIdx ?? 0))
  const col = idx % ROUTER_FX_GRID_COLS
  const row = Math.floor(idx / ROUTER_FX_GRID_COLS)
  const lefts = [
    '8px',
    'calc(((100% - 28px) / 4) + 12px)',
    'calc(((100% - 28px) / 2) + 16px)',
    'calc(((100% - 28px) * 3 / 4) + 20px)',
  ]
  return {
    '--router-left': lefts[col] || '8px',
    '--router-top': `${8 + row * 34}px`,
  }
})

const burstStyle = computed<Record<string, string>>(() => {
  const idx = Math.max(0, Number(props.message.winnerIdx ?? 0))
  const col = idx % ROUTER_FX_GRID_COLS
  const row = Math.floor(idx / ROUTER_FX_GRID_COLS)
  const lefts = [
    'calc(((100% - 28px) / 8) + 8px)',
    'calc(((100% - 28px) * 3 / 8) + 12px)',
    'calc(((100% - 28px) * 5 / 8) + 16px)',
    'calc(((100% - 28px) * 7 / 8) + 20px)',
  ]
  return {
    '--router-burst-left': lefts[col] || 'calc(12.5% + 4.5px)',
    '--router-burst-top': `${23 + row * 34}px`,
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
  --router-accent: var(--accent, #f56600);
  --router-bg: #fff;
  --router-surface: #fafafa;
  --router-hairline: rgba(24, 24, 27, 0.09);
  --router-text: #27272a;
  --router-muted: #8b8b93;
  --router-danger: #dc2626;
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
}

.router-fx-header .title {
  padding-left: 0.44em;
}

.router-fx-header .glyph {
  color: var(--router-accent);
  font-size: 12px;
  letter-spacing: 0;
  animation: router-fx-chev 900ms cubic-bezier(.4,0,.6,1) 2;
}

.router-fx-header .glyph:last-child {
  animation-delay: 450ms;
}

@keyframes router-fx-chev {
  0%, 100% { transform: translateX(0); }
  50% { transform: translateX(3px); }
}

.router-fx-grid {
  position: relative;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  grid-template-rows: repeat(3, 30px);
  gap: 4px;
  padding: 8px;
  background:
    radial-gradient(rgba(24, 24, 27, 0.08) 0.7px, transparent 1.2px) 0 0 / 8px 8px,
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
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid var(--router-hairline);
  border-radius: 4px;
  color: var(--router-text);
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 0.01em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: transform 220ms cubic-bezier(.34,1.65,.5,1), background 240ms ease, color 240ms ease, border-color 240ms ease, box-shadow 240ms ease;
}

.router-fx-cell[data-kind="real"]::after {
  content: '';
  position: absolute;
  top: 3px;
  right: 3px;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--router-accent);
  opacity: 0.72;
}

.router-fx-cell[data-kind="decoy"] {
  color: var(--router-muted);
  font-style: italic;
  opacity: 0.78;
}

@keyframes router-fx-mole-pop {
  0% { transform: translateY(0) scale(1); background: rgba(255, 255, 255, 0.72); }
  35% { transform: translateY(-2px) scale(1.14); background: color-mix(in srgb, var(--router-accent) 14%, #fff); }
  100% { transform: translateY(0) scale(1); background: rgba(255, 255, 255, 0.72); }
}

.router-fx-cell:nth-child(2),
.router-fx-cell:nth-child(6),
.router-fx-cell:nth-child(9),
.router-fx-cell:nth-child(4) {
  animation: router-fx-mole-pop 190ms cubic-bezier(.34,1.7,.5,1) both;
}

.router-fx-cell:nth-child(2) { animation-delay: 80ms; }
.router-fx-cell:nth-child(6) { animation-delay: 280ms; }
.router-fx-cell:nth-child(9) { animation-delay: 520ms; }
.router-fx-cell:nth-child(4) { animation-delay: 760ms; }

.router-fx-cell .nm {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.router-fx-cell.win {
  font-style: normal;
  animation: router-fx-winner-reveal 1.42s linear both;
}

.router-fx-cell.win::after {
  animation: router-fx-winner-dot-reveal 1.42s linear both;
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
.router-fx[data-settled="true"] .router-fx-header .glyph {
  animation: none !important;
}

.router-fx[data-settled="true"] .router-fx-cell.win {
  color: var(--router-accent);
  background: color-mix(in srgb, var(--router-accent) 9%, #fff);
  border-color: var(--router-accent);
  font-weight: 600;
}

.router-fx[data-settled="true"][data-source="fallback"] .router-fx-cell.win {
  color: var(--router-danger);
  background: color-mix(in srgb, var(--router-danger) 9%, #fff);
  border-color: var(--router-danger);
}

.router-fx[data-settled="true"] .router-fx-selector {
  transition: left 360ms cubic-bezier(.4,.0,.2,1), top 360ms cubic-bezier(.4,.0,.2,1);
}

@keyframes router-fx-winner-reveal {
  0%, 89% {
    color: var(--router-text);
    background: rgba(255, 255, 255, 0.72);
    border-color: var(--router-hairline);
    font-weight: 400;
    transform: translateY(0);
    box-shadow: none;
  }
  100% {
    color: var(--router-accent);
    background: color-mix(in srgb, var(--router-accent) 9%, #fff);
    border-color: var(--router-accent);
    font-weight: 600;
    transform: translateY(-1px);
    box-shadow: 0 1px 0 color-mix(in srgb, var(--router-accent) 35%, transparent);
  }
}

@keyframes router-fx-winner-reveal-fallback {
  0%, 89% {
    color: var(--router-text);
    background: rgba(255, 255, 255, 0.72);
    border-color: var(--router-hairline);
    font-weight: 400;
    transform: translateY(0);
    box-shadow: none;
  }
  100% {
    color: var(--router-danger);
    background: color-mix(in srgb, var(--router-danger) 9%, #fff);
    border-color: var(--router-danger);
    font-weight: 600;
    transform: translateY(-1px);
    box-shadow: 0 1px 0 color-mix(in srgb, var(--router-danger) 35%, transparent);
  }
}

@keyframes router-fx-winner-dot-reveal {
  0%, 89% { opacity: 0.72; }
  100% { opacity: 1; }
}

.router-fx-selector {
  position: absolute;
  z-index: 2;
  top: 8px;
  left: 8px;
  width: calc((100% - 28px) / 4);
  height: 30px;
  border: 2px solid color-mix(in srgb, var(--router-accent) 80%, transparent);
  border-radius: 4px;
  background: color-mix(in srgb, var(--router-accent) 6%, transparent);
  pointer-events: none;
  opacity: 0;
  transform: rotate(0deg);
}

.router-fx-selector.visible {
  opacity: 1;
}

.router-fx-selector.lock {
  border-color: var(--router-accent);
  background: color-mix(in srgb, var(--router-accent) 12%, transparent);
  box-shadow:
    0 0 0 1px color-mix(in srgb, var(--router-accent) 22%, transparent),
    inset 0 0 0 1px color-mix(in srgb, var(--router-accent) 8%, transparent);
}

.router-fx[data-source="fallback"] .router-fx-selector.lock {
  border-color: var(--router-danger);
  background: color-mix(in srgb, var(--router-danger) 12%, transparent);
  box-shadow:
    0 0 0 1px color-mix(in srgb, var(--router-danger) 22%, transparent),
    inset 0 0 0 1px color-mix(in srgb, var(--router-danger) 8%, transparent);
}

@keyframes router-fx-selector-chase {
  0% { opacity: 1; left: 8px; top: 8px; transform: rotate(1.4deg); }
  12% { left: calc(((100% - 28px) / 2) + 16px); top: 8px; transform: rotate(-1.4deg); }
  25% { left: calc(((100% - 28px) / 4) + 12px); top: 42px; transform: rotate(1.4deg); }
  42% { left: calc(((100% - 28px) * 3 / 4) + 20px); top: 42px; transform: rotate(-1.4deg); }
  62% { left: 8px; top: 76px; transform: rotate(1.4deg); }
  78% { left: calc(((100% - 28px) / 2) + 16px); top: 76px; transform: rotate(-1.4deg); }
  100% { opacity: 1; left: var(--router-left); top: var(--router-top); transform: rotate(0deg); }
}

.router-fx-selector.lock-impact {
  animation: router-fx-selector-chase 1.28s cubic-bezier(.18,1.25,.45,1) both, router-fx-impact 280ms cubic-bezier(.34,1.6,.5,1) 1.28s both;
}

@keyframes router-fx-impact {
  0% { outline: 0 solid transparent; outline-offset: 0; }
  35% { outline: 2px solid color-mix(in srgb, var(--router-accent) 70%, transparent); outline-offset: 4px; }
  100% { outline: 0 solid transparent; outline-offset: 0; }
}

.router-fx-burst {
  position: absolute;
  z-index: 4;
  left: var(--router-burst-left);
  top: var(--router-burst-top);
  width: 0;
  height: 0;
  pointer-events: none;
}

.router-fx-burst i {
  position: absolute;
  left: -2px;
  top: -2px;
  width: 4px;
  height: 4px;
  border-radius: 1px;
  background: var(--router-accent);
  opacity: 0;
  animation: router-fx-burst 540ms cubic-bezier(.2,.7,.2,1) 1.38s forwards;
}

.router-fx-burst i:nth-child(1) { --bx: -22px; --by: -10px; }
.router-fx-burst i:nth-child(2) { --bx: 22px; --by: -10px; }
.router-fx-burst i:nth-child(3) { --bx: -22px; --by: 10px; }
.router-fx-burst i:nth-child(4) { --bx: 22px; --by: 10px; }
.router-fx-burst i:nth-child(5) { --bx: 0; --by: -18px; width: 3px; height: 3px; }
.router-fx-burst i:nth-child(6) { --bx: 0; --by: 18px; width: 3px; height: 3px; }

@keyframes router-fx-burst {
  0% { opacity: 1; transform: translate(0, 0) scale(1); }
  60% { opacity: 0.7; }
  100% { opacity: 0; transform: translate(var(--bx, 16px), var(--by, 0)) scale(0.4); }
}

.router-fx[data-source="fallback"] .router-fx-burst i {
  background: var(--router-danger);
}

.router-fx[data-observe="true"] {
  opacity: 0.55;
}

.router-fx[data-observe="true"] .router-fx-header::after {
  content: 'observe';
  margin-left: 12px;
  padding: 1px 6px;
  border-radius: 3px;
  background: rgba(139, 139, 147, 0.16);
  color: var(--router-muted);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.router-fx[data-observe="true"] .router-fx-selector.lock-impact,
.router-fx[data-observe="true"] .router-fx-burst i,
.router-fx[data-observe="true"] .router-fx-header .glyph {
  animation: none;
}

.router-fx[data-observe="true"] .router-fx-selector {
  left: var(--router-left);
  top: var(--router-top);
  transform: rotate(0deg);
  opacity: 1;
}

.router-fx[data-observe="true"] .router-fx-cell.win {
  animation: none;
  background: rgba(139, 139, 147, 0.08);
  border-color: rgba(139, 139, 147, 0.35);
  color: var(--router-muted);
  font-weight: 500;
}

.router-fx[data-static="true"] .router-fx-cell,
.router-fx[data-static="true"] .router-fx-header .glyph,
.router-fx[data-static="true"] .router-fx-selector {
  animation: none;
}

.router-fx[data-static="true"] .router-fx-selector {
  left: var(--router-left);
  top: var(--router-top);
  transform: rotate(0deg);
  opacity: 1;
}

.router-fx[data-static="true"] .router-fx-cell.win {
  animation: none;
  color: var(--router-accent);
  background: color-mix(in srgb, var(--router-accent) 9%, #fff);
  border-color: var(--router-accent);
  font-weight: 600;
  transform: translateY(-1px);
  box-shadow: 0 1px 0 color-mix(in srgb, var(--router-accent) 35%, transparent);
}

.router-fx[data-static="true"][data-source="fallback"] .router-fx-cell.win {
  color: var(--router-danger);
  background: color-mix(in srgb, var(--router-danger) 9%, #fff);
  border-color: var(--router-danger);
  box-shadow: 0 1px 0 color-mix(in srgb, var(--router-danger) 35%, transparent);
}

.router-fx[data-static="true"] .router-fx-cell.win::after {
  animation: none;
  opacity: 1;
}

@media (prefers-reduced-motion: reduce) {
  .router-fx-cell,
  .router-fx-selector,
  .router-fx-burst i,
  .router-fx-header .glyph {
    animation: none !important;
    transition: none !important;
  }

  .router-fx-selector {
    left: var(--router-left);
    top: var(--router-top);
    transform: rotate(0deg);
    opacity: 1;
  }
}
</style>
