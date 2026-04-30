<template>
  <div class="error-state">
    <Icon name="alert-triangle" :size="22" class="error-icon" />
    <div class="error-body">
      <strong>{{ title }}</strong>
      <span v-if="message">{{ message }}</span>
    </div>
    <button v-if="$slots.actions || retry" class="btn btn-secondary btn-sm" @click="$emit('retry')">
      <slot name="actions">Riprova</slot>
    </button>
  </div>
</template>

<script setup lang="ts">
import Icon from './Icon.vue'

withDefaults(
  defineProps<{
    title?: string
    message?: string
    retry?: boolean
  }>(),
  {
    title: 'Errore',
    retry: false,
  }
)

defineEmits<{ (e: 'retry'): void }>()
</script>

<style scoped>
.error-state {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border: 1px solid rgba(248, 81, 73, 0.3);
  border-left-width: 3px;
  background: var(--color-danger-dim);
  color: var(--color-danger-fg);
  border-radius: var(--radius-md);
  font-size: 0.86rem;
}
.error-icon {
  flex-shrink: 0;
}
.error-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
}
.error-body strong {
  color: var(--color-text-primary);
  font-size: 0.9rem;
}
.error-body span {
  color: var(--color-text-secondary);
  font-size: 0.8rem;
}
</style>
