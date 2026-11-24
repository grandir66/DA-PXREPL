<template>
  <div class="vm-reg">
    <div class="vm-reg-toggle">
      <label class="vm-reg-switch">
        <input
          type="checkbox"
          :checked="modelValue?.register_vm ?? true"
          @change="patch({ register_vm: ($event.target as HTMLInputElement).checked })"
        />
        <span class="vm-reg-switch-label">
          {{ t('registrazione.registra') }}
        </span>
      </label>
      <p class="vm-reg-help">
        <i18n-t keypath="registrazione.aiuto" tag="span"><template #voce><em>{{ t('registrazione.voce') }}</em></template></i18n-t>
      </p>
    </div>

    <fieldset class="vm-reg-grid" :disabled="!(modelValue?.register_vm ?? true)">
      <div class="field">
        <label>{{ t('registrazione.vmid') }}</label>
        <input
          type="number"
          class="form-input"
          :value="modelValue?.dest_vm_id ?? ''"
          @input="patch({ dest_vm_id: parseIntOrNull(($event.target as HTMLInputElement).value) })"
          :placeholder="String(sourceVmid ?? t('registrazione.stessoOrigine'))"
          min="100"
          max="999999999"
        />
        <small>{{ t('registrazione.vmidNota') }}</small>
      </div>

      <div class="field">
        <label>{{ t('registrazione.suffisso') }}</label>
        <input
          type="text"
          class="form-input"
          :value="modelValue?.dest_vm_name_suffix ?? ''"
          @input="patch({ dest_vm_name_suffix: ($event.target as HTMLInputElement).value || null })"
          placeholder="-replica"
          maxlength="50"
        />
        <small><i18n-t keypath="registrazione.suffissoNota" tag="span"><template #da><code>app01</code></template><template #a><code>app01-replica</code></template></i18n-t></small>
      </div>

      <div class="field">
        <label>{{ t('registrazione.nome') }}</label>
        <input
          type="text"
          class="form-input"
          :value="modelValue?.dest_vm_name ?? ''"
          @input="patch({ dest_vm_name: ($event.target as HTMLInputElement).value || null })"
          :placeholder="sourceVmName ? `${sourceVmName}${modelValue?.dest_vm_name_suffix || ''}` : 'auto'"
          maxlength="100"
        />
        <small>{{ t('registrazione.nomeNota') }}</small>
      </div>

      <div class="field field-full" v-if="!hideStorage">
        <label>{{ t('registrazione.storage') }}</label>
        <StoragePicker
          :model-value="modelValue?.dest_storage ?? null"
          :node-id="destNodeId"
          :node-name="destNodeName"
          :type="storageType"
          :allow-free-text="true"
          @update:model-value="(v: string) => patch({ dest_storage: v || null })"
        />
      </div>

      <div class="field field-full">
        <label>{{ t('registrazione.rete') }}</label>
        <BridgeVlanPicker
          :model-value="bridgeVlan"
          :node-id="destNodeId"
          @update:model-value="onBridgeVlan"
        />
      </div>

      <div class="field field-checkbox">
        <label class="checkbox-row">
          <input
            type="checkbox"
            :checked="modelValue?.force_cpu_host ?? true"
            @change="patch({ force_cpu_host: ($event.target as HTMLInputElement).checked })"
          />
          <i18n-t keypath="registrazione.cpu" tag="span"><template #host><code>host</code></template></i18n-t>
        </label>
        <small>{{ t('registrazione.cpuNota') }}</small>
      </div>

      <div class="field field-checkbox" v-if="showStartVm">
        <label class="checkbox-row">
          <input
            type="checkbox"
            :checked="modelValue?.start_vm ?? false"
            @change="patch({ start_vm: ($event.target as HTMLInputElement).checked })"
          />
          <span>{{ t('registrazione.avvia') }}</span>
        </label>
      </div>

      <div class="field field-checkbox" v-if="showOverwrite">
        <label class="checkbox-row">
          <input
            type="checkbox"
            :checked="modelValue?.overwrite_existing ?? true"
            @change="patch({ overwrite_existing: ($event.target as HTMLInputElement).checked })"
          />
          <span>{{ t('registrazione.sovrascrivi') }}</span>
        </label>
      </div>
    </fieldset>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import StoragePicker from './StoragePicker.vue'
