<template>
  <Teleport to="body">
    <transition name="confirm">
      <div v-if="store.visible" class="confirm-overlay" @click.self="cancel">
        <div class="confirm-modal" :class="{ 'is-danger': store.options?.danger }" role="alertdialog">
          <div class="confirm-icon" :class="{ danger: store.options?.danger }">
            <Icon :name="store.options?.danger ? 'alert-triangle' : 'help-circle'" />
          </div>
          <h3 class="confirm-title">{{ store.options?.title }}</h3>
          <p v-if="store.options?.message" class="confirm-message">
            {{ store.options.message }}
          </p>
          <div class="confirm-actions">
            <button class="btn btn-secondary" @click="cancel" autofocus>
              {{ store.options?.cancelText || 'Annulla' }}
            </button>
            <button
              class="btn"
              :class="store.options?.danger ? 'btn-danger' : 'btn-primary'"
              @click="confirm"
            >
              {{ store.options?.confirmText || 'Conferma' }}
            </button>
          </div>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useConfirmStore } from '../../stores/confirm'
import Icon from './Icon.vue'

const store = useConfirmStore()

function confirm() {
  store.resolve(true)
}
function cancel() {
  store.resolve(false)
}
function onKeydown(e: KeyboardEvent) {
  if (!store.visible) return
  if (e.key === 'Escape') cancel()
  if (e.key === 'Enter') confirm()
}
onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
.confirm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  backdrop-filter: blur(4px);
  z-index: 4500;
  display: flex;
  align-items: center;
  justify-content: center;
}
.confirm-modal {
  width: min(440px, 92vw);
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
  text-align: center;
  box-shadow: var(--shadow-lg);
}
.confirm-modal.is-danger {
  border-color: var(--color-danger-fg);
}
.confirm-icon {
  width: 48px;
  height: 48px;
  margin: 0 auto var(--space-3);
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--color-info-dim);
  color: var(--color-info-fg);
}
.confirm-icon.danger {
  background: var(--color-danger-dim);
  color: var(--color-danger-fg);
}
.confirm-icon :deep(svg) {
  width: 26px;
  height: 26px;
}
.confirm-title {
  margin: 0 0 var(--space-2);
  font-size: 1.05rem;
  color: var(--color-text-primary);
}
.confirm-message {
  margin: 0 0 var(--space-4);
  color: var(--color-text-secondary);
  font-size: 0.88rem;
  line-height: 1.45;
}
.confirm-actions {
  display: flex;
  gap: var(--space-2);
  justify-content: center;
}

.confirm-enter-from,
.confirm-leave-to {
  opacity: 0;
}
.confirm-enter-from .confirm-modal,
.confirm-leave-to .confirm-modal {
  transform: scale(0.95);
}
.confirm-enter-active,
.confirm-leave-active {
  transition: opacity 0.15s ease;
}
.confirm-enter-active .confirm-modal,
.confirm-leave-active .confirm-modal {
  transition: transform 0.15s ease;
}
</style>
