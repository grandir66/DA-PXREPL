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
  /** catalog = solo dimensioni du; sync = avanzamento copia */
  mode?: 'catalog' | 'sync'
  /** Path sorgente superiore (es. /FTP_BACKUP) a cui si riferisce l'elenco */
  parentPath?: string | null
  /** Più root se il job ha più source_paths */
  roots?: string[] | null
}>()

const viewMode = computed(() => props.mode || 'sync')

const parentPaths = computed(() => {
  if (props.roots?.length) return props.roots
  if (props.parentPath) return [props.parentPath]
  const fromFolders = [
    ...new Set(
      props.folders
        .map((f) => f.root)
        .filter((r): r is string => Boolean(r)),
    ),
  ]
  if (fromFolders.length) return fromFolders
  const parents = props.folders
    .map((f) => {
      const p = f.path || ''
      const i = p.lastIndexOf('/')
      return i > 0 ? p.slice(0, i) : null
    })
    .filter((p): p is string => Boolean(p))
  return [...new Set(parents)]
})

const activeFolder = computed(() =>
  props.folders.find((f) => f.status === 'in_progress'),
)

const headerLine = computed(() => {
  if (props.activityLabel) return props.activityLabel
  if (viewMode.value === 'catalog') return null
  if (activeFolder.value && props.currentIndex && props.currentTotal) {
    const full =
      activeFolder.value.path ||
      activeFolder.value.name ||
      ''
    return `In lavorazione: ${full} (${props.currentIndex}/${props.currentTotal})`
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

const summaryLine = computed(() => {
  if (viewMode.value === 'catalog') {
    return `${props.folders.length} cartelle catalogate (du)`
  }
  const parts = [`${doneCount.value}/${props.folders.length} replicate`]
  if (pendingCount.value) parts.push(`${pendingCount.value} in coda`)
  return parts.join(' · ')
})

function foldersForRoot(root: string) {
  return props.folders.filter((f) => {
    if (f.root) return f.root === root
    const p = f.path || ''
    return p === root || p.startsWith(`${root}/`)
  })
}

function statusLabel(status: string) {
  if (status === 'done') return 'Replicata'
  if (status === 'skipped') return 'Già allineata'
  if (status === 'in_progress') return 'In lavorazione'
  if (status === 'catalogued') return 'Nel catalogo du'
  return 'In coda'
}

function statusIcon(status: string) {
  if (status === 'done') return '✓'
  if (status === 'skipped') return '≈'
  if (status === 'in_progress') return '▶'
  if (status === 'catalogued') return '·'
  return '○'
}
</script>

<template>
  <div v-if="folders.length" class="frfc" :class="{ 'frfc-compact': compact }">
    <div class="frfc-head">
      <strong>
        {{ viewMode === 'catalog' ? 'Catalogo du (1° livello)' : 'Avanzamento replica' }}
      </strong>
      <span class="frfc-summary muted">{{ summaryLine }}</span>
    </div>

    <div v-if="parentPaths.length === 1" class="frfc-parent">
      <span class="frfc-parent-label">Sotto</span>
      <code class="frfc-parent-path">{{ parentPaths[0] }}</code>
    </div>

    <p v-if="headerLine" class="frfc-current">
      {{ headerLine }}
    </p>

    <template v-if="parentPaths.length > 1">
      <div v-for="root in parentPaths" :key="root" class="frfc-group">
        <div class="frfc-parent frfc-parent--group">
          <span class="frfc-parent-label">Sotto</span>
          <code class="frfc-parent-path">{{ root }}</code>
        </div>
        <ul class="frfc-list">
          <li
            v-for="folder in foldersForRoot(root)"
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
            </div>
          </li>
        </ul>
      </div>
    </template>

    <ul v-else class="frfc-list">
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
          <small
            v-if="folder.status === 'in_progress' && folder.path && folder.path !== folder.name"
            class="frfc-path muted"
          >
            {{ folder.path }}
          </small>
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
  margin-bottom: 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  font-size: 0.82rem;
}
.frfc-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 6px;
  font-size: 0.8rem;
}
.frfc-summary { font-size: 0.75rem; }
.frfc-parent {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin: 0 0 8px;
  padding: 6px 8px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.06);
}
.frfc-parent--group {
  margin-bottom: 4px;
}
.frfc-parent-label {
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  opacity: 0.55;
  flex-shrink: 0;
}
.frfc-parent-path {
  font-size: 0.8rem;
  font-weight: 600;
  word-break: break-all;
  color: #7ec8e3;
}
.frfc-group {
  margin-bottom: 10px;
}
.frfc-group:last-child {
  margin-bottom: 0;
}
.frfc-current {
  margin: 0 0 8px;
  font-size: 0.8rem;
}
.frfc-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 360px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 255, 255, 0.22) transparent;
}
.frfc-list::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
.frfc-list::-webkit-scrollbar-track {
  background: transparent;
}
.frfc-list::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.22);
  border-radius: 4px;
}
.frfc-list::-webkit-scrollbar-corner {
  background: transparent;
}
.frfc-compact .frfc-list {
  max-height: 140px;
}
.frfc-item {
  display: flex;
  gap: 8px;
  padding: 5px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.frfc-item:last-child { border-bottom: none; }
.frfc-item--done { opacity: 0.72; }
.frfc-item--skipped { opacity: 0.8; }
.frfc-item--in_progress {
  background: rgba(240, 173, 78, 0.08);
  margin: 0 -6px;
  padding: 5px 6px;
  border-radius: 6px;
  border-bottom-color: transparent;
}
.frfc-icon {
  width: 16px;
  flex-shrink: 0;
  text-align: center;
  font-size: 0.75rem;
  line-height: 1.4;
}
.frfc-item--done .frfc-icon { color: #28a745; }
.frfc-item--skipped .frfc-icon { color: #5bc0de; }
.frfc-item--in_progress .frfc-icon { color: #f0ad4e; }
.frfc-item--pending .frfc-icon { color: rgba(255, 255, 255, 0.35); }
.frfc-item--catalogued .frfc-icon { color: rgba(255, 255, 255, 0.45); }
.frfc-body { flex: 1; min-width: 0; }
.frfc-row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: baseline;
}
.frfc-name {
  font-weight: 500;
  font-size: 0.8rem;
  word-break: break-word;
}
.frfc-path {
  display: block;
  margin-top: 2px;
  font-size: 0.7rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  word-break: break-all;
  opacity: 0.75;
}
.frfc-size {
  font-size: 0.72rem;
  white-space: nowrap;
}
.frfc-bar {
  height: 4px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
  overflow: hidden;
  margin-top: 4px;
}
.frfc-bar-fill {
  height: 100%;
  background: #f0ad4e;
  transition: width 0.4s ease;
}
.frfc-progress {
  display: block;
  margin-top: 2px;
  font-size: 0.72rem;
}
.muted { opacity: 0.7; }
</style>
