<template>
  <header class="page-header">
    <div class="page-header-text">
      <div class="page-title-row">
        <Icon v-if="icon" :name="icon" :size="20" class="page-icon" />
        <h1 class="page-title">{{ title }}</h1>
        <slot name="badge" />
      </div>
      <p v-if="subtitle" class="page-subtitle">{{ subtitle }}</p>
    </div>
    <div class="page-actions" v-if="$slots.actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<script setup lang="ts">
import Icon from './Icon.vue'

defineProps<{
  title: string
  subtitle?: string
  icon?: string
}>()
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-5);
}
.page-header-text {
  flex: 1;
  min-width: 0;
}
.page-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.page-icon {
  color: var(--color-primary);
}
.page-title {
  margin: 0;
  font-size: 1.4rem;
  font-weight: 600;
  color: var(--color-text-primary);
  letter-spacing: -0.01em;
}
.page-subtitle {
  margin: 4px 0 0;
  color: var(--color-text-secondary);
  font-size: 0.86rem;
}
.page-actions {
  display: flex;
  gap: var(--space-2);
  flex-shrink: 0;
  flex-wrap: wrap;
}
</style>
