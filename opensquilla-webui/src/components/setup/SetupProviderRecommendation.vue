<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const registrationUrl = 'https://tokenrhythm.studio/register'
</script>

<template>
  <div
    class="setup-provider-recommendation control-card control-card--compact control-card--accent"
    data-testid="tokenrhythm-recommendation"
  >
    <p
      class="setup-provider-recommendation__title"
      data-testid="tokenrhythm-recommendation-title"
    >{{ t('setup.provider.recommendation.title') }}</p>
    <p
      class="setup-provider-recommendation__copy"
      data-testid="tokenrhythm-recommendation-value"
    >{{ t('setup.provider.recommendation.value') }}</p>
    <p
      class="setup-provider-recommendation__copy"
      data-testid="tokenrhythm-recommendation-registration"
    >{{ t('setup.provider.recommendation.registration') }}</p>
    <a
      class="setup-provider-recommendation__link"
      :href="registrationUrl"
      target="_blank"
      rel="noopener noreferrer"
      :aria-label="t('setup.provider.recommendation.externalLabel')"
    >{{ t('setup.provider.recommendation.cta') }}</a>
  </div>
</template>

<style scoped>
.setup-provider-recommendation {
  margin: 0;
}

.setup-provider-recommendation__title,
.setup-provider-recommendation__copy {
  margin: 0;
}

.setup-provider-recommendation__title {
  font-size: var(--fs-sm);
  font-weight: 700;
}

.setup-provider-recommendation__copy {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: 1.5;
}

.setup-provider-recommendation__link {
  align-self: flex-start;
  color: var(--accent);
  font-size: var(--fs-sm);
  font-weight: 600;
  text-decoration: none;
}

.setup-provider-recommendation__link:hover {
  text-decoration: underline;
}

.setup-provider-recommendation__link:focus-visible {
  border-radius: var(--radius-sm);
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
</style>
