<template>
  <div class="metric-ring" :style="{ width: `${size}px`, height: `${size}px` }" :title="title">
    <svg :width="size" :height="size" :viewBox="`0 0 ${size} ${size}`">
      <circle
        class="metric-ring-track"
        :cx="center"
        :cy="center"
        :r="radius"
        fill="none"
        :stroke-width="stroke"
      />
      <circle
        class="metric-ring-fill"
        :class="toneClass"
        :cx="center"
        :cy="center"
        :r="radius"
        fill="none"
        :stroke-width="stroke"
        :stroke-dasharray="circumference"
        :stroke-dashoffset="dashOffset"
        stroke-linecap="round"
        :transform="`rotate(-90 ${center} ${center})`"
      />
    </svg>
    <div class="metric-ring-label">
      <span class="metric-ring-value">{{ clamped.toFixed(0) }}%</span>
      <span v-if="sublabel" class="metric-ring-sublabel">{{ sublabel }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    value: number
    size?: number
    stroke?: number
    warning?: number
    danger?: number
    sublabel?: string
    title?: string
  }>(),
  {
    size: 56,
    stroke: 5,
    warning: 70,
    danger: 85,
  },
)

const clamped = computed(() => Math.min(100, Math.max(0, props.value || 0)))
const center = computed(() => props.size / 2)
const radius = computed(() => (props.size - props.stroke) / 2)
const circumference = computed(() => 2 * Math.PI * radius.value)
const dashOffset = computed(() => circumference.value * (1 - clamped.value / 100))

const toneClass = computed(() => {
  if (clamped.value >= props.danger) return 'tone-danger'
  if (clamped.value >= props.warning) return 'tone-warning'
  return 'tone-ok'
})
</script>

<style scoped>
.metric-ring {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.metric-ring-track {
  stroke: var(--color-bg-element, rgba(255, 255, 255, 0.08));
}
.metric-ring-fill {
  transition: stroke-dashoffset 0.35s ease;
}
.metric-ring-fill.tone-ok {
  stroke: var(--color-primary);
}
.metric-ring-fill.tone-warning {
  stroke: var(--color-warning-fg, #fbbf24);
}
.metric-ring-fill.tone-danger {
  stroke: var(--color-danger-fg, #f87171);
}
.metric-ring-label {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.metric-ring-value {
  font-size: 0.72rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--color-text-primary);
  line-height: 1;
}
.metric-ring-sublabel {
  font-size: 0.55rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text-secondary);
  margin-top: 2px;
}
</style>
