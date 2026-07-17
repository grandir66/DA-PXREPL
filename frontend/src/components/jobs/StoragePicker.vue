<template>
  <div class="storage-picker">
    <div class="sp-head">
      <label v-if="label" class="sp-label">{{ label }}</label>
      <button
        type="button"
        class="btn btn-secondary btn-sm"
        :disabled="loading || !nodeId"
        @click="reload"
        :title="'Ricarica storage da ' + (nodeName || 'nodo')"
      >
        <span v-if="loading">Aggiorno…</span>
        <span v-else>Aggiorna</span>
      </button>
    </div>

    <div v-if="!nodeId" class="sp-empty">Seleziona prima un nodo.</div>

    <div v-else-if="loading" class="sp-empty">Caricamento storage…</div>

    <div v-else-if="error" class="sp-error">{{ error }}</div>

    <div v-else-if="filtered.length === 0 && !loading" class="sp-empty">
      Nessuno storage{{ type !== 'any' ? ` di tipo ${type}` : '' }} disponibile.
    </div>

    <ul v-else class="sp-list">
      <li
        v-for="s in filtered"
        :key="s.storage"
        class="sp-item"
        :class="{ active: modelValue === s.storage, disabled: s.status && s.status !== 'active' }"
        @click="emit('update:modelValue', s.storage)"
      >
        <div class="sp-item-main">
          <span class="sp-item-name">{{ s.storage }}</span>
          <span class="sp-item-type" :class="`type-${(s.type || 'unknown').toLowerCase()}`">{{ s.type || '—' }}</span>
        </div>
        <div class="sp-item-meta">
          <span v-if="s.avail">disp. {{ humanBytes(s.avail) }}</span>
          <span v-if="s.used && s.total">
            {{ humanBytes(s.used) }} / {{ humanBytes(s.total) }}
          </span>
          <span v-if="s.status && s.status !== 'active'" class="sp-item-warn">
            {{ s.status }}
          </span>
        </div>
      </li>
    </ul>

    <div v-if="allowFreeText" class="sp-free">
      <label class="sp-label-sm">o digita manualmente</label>
      <input
        type="text"
        class="form-input"
        :value="modelValue || ''"
        @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
        placeholder="nome-storage"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import nodesService from '../../services/nodes'

interface StorageEntry {
  storage: string
  type: string
  status?: string
  avail?: string | number
  used?: string | number
  total?: string | number
}

const props = withDefaults(
  defineProps<{
    modelValue: string | null | undefined
    nodeId: number | string | null | undefined
    nodeName?: string
    label?: string
    type?: 'zfs' | 'pbs' | 'dir' | 'lvm' | 'any'
    allowFreeText?: boolean
  }>(),
  {
    type: 'any',
    allowFreeText: true,
  }
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

const loading = ref(false)
const error = ref<string | null>(null)
const storages = ref<StorageEntry[]>([])

const filtered = computed(() => {
  if (props.type === 'any') return storages.value
  // PVE espone storage ZFS come `zfspool` (pvesm) o come pool raw `zfs`.
  // Trattiamoli come equivalenti quando filtriamo per type='zfs'.
  const wantZfs = props.type === 'zfs'
  return storages.value.filter(s => {
    const t = (s.type || '').toLowerCase()
    if (wantZfs) return t === 'zfs' || t === 'zfspool'
    return t === props.type
  })
})

async function reload() {
  if (!props.nodeId) return
  loading.value = true
  error.value = null
  try {
    const r = await nodesService.getStorages(props.nodeId)
    storages.value = (r.data?.storages || []) as StorageEntry[]
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || String(e)
  } finally {
    loading.value = false
  }
}

watch(() => props.nodeId, () => reload(), { immediate: true })

function humanBytes(v: any): string {
  if (v == null) return '—'
  const n = typeof v === 'string' ? parseInt(v, 10) : Number(v)
  if (!Number.isFinite(n)) return String(v)
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB']
  let i = 0
  let x = n
  while (x >= 1024 && i < units.length - 1) {
    x /= 1024
    i++
  }
  return `${x.toFixed(x < 10 && i > 0 ? 1 : 0)} ${units[i]}`
}
</script>

<style scoped>
.storage-picker {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.sp-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}
.sp-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--color-text-secondary);
}
.sp-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0;
  max-height: 280px;
  overflow-y: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-surface);
}
.sp-item {
  padding: var(--space-2) var(--space-3);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  cursor: pointer;
  border-bottom: 1px solid var(--color-border);
  transition: background 0.12s;
}
.sp-item:last-child {
  border-bottom: none;
}
.sp-item:hover {
  background: var(--color-bg-hover);
}
.sp-item.active {
  background: var(--color-primary-dim);
  border-left: 2px solid var(--color-primary);
}
.sp-item.disabled {
  opacity: 0.55;
}
.sp-item-main {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.sp-item-name {
  font-weight: 600;
  font-family: var(--font-mono);
  font-size: 0.85rem;
  color: var(--color-text-primary);
}
.sp-item-type {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-border);
  color: var(--color-text-secondary);
}
.sp-item-type.type-zfs,
.sp-item-type.type-zfspool {
  border-color: var(--color-zfs);
  color: var(--color-zfs);
}
.sp-item-type.type-pbs {
  border-color: var(--color-pbs);
  color: var(--color-pbs);
}
.sp-item-meta {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: 0.75rem;
  color: var(--color-text-secondary);
  font-family: var(--font-mono);
}
.sp-item-warn {
  color: var(--color-warning-fg);
}
.sp-empty {
  padding: var(--space-3);
  text-align: center;
  font-size: 0.8rem;
  color: var(--color-text-secondary);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-md);
}
.sp-error {
  padding: var(--space-2) var(--space-3);
  background: var(--color-danger-dim);
  color: var(--color-danger-fg);
  border-radius: var(--radius-md);
  font-size: 0.8rem;
}
.sp-free {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding-top: var(--space-2);
  border-top: 1px dashed var(--color-border);
}
.sp-label-sm {
  font-size: 0.7rem;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
</style>
