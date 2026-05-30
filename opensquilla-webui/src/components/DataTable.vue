<template>
  <div class="data-table-wrapper">
    <table class="data-table">
      <thead>
        <tr>
          <th
            v-for="col in columns"
            :key="col.key"
            :class="{ sortable: col.sortable, active: sortKey === col.key }"
            @click="col.sortable ? toggleSort(col.key) : undefined"
          >
            <span class="th-label">{{ col.label }}</span>
            <span v-if="col.sortable" class="sort-indicator" aria-hidden="true">
              {{ sortKey === col.key ? (sortDir === 'asc' ? '▲' : '▼') : '⇅' }}
            </span>
          </th>
        </tr>
      </thead>
      <tbody>
        <template v-if="loading">
          <tr v-for="n in skeletonRows" :key="n" class="skeleton-row">
            <td v-for="col in columns" :key="col.key">
              <span class="skeleton-cell"></span>
            </td>
          </tr>
        </template>
        <template v-else-if="sortedRows.length === 0">
          <tr class="empty-row">
            <td :colspan="columns.length" class="empty-cell">
              {{ emptyText }}
            </td>
          </tr>
        </template>
        <template v-else>
          <tr v-for="(row, idx) in sortedRows" :key="idx">
            <td v-for="col in columns" :key="col.key">
              <slot :name="col.key" :row="row" :value="row[col.key]">
                {{ row[col.key] }}
              </slot>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

interface Column {
  key: string
  label: string
  sortable?: boolean
}

const props = withDefaults(
  defineProps<{
    columns: Column[]
    rows: Array<Record<string, any>>
    loading?: boolean
    emptyText?: string
  }>(),
  {
    loading: false,
    emptyText: 'No data',
  }
)

const sortKey = ref<string | null>(null)
const sortDir = ref<'asc' | 'desc'>('asc')
const skeletonRows = 5

function toggleSort(key: string) {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = key
    sortDir.value = 'asc'
  }
}

const sortedRows = computed(() => {
  if (!sortKey.value) return props.rows
  const key = sortKey.value
  const dir = sortDir.value
  return [...props.rows].sort((a, b) => {
    const av = a[key]
    const bv = b[key]
    if (av == null && bv == null) return 0
    if (av == null) return dir === 'asc' ? -1 : 1
    if (bv == null) return dir === 'asc' ? 1 : -1
    if (typeof av === 'number' && typeof bv === 'number') {
      return dir === 'asc' ? av - bv : bv - av
    }
    const as = String(av).toLowerCase()
    const bs = String(bv).toLowerCase()
    if (as < bs) return dir === 'asc' ? -1 : 1
    if (as > bs) return dir === 'asc' ? 1 : -1
    return 0
  })
})
</script>

<style scoped>
.data-table-wrapper {
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-surface);
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--fs-sm);
  color: var(--text);
}

.data-table thead th {
  text-align: left;
  padding: var(--sp-3) var(--sp-4);
  font-weight: 600;
  color: var(--text-muted);
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border-strong);
  white-space: nowrap;
  user-select: none;
}

.data-table thead th.sortable {
  cursor: pointer;
  transition: color var(--transition), background var(--transition);
}

.data-table thead th.sortable:hover {
  color: var(--text);
  background: var(--bg-hover);
}

.data-table thead th.active {
  color: var(--accent);
}

.th-label {
  vertical-align: middle;
}

.sort-indicator {
  margin-left: var(--sp-2);
  font-size: 0.7em;
  opacity: 0.6;
  vertical-align: middle;
}

.data-table thead th.active .sort-indicator {
  opacity: 1;
}

.data-table tbody td {
  padding: var(--sp-3) var(--sp-4);
  border-bottom: 1px solid var(--hairline);
  vertical-align: middle;
}

.data-table tbody tr:last-child td {
  border-bottom: none;
}

.data-table tbody tr:hover td {
  background: var(--bg-hover);
}

.empty-cell {
  text-align: center;
  color: var(--text-dim);
  padding: var(--sp-8) var(--sp-4);
}

.skeleton-row td {
  padding: var(--sp-3) var(--sp-4);
}

.skeleton-cell {
  display: block;
  height: 1em;
  width: 70%;
  border-radius: var(--radius-sm);
  background: linear-gradient(
    90deg,
    var(--bg-hover) 25%,
    var(--bg-elevated) 50%,
    var(--bg-hover) 75%
  );
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.4s ease-in-out infinite;
}

@keyframes skeleton-shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .skeleton-cell {
    animation: none;
    background: var(--bg-hover);
  }
}
</style>
