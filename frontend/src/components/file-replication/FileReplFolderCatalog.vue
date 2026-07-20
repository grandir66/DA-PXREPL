<script setup lang="ts">
import { computed } from 'vue'
import type { FileReplFolderItem } from '../../utils/fileReplProgress'

const props = defineProps<{
  folders: FileReplFolderItem[]
  activityLabel?: string | null
  currentName?: string | null
  currentIndex?: number | null
  currentTotal?: number | null
  foldersDone?: number | null
  compact?: boolean
}>()

const activeFolder = computed(() =>
  props.folders.find((f) => f.status === 'in_progress'),
)

const headerLine = computed(() => {
  if (props.activityLabel) return props.activityLabel
  if (activeFolder.value && props.currentIndex && props.currentTotal) {
    return `In lavorazione: ${activeFolder.value.name || activeFolder.value.path} (${props.currentIndex}/${props.currentTotal})`
  }
  return null
})

const doneCount = computed(
  () =>
    props.foldersDone ??
    props.folders.filter((f) => f.status === 'done' || f.status === 'skipped').length,
)
const pendingCount = computed(
  () => props.folders.filter((f) => f.status === 'pending').length,
)

function statusLabel(status: string) {
  if (status === 'done') return 'Completata'
  if (status === 'skipped') return 'Già allineata'
  if (status === 'in_progress') return 'In lavorazione'
  return 'In attesa'
}

function statusIcon(status: string) {
  if (status === 'done') return '✓'
  if (status === 'skipped') return '≈'
  if (status === 'in_progress') return '▶'
  return '○'
}
</script>

<template>
  <div v-if="folders.length" class="frfc" :class="{ 'frfc-compact': compact }">
    <div class="frfc-head">
      <strong>Cartelle sorgente (du 1° livello)</strong>
      <span class="frfc-summary muted">
        {{ doneCount }}/{{ folders.length }} completate
        <span v-if="pendingCount"> · {{ pendingCount }} in attesa</span>
      </span>
    </div>
    <p v-if="headerLine" class="frfc-current">
      {{ headerLine }}
    </p>
    <ul class="frfc-list">
      <li
        v-for="folder in folders"
        :key="folder.path"
        class="frfc-item"
        :class="`frfc-item--${folder.status}`"
      >
        <span class="frfc-icon" :title="statusLabel(folder.status)">{{ statusIcon(folder.status) }}</span>
        <div class="frfc-body">
          <div class="frfc-row">
            <span class="frfc-name">{{ folder.name || folder.path }}</span>
            <span v-if="folder.size_human" class="frfc-size muted">{{ folder.size_human }}</span>
          </div>
          <div
            v-if="folder.status === 'in_progress' && folder.progress_pct != null"
            class="frfc-bar"
            role="progressbar"
            :aria-valuenow="folder.progress_pct"
          >
            <div class="frfc-bar-fill" :style="{ width: `${folder.progress_pct}%` }" />
          </div>
          <small
            v-if="folder.status_hint"
            class="frfc-progress muted"
          >
            {{ folder.status_hint }}
          </small>
          <small
            v-else-if="folder.status === 'in_progress' && (folder.session_human || folder.progress_pct != null)"
            class="frfc-progress muted"
          >
            <template v-if="folder.session_human">{{ folder.session_human }} elaborati</template>
            <template v-if="folder.progress_pct != null"> (~{{ folder.progress_pct }}% cartella)</template>
          </small>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.frfc {
  margin-bottom: 12px;
  padding: 12px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.frfc-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.frfc-summary { font-size: 0.85rem; }
.frfc-current {
  margin: 0 0 10px;
  font-size: 0.95rem;
}
.frfc-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 280px;
  overflow-y: auto;
}
.frfc-compact .frfc-list {
  max-height: 160px;
}
.frfc-item {
  display: flex;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.frfc-item:last-child { border-bottom: none; }
.frfc-item--done { opacity: 0.72; }
.frfc-item--skipped { opacity: 0.8; }
.frfc-item--in_progress {
  background: rgba(240, 173, 78, 0.08);
  margin: 0 -8px;
  padding: 8px;
  border-radius: 6px;
  border-bottom-color: transparent;
}
.frfc-icon {
  width: 18px;
  flex-shrink: 0;
  text-align: center;
  font-size: 0.85rem;
  line-height: 1.4;
}
.frfc-item--done .frfc-icon { color: #28a745; }
.frfc-item--skipped .frfc-icon { color: #5bc0de; }
.frfc-item--in_progress .frfc-icon { color: #f0ad4e; }
.frfc-item--pending .frfc-icon { color: rgba(255, 255, 255, 0.35); }
.frfc-body { flex: 1; min-width: 0; }
.frfc-row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: baseline;
}
.frfc-name {
  font-weight: 500;
  word-break: break-word;
}
.frfc-size {
  font-size: 0.8rem;
  white-space: nowrap;
}
.frfc-bar {
  height: 6px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
  overflow: hidden;
  margin-top: 6px;
}
.frfc-bar-fill {
  height: 100%;
  background: #f0ad4e;
  transition: width 0.4s ease;
}
.frfc-progress {
  display: block;
  margin-top: 4px;
  font-size: 0.8rem;
}
.muted { opacity: 0.7; }
</style>
