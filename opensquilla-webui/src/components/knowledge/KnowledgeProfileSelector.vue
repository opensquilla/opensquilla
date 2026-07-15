<template>
  <section class="rag-profile-selector control-panel">
    <h2 class="control-panel__title">{{ t('rag.profile.title') }}</h2>

    <div class="rag-profile-grid" role="radiogroup" :aria-label="t('rag.profile.title')">
      <button
        type="button"
        role="radio"
        data-profile-id="provider-default"
        class="rag-profile-card"
        :class="{ 'is-selected': checked(null) }"
        :aria-checked="checked(null)"
        :disabled="disabled || saving"
        @click="emit('change', null)"
      >
        <strong>{{ t('rag.profile.followProvider') }}</strong>
        <span>{{ providerDefault || t('rag.profile.notDeclared') }}</span>
      </button>

      <button
        v-for="profile in profiles"
        :key="profile.id"
        type="button"
        role="radio"
        class="rag-profile-card"
        :class="{ 'is-selected': checked(profile.id) }"
        :data-profile-id="profile.id"
        :aria-checked="checked(profile.id)"
        :disabled="disabled || saving"
        @click="emit('change', profile.id)"
      >
        <strong>{{ profile.label }}</strong>
        <code>{{ profile.id }}</code>
        <span v-if="profile.id === providerDefault" class="control-pill">
          {{ t('rag.profile.providerDefaultBadge') }}
        </span>
        <span v-if="profile.id === effective" class="control-pill control-pill--ok">
          {{ t('rag.profile.activeBadge') }}
        </span>
      </button>
    </div>

    <div class="rag-profile-selector__footer">
      <div class="rag-profile-selector__status">
        <p
          v-if="savedUnavailable"
          data-testid="rag-profile-unavailable"
          class="rag-profile-selector__alert"
          role="alert"
        >
          {{ t('rag.profile.unavailable') }}
        </p>
        <p v-if="error" class="rag-profile-selector__alert" role="alert">{{ error }}</p>
        <span v-if="dirty" aria-live="polite">{{ t('rag.profile.unsaved') }}</span>
      </div>
      <button
        data-testid="rag-profile-save"
        class="btn btn--primary"
        type="button"
        :disabled="disabled || saving || !dirty"
        @click="emit('save')"
      >
        {{ saving ? t('rag.profile.saving') : t('rag.profile.save') }}
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  profiles: Array<{ id: string; label: string }>
  providerDefault: string | null
  savedOverride: string | null
  draft: string | null
  saving: boolean
  disabled: boolean
  error: string
}>()

const emit = defineEmits<{
  change: [profile: string | null]
  save: []
}>()

const { t } = useI18n()
const dirty = computed(() => props.draft !== props.savedOverride)
const availableIds = computed(() => new Set(props.profiles.map(item => item.id)))
const savedUnavailable = computed(
  () => props.savedOverride !== null && !availableIds.value.has(props.savedOverride),
)
const effective = computed(() => props.savedOverride || props.providerDefault)

function checked(profile: string | null): boolean {
  return props.draft === profile
}
</script>

<style scoped>
.rag-profile-selector {
  display: grid;
  gap: var(--sp-4);
}

.rag-profile-grid {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
}

.rag-profile-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  color: var(--text);
  display: grid;
  gap: 6px;
  min-width: 0;
  padding: var(--sp-3);
  text-align: left;
}

.rag-profile-card.is-selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}

.rag-profile-card code {
  color: var(--text-muted);
  overflow-wrap: anywhere;
}

.rag-profile-selector__footer {
  align-items: center;
  display: flex;
  gap: var(--sp-3);
  justify-content: space-between;
}

.rag-profile-selector__status {
  display: grid;
  gap: var(--sp-2);
}

.rag-profile-selector__alert,
.rag-profile-selector__status p {
  margin: 0;
}

.rag-profile-selector__alert {
  color: var(--warn);
}
</style>
