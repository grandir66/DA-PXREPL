<template>
  <div class="dt-wrap">
    <div class="dt-toolbar" v-if="searchable || $slots.toolbar">
      <div class="dt-search" v-if="searchable">
        <Icon name="search" :size="14" />
        <input
          v-model="search"
          type="text"
          class="form-input"
          :placeholder="searchPlaceholder"
        />
      </div>
      <slot name="toolbar" />
    </div>

    <div class="dt-scroll">
      <table class="dt">
        <thead>
          <tr>
            <th
              v-for="c in columns"
              :key="c.key"
              :class="{ 'dt-th-num': c.numeric, 'dt-th-sortable': c.sortable }"
              :style="c.width ? { width: c.width } : {}"
              @click="c.sortable && toggleSort(c.key)"
            >
              <div class="dt-th-inner">
                <span>{{ c.label }}</span>
                <span v-if="c.sortable" class="dt-sort">
                  <Icon
                    :name="sortKey === c.key
                      ? (sortDir === 'asc' ? 'chevron-up' : 'chevron-down')
                      : 'chevron-down'"
                    :size="12"
                    :class="{ 'dt-sort-active': sortKey === c.key }"
                  />
                </span>
              </div>
            </th>
            <th v-if="$slots.actions" class="dt-th-actions">Azioni</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td :colspan="totalCols">
              <LoadingState />
            </td>
          </tr>
          <tr v-else-if="!sorted.length">
            <td :colspan="totalCols">
              <slot name="empty">
                <EmptyState :title="emptyTitle" :message="emptyMessage" />
              </slot>
            </td>
          </tr>
          <tr v-else v-for="(row, ri) in paged" :key="rowKey(row, ri)">
            <td
              v-for="c in columns"
              :key="c.key"
              :class="{ 'dt-td-num': c.numeric, 'dt-td-mono': c.mono }"
            >
              <slot :name="`cell-${c.key}`" :row="row" :value="getValue(row, c.key)">
                {{ getValue(row, c.key) ?? '—' }}
              </slot>
            </td>
            <td v-if="$slots.actions" class="dt-td-actions">
              <slot name="actions" :row="row" />
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="paginated && sorted.length > pageSize" class="dt-pager">
      <span class="dt-pager-info">
        {{ pageStart + 1 }}–{{ pageEnd }} di {{ sorted.length }}
      </span>
      <div class="dt-pager-buttons">
        <button class="btn btn-secondary btn-sm" :disabled="page === 0" @click="page = 0">«</button>
        <button class="btn btn-secondary btn-sm" :disabled="page === 0" @click="page--">‹</button>
        <span class="dt-pager-page">pag. {{ page + 1 }} / {{ totalPages }}</span>
        <button class="btn btn-secondary btn-sm" :disabled="page >= totalPages - 1" @click="page++">›</button>
        <button class="btn btn-secondary btn-sm" :disabled="page >= totalPages - 1" @click="page = totalPages - 1">»</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts" generic="T extends Record<string, any>">
import { computed, ref, useSlots, watch } from 'vue'
import Icon from './Icon.vue'
import LoadingState from './LoadingState.vue'
import EmptyState from './EmptyState.vue'

export interface DataTableColumn {
  key: string
  label: string
  sortable?: boolean
  numeric?: boolean
  mono?: boolean
  width?: string
}

const props = withDefaults(
  defineProps<{
    rows: T[]
    columns: DataTableColumn[]
    rowKey?: (row: T, index: number) => string | number
    loading?: boolean
    searchable?: boolean
    searchPlaceholder?: string
    paginated?: boolean
    pageSize?: number
    emptyTitle?: string
    emptyMessage?: string
    /** Funzione opzionale per filtrare un row dato la query di ricerca. */
    searchFn?: (row: T, q: string) => boolean
  }>(),
  {
    loading: false,
    searchable: true,
    searchPlaceholder: 'Filtra…',
    paginated: true,
    pageSize: 25,
    emptyTitle: 'Nessun risultato',
    emptyMessage: '',
  }
)

