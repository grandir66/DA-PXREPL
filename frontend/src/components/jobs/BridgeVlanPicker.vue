<template>
  <div class="bv-picker">
    <div class="bv-row">
      <label class="bv-label">Bridge</label>
      <select
        class="form-input bv-select"
        :value="modelValue?.bridge || ''"
        @change="onBridgeChange(($event.target as HTMLSelectElement).value)"
        :disabled="loading || !nodeId"
      >
        <option value="">— seleziona —</option>
        <option v-for="b in bridges" :key="b.name" :value="b.name">
          {{ b.name }}{{ b.vlan_aware ? ' · vlan-aware' : '' }}
        </option>
      </select>
      <button
        type="button"
        class="btn btn-secondary btn-sm bv-refresh"
        @click="reload"
        :disabled="loading || !nodeId"
        title="Aggiorna lista bridge"
      >
        ↻
      </button>
    </div>

    <div class="bv-row">
      <label class="bv-label">VLAN tag</label>
      <input
        type="number"
        min="1"
        max="4094"
        class="form-input bv-vlan"
        :value="modelValue?.vlan ?? ''"
        @input="onVlanChange(($event.target as HTMLInputElement).value)"
        :disabled="!isVlanAware"
        :placeholder="isVlanAware ? 'opzionale' : 'bridge non vlan-aware'"
      />
      <div class="bv-vlan-hint" v-if="observedVlans.length">
        <span class="bv-hint">Già usate:</span>
        <button
          v-for="v in observedVlans"
          :key="v"
          type="button"
          class="bv-vlan-chip"
          @click="onVlanChange(String(v))"
        >
          {{ v }}
        </button>
      </div>
    </div>

    <div v-if="error" class="bv-error">{{ error }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import apiClient from '../../services/api'

interface BridgeInfo {
  name: string
  vlan_aware: boolean
  observed_vlans: number[]
}

export interface BridgeVlanValue {
  bridge: string | null
  vlan: number | null
}

const props = defineProps<{
  modelValue: BridgeVlanValue | null | undefined
  nodeId: number | string | null | undefined
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: BridgeVlanValue): void
}>()

const loading = ref(false)
const error = ref<string | null>(null)
const bridges = ref<BridgeInfo[]>([])

const selectedBridge = computed(() =>
  bridges.value.find(b => b.name === props.modelValue?.bridge) || null
)
const isVlanAware = computed(() => selectedBridge.value?.vlan_aware ?? false)
const observedVlans = computed(() => selectedBridge.value?.observed_vlans || [])

async function reload() {
  if (!props.nodeId) return
  loading.value = true
  error.value = null
  try {
    const r = await apiClient.get<{ bridges: BridgeInfo[]; vlan_aware_default: string | null }>(
      `/nodes/${props.nodeId}/network-config`
    )
    bridges.value = r.data?.bridges || []
    // Se non c'è ancora un bridge selezionato, suggerisci il default
    // vlan-aware (o il primo disponibile).
    if (!props.modelValue?.bridge) {
      const def = r.data?.vlan_aware_default || bridges.value[0]?.name || null
      if (def) emit('update:modelValue', { bridge: def, vlan: props.modelValue?.vlan ?? null })
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || String(e)
  } finally {
    loading.value = false
  }
}

watch(() => props.nodeId, () => reload(), { immediate: true })

function onBridgeChange(name: string) {
  const next = bridges.value.find(b => b.name === name)
  emit('update:modelValue', {
    bridge: name || null,
    vlan: next?.vlan_aware ? props.modelValue?.vlan ?? null : null,
  })
}

function onVlanChange(v: string) {
  if (v === '' || v == null) {
    emit('update:modelValue', { bridge: props.modelValue?.bridge || null, vlan: null })
    return
  }
  const n = parseInt(v, 10)
  if (Number.isNaN(n)) return
  const clamped = Math.min(4094, Math.max(1, n))
  emit('update:modelValue', { bridge: props.modelValue?.bridge || null, vlan: clamped })
}
</script>

<style scoped>
.bv-picker {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.bv-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.bv-label {
  min-width: 100px;
  font-size: 0.8rem;
  color: var(--color-text-secondary);
}
.bv-select {
  flex: 1 1 200px;
  min-width: 200px;
}
.bv-vlan {
  max-width: 120px;
}
.bv-refresh {
  padding: 4px 10px;
}
.bv-vlan-hint {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  flex-wrap: wrap;
}
.bv-hint {
  font-size: 0.7rem;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.bv-vlan-chip {
  padding: 2px 8px;
  background: var(--color-bg-element);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  color: var(--color-text-secondary);
  font-size: 0.75rem;
  cursor: pointer;
  font-family: var(--font-mono);
}
.bv-vlan-chip:hover {
  background: var(--color-primary-dim);
  color: var(--color-primary);
  border-color: var(--color-primary);
}
.bv-error {
  padding: var(--space-2);
  background: var(--color-danger-dim);
  color: var(--color-danger-fg);
  border-radius: var(--radius-sm);
  font-size: 0.78rem;
}
</style>
