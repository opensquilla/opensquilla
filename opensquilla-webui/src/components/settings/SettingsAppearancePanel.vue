<script setup lang="ts">
import { useAppStore, type ThemeMode } from '@/stores/app'
import Icon from '@/components/Icon.vue'

// Client-only preferences: applied instantly to this browser and persisted via
// the theme store. No readiness state; never part of the settings dirty bar.
// This is theme's canonical home — the sidebar theme button is a reactive
// shortcut over the SAME store, so the two can never drift.
const appStore = useAppStore()

const themeOptions = [
  { mode: 'system', label: 'System', icon: 'monitor' },
  { mode: 'light', label: 'Light', icon: 'sun' },
  { mode: 'dark', label: 'Dark', icon: 'moon' },
] as const

function pickTheme(mode: ThemeMode) {
  appStore.setTheme(mode)
}
</script>

<template>
  <section class="control-section">
    <div class="control-section__head">
      <h3 class="control-section__title">Appearance</h3>
      <p class="control-section__desc">Theme for this browser. Changes apply instantly &mdash; no save needed.</p>
    </div>

    <div class="control-row">
      <div class="control-row__label-block">
        <span class="control-row__label">Theme</span>
        <span class="control-row__desc">Follow your system, or force light or dark. The sidebar toggle is a shortcut to this same setting.</span>
      </div>
      <div class="control-row__control">
        <!-- Native radio group: the browser handles arrow-key roving, focus and
             state announcement; the inputs are visually hidden and the labels
             render the segmented control. -->
        <div class="appearance-theme" role="radiogroup" aria-label="Theme">
          <label
            v-for="opt in themeOptions"
            :key="opt.mode"
            class="appearance-theme__opt"
            :class="{ 'is-active': appStore.theme === opt.mode }"
          >
            <input
              class="appearance-theme__radio"
              type="radio"
              name="appearance-theme"
              :value="opt.mode"
              :checked="appStore.theme === opt.mode"
              @change="pickTheme(opt.mode)"
            >
            <Icon :name="opt.icon" :size="15" aria-hidden="true" />
            <span>{{ opt.label }}</span>
          </label>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.appearance-theme {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}

.appearance-theme__opt {
  align-items: center;
  background: transparent;
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
  font-size: var(--fs-sm);
  gap: var(--sp-1);
  padding: 6px var(--sp-3);
  position: relative;
}

/* Visually hidden but focusable / arrow-navigable native radio. */
.appearance-theme__radio {
  height: 1px;
  margin: 0;
  opacity: 0;
  position: absolute;
  width: 1px;
}

.appearance-theme__opt:hover {
  color: var(--text);
}

.appearance-theme__opt.is-active {
  background: var(--bg-surface);
  box-shadow: var(--shadow-xs);
  color: var(--text);
}

.appearance-theme__opt:focus-within {
  outline: 2px solid color-mix(in srgb, var(--accent) 45%, transparent);
  outline-offset: 2px;
}
</style>
