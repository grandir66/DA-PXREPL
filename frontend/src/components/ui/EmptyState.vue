<template>
  <div class="empty">
    <div class="empty-icon" v-if="icon">
      <Icon :name="icon" :size="iconSize" />
    </div>
    <h3 class="empty-title">{{ title }}</h3>
    <p class="empty-message" v-if="message">{{ message }}</p>
    <div class="empty-actions" v-if="$slots.actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup lang="ts">
import Icon from './Icon.vue'

withDefaults(
  defineProps<{
    title: string
    message?: string
    icon?: string
    iconSize?: number
  }>(),
  {
    icon: 'box',
    iconSize: 28,
  }
)
</script>

<style scoped>
.empty {
  padding: var(--space-6) var(--space-4);
  text-align: center;
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-surface);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
}
.empty-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: var(--color-bg-element);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-1);
}
.empty-title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--color-text-primary);
}
.empty-message {
  margin: 0;
  font-size: 0.84rem;
  color: var(--color-text-secondary);
  max-width: 420px;
}
.empty-actions {
  margin-top: var(--space-2);
  display: flex;
  gap: var(--space-2);
}
</style>
