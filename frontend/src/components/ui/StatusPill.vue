<template>
  <span class="pill" :class="[`pill-${tone}`, { 'pill-pulse': pulse }]">
    <span v-if="dot" class="pill-dot" />
    <Icon v-else-if="iconName" :name="iconName" :size="12" class="pill-icon" />
    <span class="pill-text">{{ label }}</span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Icon from './Icon.vue'

export type StatusTone = 'success' | 'danger' | 'warning' | 'info' | 'neutral' | 'zfs' | 'pbs'

const props = withDefaults(
  defineProps<{
    label: string
    tone?: StatusTone
    icon?: string
    dot?: boolean
    pulse?: boolean
  }>(),
  {
    tone: 'neutral',
    dot: true,
    pulse: false,
  }
)

const iconName = computed(() => props.icon)
</script>

<style scoped>
.pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  border-radius: 999px;
  border: 1px solid transparent;
  white-space: nowrap;
  line-height: 1.4;
}
.pill-text {
  text-transform: capitalize;
}
.pill-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
.pill-icon {
  width: 11px;
  height: 11px;
}

.pill-success {
  background: var(--color-success-dim);
  color: var(--color-success-fg);
  border-color: rgba(46, 160, 67, 0.25);
}
.pill-danger {
  background: var(--color-danger-dim);
  color: var(--color-danger-fg);
  border-color: rgba(248, 81, 73, 0.25);
}
.pill-warning {
  background: var(--color-warning-dim);
  color: var(--color-warning-fg);
  border-color: rgba(187, 128, 9, 0.25);
}
.pill-info {
  background: var(--color-info-dim);
  color: var(--color-info-fg);
  border-color: rgba(56, 139, 253, 0.25);
}
.pill-neutral {
  background: var(--color-bg-element);
  color: var(--color-text-secondary);
  border-color: var(--color-border);
}
.pill-zfs {
  background: rgba(115, 183, 86, 0.15);
  color: var(--color-zfs);
  border-color: rgba(115, 183, 86, 0.3);
}
.pill-pbs {
  background: rgba(224, 93, 68, 0.15);
  color: var(--color-pbs);
  border-color: rgba(224, 93, 68, 0.3);
}

.pill-pulse .pill-dot {
  animation: pulse-dot 1.4s ease-in-out infinite;
}
@keyframes pulse-dot {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.6; transform: scale(1.25); }
}
</style>
