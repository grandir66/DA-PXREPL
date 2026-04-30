<template>
  <div class="loading" :class="{ 'loading-inline': inline }">
    <div class="spinner" :style="{ width: size + 'px', height: size + 'px' }" />
    <span v-if="message" class="loading-msg">{{ message }}</span>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    message?: string
    size?: number
    inline?: boolean
  }>(),
  {
    message: 'Caricamento…',
    size: 22,
    inline: false,
  }
)
</script>

<style scoped>
.loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-5);
  color: var(--color-text-secondary);
}
.loading-inline {
  flex-direction: row;
  padding: var(--space-2);
}
.spinner {
  border: 2px solid var(--color-border);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
.loading-msg {
  font-size: 0.84rem;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