import BridgeVlanPicker, { type BridgeVlanValue } from './BridgeVlanPicker.vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

export interface VMRegistration {
  register_vm: boolean
  dest_vm_id: number | null
  dest_vm_name?: string | null
  dest_vm_name_suffix: string | null
  dest_storage: string | null
  bridge: string | null
  vlan: number | null
  force_cpu_host: boolean
  start_vm?: boolean
  overwrite_existing?: boolean
}

const props = withDefaults(
  defineProps<{
    modelValue: VMRegistration | null | undefined
    destNodeId: number | string | null | undefined
    destNodeName?: string
    sourceVmid?: number | string | null
    sourceVmName?: string | null
    storageType?: 'zfs' | 'pbs' | 'dir' | 'lvm' | 'any'
    showStartVm?: boolean
    showOverwrite?: boolean
    /** Nasconde il selettore "Storage destinazione" — usato quando lo
     *  storage e' gia' definito a un livello superiore (es. dest_pool
     *  in un job Syncoid). */
    hideStorage?: boolean
  }>(),
  {
    storageType: 'any',
    showStartVm: false,
    showOverwrite: false,
    hideStorage: false,
  }
)

const emit = defineEmits<{
  (e: 'update:modelValue', v: VMRegistration): void
}>()

const bridgeVlan = computed<BridgeVlanValue>(() => ({
  bridge: props.modelValue?.bridge || null,
  vlan: props.modelValue?.vlan ?? null,
}))

function patch(part: Partial<VMRegistration>) {
  const next: VMRegistration = {
    register_vm: props.modelValue?.register_vm ?? true,
    dest_vm_id: props.modelValue?.dest_vm_id ?? null,
    dest_vm_name: props.modelValue?.dest_vm_name ?? null,
    dest_vm_name_suffix: props.modelValue?.dest_vm_name_suffix ?? null,
    dest_storage: props.modelValue?.dest_storage ?? null,
    bridge: props.modelValue?.bridge ?? null,
    vlan: props.modelValue?.vlan ?? null,
    force_cpu_host: props.modelValue?.force_cpu_host ?? true,
    start_vm: props.modelValue?.start_vm ?? false,
    overwrite_existing: props.modelValue?.overwrite_existing ?? true,
    ...part,
  }
  emit('update:modelValue', next)
}

function onBridgeVlan(v: BridgeVlanValue) {
  patch({ bridge: v.bridge, vlan: v.vlan })
}

function parseIntOrNull(s: string): number | null {
  if (s === '' || s == null) return null
  const n = parseInt(s, 10)
  return Number.isNaN(n) ? null : n
}
</script>

<style scoped>
.vm-reg {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.vm-reg-toggle {
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3);
}
.vm-reg-switch {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
}
.vm-reg-switch-label {
  font-weight: 600;
  color: var(--color-text-primary);
}
.vm-reg-help {
  margin: var(--space-1) 0 0;
  font-size: 0.78rem;
  color: var(--color-text-secondary);
}
.vm-reg-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
  border: 0;
  padding: 0;
  margin: 0;
}
.vm-reg-grid:disabled {
  opacity: 0.55;
  pointer-events: none;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.field-full {
  grid-column: 1 / -1;
}
.field-checkbox {
  grid-column: 1 / -1;
}
.field label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--color-text-secondary);
}
.field small {
  font-size: 0.72rem;
  color: var(--color-text-secondary);
}
.checkbox-row {
  display: inline-flex !important;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
  font-weight: 500 !important;
  color: var(--color-text-primary) !important;
}
code {
  font-family: var(--font-mono);
  background: var(--color-bg-element);
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 0.78em;
}

@media (max-width: 720px) {
  .vm-reg-grid {
    grid-template-columns: 1fr;
  }
}
</style>
