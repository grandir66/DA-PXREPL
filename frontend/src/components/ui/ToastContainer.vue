<template>
  <Teleport to="body">
    <div class="toast-stack" role="region" aria-live="polite" aria-label="Notifiche">
      <transition-group name="toast">
        <div
          v-for="t in store.toasts"
          :key="t.id"
          class="toast"
          :class="`toast-${t.kind}`"
          @click="store.dismiss(t.id)"
        >
          <Icon :name="iconFor(t.kind)" class="toast-icon" />
          <div class="toast-body">
            <div class="toast-title">{{ t.title }}</div>
            <div class="toast-message" v-if="t.message">{{ t.message }}</div>
          </div>
          <button class="toast-close" @click.stop="store.dismiss(t.id)" aria-label="Chiudi">×</button>
        </div>
      </transition-group>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useToastStore, type ToastKind } from '../../stores/toast'
import Icon from './Icon.vue'

const store = useToastStore()

function iconFor(k: ToastKind): string {
  return {
    success: 'check-circle',
    error: 'x-circle',
    warning: 'alert-triangle',
    info: 'info',
  }[k]
}
</script>

<style scoped>
.toast-stack {
  position: fixed;
  top: var(--space-4);
  right: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  z-index: 5000;
  max-width: 420px;
  pointer-events: none;
}
.toast {
  pointer-events: auto;
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-left-width: 3px;
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  cursor: pointer;
  min-width: 280px;
  font-size: 0.86rem;
}
.toast-success {
  border-left-color: var(--color-success-fg);
}
.toast-error {
  border-left-color: var(--color-danger-fg);
}
.toast-warning {
  border-left-color: var(--color-warning-fg);
}
.toast-info {
  border-left-color: var(--color-info-fg);
}
.toast-icon {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
}
.toast-success .toast-icon { color: var(--color-success-fg); }
.toast-error .toast-icon { color: var(--color-danger-fg); }
.toast-warning .toast-icon { color: var(--color-warning-fg); }
.toast-info .toast-icon { color: var(--color-info-fg); }
.toast-body {
  flex: 1;
  min-width: 0;
}
.toast-title {
  font-weight: 600;
  color: var(--color-text-primary);
}
.toast-message {
  margin-top: 2px;
  color: var(--color-text-secondary);
  font-size: 0.8rem;
  word-wrap: break-word;
}
.toast-close {
  background: transparent;
  border: 0;
  color: var(--color-text-secondary);
  cursor: pointer;
  font-size: 1.1rem;
  line-height: 1;
  padding: 0 4px;
}
.toast-close:hover {
  color: var(--color-text-primary);
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.toast-leave-active {
  position: absolute;
  right: 0;
}
</style>
