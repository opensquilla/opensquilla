<template>
  <details class="rag-provider-details control-panel">
    <summary>{{ t('rag.details.title') }}</summary>
    <div class="rag-provider-details__groups">
      <section>
        <h3>{{ t('rag.details.connection') }}</h3>
        <dl>
          <div><dt>provider.name</dt><dd>{{ value(props.status?.provider?.name) }}</dd></div>
          <div><dt>version</dt><dd>{{ value(props.status?.provider?.version) }}</dd></div>
          <div><dt>instanceId</dt><dd>{{ value(props.status?.provider?.instanceId) }}</dd></div>
          <div><dt>connectionState</dt><dd>{{ value(props.status?.connectionState) }}</dd></div>
          <div><dt>lastSuccessAt</dt><dd>{{ value(props.status?.lastSuccessAt) }}</dd></div>
          <div><dt>lastErrorCode</dt><dd>{{ value(props.status?.lastErrorCode) }}</dd></div>
        </dl>
      </section>

      <section>
        <h3>{{ t('rag.details.protocol') }}</h3>
        <dl>
          <div><dt>protocolVersion</dt><dd>{{ value(props.status?.protocolVersion) }}</dd></div>
          <div><dt>capabilities.search</dt><dd>{{ value(props.status?.capabilities?.search) }}</dd></div>
          <div><dt>capabilities.get</dt><dd>{{ value(props.status?.capabilities?.get) }}</dd></div>
          <div><dt>collectionScope</dt><dd>{{ collectionScope }}</dd></div>
        </dl>
      </section>

      <section>
        <h3>{{ t('rag.details.budgets') }}</h3>
        <dl>
          <div><dt>maxSearchResults</dt><dd>{{ value(props.status?.effectiveLimits?.maxSearchResults) }}</dd></div>
          <div><dt>maxSnippetChars</dt><dd>{{ value(props.status?.effectiveLimits?.maxSnippetChars) }}</dd></div>
          <div><dt>maxSearchResponseChars</dt><dd>{{ value(props.status?.effectiveLimits?.maxSearchResponseChars) }}</dd></div>
          <div><dt>maxGetContentChars</dt><dd>{{ value(props.status?.effectiveLimits?.maxGetContentChars) }}</dd></div>
        </dl>
      </section>
    </div>
  </details>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RagProviderStatus } from '@/views/ragProvider'

const props = defineProps<{ status: RagProviderStatus | null }>()
const { t } = useI18n()

const collectionScope = computed(() => {
  if (!props.status?.collectionScope.length) return '—'
  return props.status.collectionScope.join(', ')
})

function value(item: string | number | boolean | null | undefined): string {
  return item === null || item === undefined || item === '' ? '—' : String(item)
}
</script>

<style scoped>
.rag-provider-details summary {
  color: var(--text);
  cursor: pointer;
  font-weight: 600;
}

.rag-provider-details__groups {
  display: grid;
  gap: var(--sp-4);
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: var(--sp-4);
}

.rag-provider-details h3 {
  font-size: var(--fs-md);
  margin: 0 0 var(--sp-3);
}

.rag-provider-details dl {
  display: grid;
  gap: var(--sp-2);
  margin: 0;
}

.rag-provider-details dl div {
  border-top: 1px solid var(--border);
  display: grid;
  gap: var(--sp-1);
  padding-top: var(--sp-2);
}

.rag-provider-details dt {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  overflow-wrap: anywhere;
}

.rag-provider-details dd {
  margin: 0;
  overflow-wrap: anywhere;
}

@media (max-width: 900px) {
  .rag-provider-details__groups {
    grid-template-columns: 1fr;
  }
}
</style>
