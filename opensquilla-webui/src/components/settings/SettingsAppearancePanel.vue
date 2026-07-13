<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useAppStore, type ThemeMode } from '@/stores/app'
import { themePickerOptions } from '@/themes/registry'
import { SUPPORTED_LOCALES, type LocaleCode } from '@/i18n'
import Icon from '@/components/Icon.vue'
import ControlSwitch from '@/components/ControlSwitch.vue'
import { useBgm } from '@/composables/useBgm'

// Client-only preferences: applied instantly to this browser and persisted via
// the app store. No readiness state; never part of the settings dirty bar.
// This is the canonical home for theme AND language — the sidebar theme button
// and the topbar LanguageSwitcher are reactive shortcuts over the SAME store, so
// the surfaces can never drift.
const appStore = useAppStore()
const { t } = useI18n()

// Registry-driven, full list: every selectable value theme (incl. custom ones) +
// system. The compact topbar menu shows only the basic modes (scope: 'basic')
// and links here via "More themes…"; this panel is the home for the full set.
const themeOptions = themePickerOptions({ scope: 'all' })

// Native language names — deliberately NOT translated.
const LOCALE_LABELS: Record<LocaleCode, string> = {
  en: 'English',
  'zh-Hans': '中文',
  'zh-Hant': '繁體中文',
  ja: '日本語',
  fr: 'Français',
  de: 'Deutsch',
  es: 'Español',
}
const localeOptions = SUPPORTED_LOCALES.map((code) => ({ code, label: LOCALE_LABELS[code] }))

function pickTheme(mode: ThemeMode) {
  appStore.setTheme(mode)
}

function pickLocale(code: LocaleCode) {
  void appStore.setLocale(code)
}

// Background-music feature gate (off by default). Same singleton the topbar
// control and the command palette read, so all three surfaces stay in lockstep.
const { enabled: bgmEnabled, setEnabled: setBgmEnabled } = useBgm()
</script>

<template>
  <section class="control-section">
    <div class="control-section__head">
      <h3 class="control-section__title">{{ t('settings.appearance.title') }}</h3>
      <p class="control-section__desc">{{ t('settings.appearance.desc') }}</p>
    </div>

    <div class="control-row control-row--stack">
      <div class="control-row__label-block">
        <span class="control-row__label">{{ t('settings.appearance.themeLabel') }}</span>
        <span class="control-row__desc">{{ t('settings.appearance.themeDesc') }}</span>
      </div>
      <div class="control-row__control">
        <!-- Native radio group: the browser handles arrow-key roving, focus and
             state announcement; the inputs are visually hidden and the labels
             render the segmented control. -->
        <div class="appearance-theme" role="radiogroup" :aria-label="t('settings.appearance.themeLabel')">
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
            <span>{{ opt.labelKey ? t(opt.labelKey) : opt.label }}</span>
          </label>
        </div>
      </div>
    </div>

    <div class="control-row control-row--stack">
      <div class="control-row__label-block">
        <span class="control-row__label">{{ t('settings.appearance.languageLabel') }}</span>
        <span class="control-row__desc">{{ t('settings.appearance.languageDesc') }}</span>
      </div>
      <div class="control-row__control">
        <div
          class="appearance-theme"
          role="radiogroup"
          :aria-label="t('settings.appearance.languageLabel')"
          data-testid="settings-language-group"
        >
          <label
            v-for="opt in localeOptions"
            :key="opt.code"
            class="appearance-theme__opt"
            :class="{ 'is-active': appStore.locale === opt.code }"
          >
            <input
              class="appearance-theme__radio"
              type="radio"
              name="appearance-locale"
              :value="opt.code"
              :checked="appStore.locale === opt.code"
              :data-testid="`settings-language-${opt.code}`"
              @change="pickLocale(opt.code)"
            >
            <span>{{ opt.label }}</span>
          </label>
        </div>
      </div>
    </div>

    <div class="control-row control-row--stack">
      <div class="control-row__label-block">
        <span class="control-row__label">{{ t('settings.appearance.bgmLabel') }}</span>
        <span class="control-row__desc">{{ t('settings.appearance.bgmDesc') }}</span>
      </div>
      <div class="control-row__control">
        <ControlSwitch
          :checked="bgmEnabled"
          :aria-label="t('settings.appearance.bgmLabel')"
          name="appearance-bgm"
          data-testid="settings-bgm-toggle"
          @change="setBgmEnabled"
        />
      </div>
    </div>
  </section>
</template>

<style scoped>
.appearance-theme {
  /* Wraps to multiple rows so many themes / locales never overflow or crush the
     row (the parent row is .control-row--stack, so this fills the width). */
  display: flex;
  flex-wrap: wrap;
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
