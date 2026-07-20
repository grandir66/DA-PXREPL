<template>
  <svg
    v-if="points.length >= 2"
    class="metric-sparkline"
    :width="width"
    :height="height"
    :viewBox="`0 0 ${width} ${height}`"
    preserveAspectRatio="none"
    :title="title"
  >
    <polyline
      :points="polylinePoints"
      fill="none"
      :stroke="strokeColor"
      stroke-width="1.5"
      stroke-linejoin="round"
      stroke-linecap="round"
    />
  </svg>
  <span v-else class="metric-sparkline-empty" :title="title">—</span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    values: number[]
    width?: number
    height?: number
    warning?: number
    danger?: number
    title?: string
  }>(),
  {
    width: 72,
    height: 24,
    warning: 70,
    danger: 85,
  },
)

const points = computed(() =>
  props.values.filter((v) => Number.isFinite(v)).map((v) => Math.min(100, Math.max(0, v))),
)

const strokeColor = computed(() => {
  const last = points.value[points.value.length - 1] ?? 0
  if (last >= props.danger) return 'var(--color-danger-fg, #f87171)'
  if (last >= props.warning) return 'var(--color-warning-fg, #fbbf24)'
  return 'var(--color-primary)'
})

const polylinePoints = computed(() => {
  const vals = points.value
  if (vals.length < 2) return ''
  const max = Math.max(...vals, 1)
  const min = Math.min(...vals, 0)
  const span = Math.max(max - min, 1)
  return vals
    .map((v, i) => {
      const x = (i / (vals.length - 1)) * props.width
      const y = props.height - ((v - min) / span) * (props.height - 2) - 1
      return `${x},${y}`
    })
    .join(' ')
})
</script>

<style scoped>
.metric-sparkline {
  display: block;
  opacity: 0.9;
}
.metric-sparkline-empty {
  font-size: 0.75rem;
  color: var(--color-text-secondary);
}
</style>
