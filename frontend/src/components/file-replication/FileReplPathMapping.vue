<script setup lang="ts">
import { computed } from 'vue'
import { buildFileReplMappings, formatDestShareLabel } from '../../utils/fileReplPaths'
import { normalizeQnapDestShare } from '../../utils/qnapPath'

const props = withDefaults(
  defineProps<{
    sourcePaths: string[]
    destSharePath: string
    sourceLabel?: string | null
    destLabel?: string | null
    /** Vista minima (tabella job, log) */
    compact?: boolean
    /** Una riga di contesto endpoint/share */
    showHeader?: boolean
    maxRows?: number
  }>(),
  {
    compact: false,
    showHeader: false,
    maxRows: 0,
  },
)

const destShare = computed(() => normalizeQnapDestShare(props.destSharePath))
const shareLabel = computed(() => formatDestShareLabel(destShare.value))

const rows = computed(() => buildFileReplMappings(props.sourcePaths, destShare.value))

const visibleRows = computed(() => {
  if (!props.maxRows || props.maxRows <= 0) return rows.value
  return rows.value.slice(0, props.maxRows)
})

const hiddenCount = computed(() => {
  if (!props.maxRows || props.maxRows <= 0) return 0
  return Math.max(0, rows.value.length - props.maxRows)
})

function shortPath(path: string) {
  return path.replace(/^\/+/, '').replace(/\/+$/, '')
}
</script>

<template>
  <div class="frpm" :class="{ 'frpm-compact': compact }">
    <p v-if="showHeader && rows.length" class="frpm-head">
      <span>{{ sourceLabel || 'Synology' }}</span>
      <span class="frpm-arr">→</span>
      <span>{{ destLabel || 'QNAP' }}/<code>{{ shareLabel }}</code></span>
    </p>

    <p v-if="!rows.length" class="frpm-empty">Nessuna cartella sorgente.</p>

    <ul v-else class="frpm-list">
      <li v-for="row in visibleRows" :key="row.sourcePath" class="frpm-row">
        <code>{{ shortPath(row.sourcePath) }}</code>
        <span class="frpm-arr">→</span>
        <code>{{ shortPath(row.destPath) }}</code>
      </li>
    </ul>

    <p v-if="hiddenCount > 0" class="frpm-more">+{{ hiddenCount }} cartelle</p>
  </div>
</template>

<style scoped>
.frpm {
  font-size: 0.82rem;
  line-height: 1.35;
}
.frpm-head {
  margin: 0 0 4px;
  opacity: 0.75;
  font-size: 0.78rem;
}
.frpm-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.frpm-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px;
  padding: 1px 0;
}
.frpm-arr {
  opacity: 0.45;
  flex-shrink: 0;
}
.frpm-row code,
.frpm-head code {
  font-size: 0.8em;
  word-break: break-all;
}
.frpm-empty,
.frpm-more {
  margin: 0;
  opacity: 0.6;
  font-size: 0.78rem;
}
.frpm-compact {
  font-size: 0.78rem;
}
.frpm-compact .frpm-row {
  gap: 4px;
}
</style>