const search = ref('')
const sortKey = ref<string | null>(null)
const sortDir = ref<'asc' | 'desc'>('asc')
const page = ref(0)

watch([search, sortKey, sortDir], () => {
  page.value = 0
})

function getValue(row: T, key: string): any {
  return key.split('.').reduce<any>((o, k) => (o == null ? o : o[k]), row)
}

function rowKey(row: T, index: number) {
  return props.rowKey ? props.rowKey(row, index) : index
}

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return props.rows
  if (props.searchFn) return props.rows.filter(r => props.searchFn!(r, q))
  return props.rows.filter(r => {
    for (const c of props.columns) {
      const v = getValue(r, c.key)
      if (v != null && String(v).toLowerCase().includes(q)) return true
    }
    return false
  })
})

const sorted = computed(() => {
  if (!sortKey.value) return filtered.value
  const k = sortKey.value
  const dir = sortDir.value === 'asc' ? 1 : -1
  return [...filtered.value].sort((a, b) => {
    const va = getValue(a, k)
    const vb = getValue(b, k)
    if (va == null && vb == null) return 0
    if (va == null) return -dir
    if (vb == null) return dir
    if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir
    return String(va).localeCompare(String(vb), undefined, { numeric: true }) * dir
  })
})

const totalPages = computed(() =>
  Math.max(1, Math.ceil(sorted.value.length / props.pageSize))
)
const pageStart = computed(() => page.value * props.pageSize)
const pageEnd = computed(() =>
  Math.min(sorted.value.length, pageStart.value + props.pageSize)
)
const paged = computed(() =>
  props.paginated ? sorted.value.slice(pageStart.value, pageEnd.value) : sorted.value
)

const _slots = useSlots()
const slotsHasActions = computed(() => !!_slots.actions)
const totalCols = computed(() => props.columns.length + (slotsHasActions.value ? 1 : 0))

function toggleSort(key: string) {
  if (sortKey.value !== key) {
    sortKey.value = key
    sortDir.value = 'asc'
  } else if (sortDir.value === 'asc') {
    sortDir.value = 'desc'
  } else {
    sortKey.value = null
    sortDir.value = 'asc'
  }
}
</script>

<style scoped>
.dt-wrap {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.dt-toolbar {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  flex-wrap: wrap;
}
.dt-search {
  flex: 1;
  position: relative;
  min-width: 220px;
}
.dt-search :deep(svg) {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-secondary);
  pointer-events: none;
}
.dt-search input {
  padding-left: 32px;
}

.dt-scroll {
  overflow-x: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-surface);
}
.dt {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
.dt thead th {
  text-align: left;
  background: var(--color-bg-body);
  color: var(--color-text-secondary);
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 600;
  padding: 10px 12px;
  border-bottom: 1px solid var(--color-border);
  position: sticky;
  top: 0;
  z-index: 1;
  user-select: none;
}
.dt-th-sortable {
  cursor: pointer;
}
.dt-th-sortable:hover {
  color: var(--color-text-primary);
}
.dt-th-num,
.dt-td-num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.dt-td-mono {
  font-family: var(--font-mono);
  font-size: 0.8rem;
}
.dt-th-inner {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.dt-sort :deep(svg) {
  opacity: 0.5;
}
.dt-sort .dt-sort-active {
  opacity: 1;
  color: var(--color-primary);
}
.dt tbody td {
  padding: 9px 12px;
  border-bottom: 1px solid var(--color-border);
  vertical-align: middle;
  color: var(--color-text-primary);
}
.dt tbody tr:last-child td {
  border-bottom: 0;
}
.dt tbody tr:hover {
  background: var(--color-bg-hover);
}
.dt-th-actions,
.dt-td-actions {
  text-align: right;
  width: 1%;
  white-space: nowrap;
}
.dt-pager {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: var(--space-1);
  font-size: 0.8rem;
  color: var(--color-text-secondary);
}
.dt-pager-buttons {
  display: flex;
  gap: 4px;
  align-items: center;
}
.dt-pager-page {
  padding: 0 var(--space-2);
  font-variant-numeric: tabular-nums;
}
</style>
