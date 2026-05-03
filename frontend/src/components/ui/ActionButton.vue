<template>
  <button
    type="button"
    class="action-btn"
    :class="[`action-${kind}`, { 'action-only-icon': iconOnly }]"
    :disabled="disabled"
    :title="title || label"
    @click="$emit('click', $event)"
  >
    <Icon :name="iconName" :size="iconSize" />
    <span v-if="!iconOnly" class="action-label">{{ label }}</span>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Icon from './Icon.vue'

export type ActionKind =
  | 'run'         // ▶ esegui
  | 'pause'       // ⏸
  | 'stop'        // ⏹
  | 'edit'        // ✎ modifica
  | 'delete'      // 🗑 elimina (rosso)
  | 'view'        // 👁 dettagli
  | 'logs'        // log output
  | 'info'        // dettagli generici
  | 'refresh'     // aggiorna
  | 'download'    // scarica
  | 'upload'      // carica
  | 'add'         // +
  | 'copy'        // clona
  | 'restore'     // ↺
  | 'test'        // verifica connessione
  | 'lock'
  | 'unlock'
  | 'custom'      // usa props.icon

const props = withDefaults(
  defineProps<{
    kind: ActionKind
    label?: string
    icon?: string             // override per kind=custom
    iconOnly?: boolean        // mostra solo icona (con title)
    iconSize?: number
    disabled?: boolean
    title?: string
  }>(),
  {
    iconOnly: false,
    iconSize: 14,
    disabled: false,
  }
)

defineEmits<{ (e: 'click', ev: MouseEvent): void }>()

const ICONS: Record<ActionKind, string> = {
  run: 'play',
  pause: 'pause',
  stop: 'stop',
  edit: 'pencil',
  delete: 'trash',
  view: 'eye',
  logs: 'file-text',
  info: 'info',
  refresh: 'refresh',
  download: 'download',
  upload: 'upload',
  add: 'plus',
  copy: 'copy',
  restore: 'rotate-ccw',
  test: 'activity',
  lock: 'lock',
  unlock: 'unlock',
  custom: '',
}

const LABELS_IT: Record<ActionKind, string> = {
  run: 'Esegui',
  pause: 'Pausa',
  stop: 'Stop',
  edit: 'Modifica',
  delete: 'Elimina',
  view: 'Vedi',
  logs: 'Log',
  info: 'Info',
  refresh: 'Aggiorna',
  download: 'Scarica',
  upload: 'Carica',
  add: 'Aggiungi',
  copy: 'Clona',
  restore: 'Ripristina',
  test: 'Test',
  lock: 'Blocca',
  unlock: 'Sblocca',
  custom: '',
}

const iconName = computed(() => props.icon || ICONS[props.kind] || 'info')
const label = computed(() => props.label ?? LABELS_IT[props.kind] ?? '')
</script>

<style scoped>
.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  font-size: 0.78rem;
  font-weight: 500;
  background: var(--color-bg-element);
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.12s, color 0.12s, border-color 0.12s;
}
.action-btn:hover:not(:disabled) {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
  border-color: var(--color-border-hover);
}
.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.action-btn :deep(svg) {
  flex-shrink: 0;
}
.action-only-icon {
  padding: 5px 7px;
}
.action-only-icon .action-label {
  display: none;
}

/* Toni semantici */
.action-run:hover:not(:disabled) {
  border-color: var(--color-success-fg);
  color: var(--color-success-fg);
}
.action-delete {
  color: var(--color-text-secondary);
}
.action-delete:hover:not(:disabled) {
  background: var(--color-danger-dim);
  color: var(--color-danger-fg);
  border-color: var(--color-danger-fg);
}
.action-edit:hover:not(:disabled),
.action-view:hover:not(:disabled),
.action-info:hover:not(:disabled),
.action-logs:hover:not(:disabled) {
  border-color: var(--color-primary);
  color: var(--color-primary);
}
.action-test:hover:not(:disabled) {
  border-color: var(--color-info-fg);
  color: var(--color-info-fg);
}
</style>
