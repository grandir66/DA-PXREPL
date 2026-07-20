<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import FileReplFolderCatalog from '../file-replication/FileReplFolderCatalog.vue'
import FileReplPathMapping from '../file-replication/FileReplPathMapping.vue'
import { nasSyncApi } from '../../services/nasSync'
import type { NasSyncJob } from '../../services/nasSync'
import {
  formatFileReplProgress,
  type FileReplProgress,
} from '../../utils/fileReplProgress'

interface FileReplLogEntry {
  id: number
  status: string
  message?: string | null
  output?: string | null
  error?: string | null
  duration?: number | null
  transferred?: string | null
  created_at?: string | null
  completed_at?: string | null
}

const props = defineProps<{
  jobId: number
  jobName: string
  job?: NasSyncJob | null
}>()

const emit = defineEmits<{ close: [] }>()

const logs = ref<FileReplLogEntry[]>([])
const progress = ref<FileReplProgress | null>(null)
const loading = ref(true)
let pollTimer: ReturnType<typeof setInterval> | null = null

const latest = computed(() => logs.value[0] ?? null)
const liveError = computed(() => progress.value?.error || latest.value?.error || null)
const isLive = computed(() =>
  ['running', 'cancelling', 'catalog_refresh'].includes(progress.value?.status || ''),
)
const progressText = computed(() => formatFileReplProgress(progress.value))
const reportText = computed(() => {
  if (isLive.value) return progressText.value
  if (progress.value?.report) return progress.value.report as string
  if (latest.value?.output?.includes('Cartelle replicate:')) {
    return latest.value.output.split('\n\n--- rclone')[0].trim()
  }
  return latest.value?.message || ''
})
const outputText = computed(() => {
  const raw = latest.value?.output || ''
  if (raw.includes('--- rclone/rsync ---')) {
    return raw.split('--- rclone/rsync ---').slice(1).join('--- rclone/rsync ---').trim()
  }
  return raw.trim()
})
const folderCatalog = computed(() => progress.value?.folder_catalog || [])
const catalogMode = computed((): 'catalog' | 'sync' => {
  const s = progress.value?.status
  if (s === 'catalog_refresh') return 'catalog'
  if (s === 'running' || s === 'cancelling') return 'sync'
  // Dopo du (success) o idle con lista: mostra come catalogo, non 0/N replicate
  if (progress.value?.catalog_view_mode === 'catalog') return 'catalog'
  if (s === 'success' && folderCatalog.value.length && !progress.value?.folders_done) {
    return 'catalog'
  }
  return 'sync'
})
const catalogActivityLabel = computed(() => {
  if (catalogMode.value === 'catalog') {
    return progress.value?.folder_activity_label || null
  }
  // Non mostrare «File sciolti» come titolo fuorviante a inizio run
  const label = progress.value?.folder_activity_label
  if (label && label.startsWith('File sciolti') && !(progress.value?.folders_done)) {
    return progress.value?.phase_label || 'Avvio replica…'
  }
  return label || null
})

async function refresh() {
  try {
    const [logsRes, progRes] = await Promise.all([
      nasSyncApi.logs(props.jobId),
      nasSyncApi.progress(props.jobId),
    ])
    logs.value = logsRes.data as FileReplLogEntry[]
    progress.value = progRes.data as FileReplProgress
  } finally {
    loading.value = false
  }
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(refresh, 2000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

watch(
  () => props.jobId,
  () => {
    loading.value = true
    refresh()
    startPolling()
  },
  { immediate: true },
)

onUnmounted(stopPolling)
</script>

<template>
  <div class="frl-overlay" @click.self="emit('close')">
    <div class="frl-modal card">
      <div class="card-header">
        <h3>Report sync — {{ jobName }}</h3>
        <button class="btn btn-sm btn-secondary" type="button" @click="emit('close')">Chiudi</button>
      </div>
      <div class="card-body">
        <FileReplPathMapping
          v-if="job?.source_paths?.length"
          class="frl-structure"
          compact
          show-header
          :max-rows="3"
          :source-paths="job.source_paths"
          :dest-share-path="job.dest_base_path"
          :source-label="job.source_endpoint_name"
          :dest-label="job.dest_endpoint_name"
        />

        <p v-if="loading && !logs.length" class="muted">Caricamento log…</p>

        <div v-if="progress?.status === 'running' || progress?.status === 'cancelling'" class="frl-running">
          <span class="frl-dot" /> In esecuzione
          <span v-if="progress.folder_activity_label" class="frl-step">
            — {{ progress.folder_activity_label }}
          </span>
          <span v-else-if="progress.message" class="frl-step"> — {{ progress.message }}</span>
        </div>
        <div v-else-if="progress?.status === 'catalog_refresh'" class="frl-running">
          <span class="frl-dot" /> Catalogo du
          <span v-if="progress.message" class="frl-step"> — {{ progress.message }}</span>
        </div>

        <p v-if="progressText" class="frl-progress-detail">
          {{ progressText }}
        </p>
        <p v-else-if="progress?.status === 'running'" class="frl-progress-detail muted">
          In attesa dati dal motore…
        </p>

        <div v-if="folderCatalog.length" class="frl-catalog">
          <FileReplFolderCatalog
            :folders="folderCatalog"
            :mode="catalogMode"
            :activity-label="catalogActivityLabel"
            :current-name="progress?.current_folder_name"
            :current-index="progress?.current_folder_index"
            :current-total="progress?.current_folder_total"
            :folders-done="progress?.folders_done"
          />
        </div>

        <p v-if="progress?.last_file" class="frl-last-file muted">
          Ultimo file: {{ progress.last_file }}
        </p>

        <div v-if="latest && latest.status !== 'started' && !isLive" class="frl-report">
          <strong>Ultimo report</strong>
          <p v-if="latest.duration != null" class="frl-meta">
            Durata {{ latest.duration }}s
            <span v-if="latest.transferred"> · {{ latest.transferred }}</span>
            <span v-if="latest.created_at"> · {{ new Date(latest.created_at).toLocaleString() }}</span>
          </p>
          <pre v-if="reportText">{{ reportText }}</pre>
        </div>

        <div v-if="liveError" class="frl-error">
          <strong>Errore</strong>
          <pre>{{ liveError }}</pre>
        </div>

        <div v-else-if="latest?.status === 'failed' && latest.message" class="frl-error">
          <strong>Fallito</strong>
          <pre>{{ latest.message }}</pre>
        </div>

        <div v-if="outputText" class="frl-output">
          <strong>Log tecnico</strong>
          <pre>{{ outputText }}</pre>
        </div>

        <p
          v-if="!loading && !liveError && !reportText && !outputText && !folderCatalog.length && !isLive"
          class="muted"
        >
          Nessun log disponibile. Se il job non parte, verifica rsync/sshpass sul server e SSH sui NAS.
        </p>

        <details v-if="logs.length > 1" class="frl-history">
          <summary>Storico esecuzioni ({{ logs.length }})</summary>
          <ul>
            <li v-for="log in logs" :key="log.id">
              <span :class="log.status === 'failed' ? 'text-danger' : log.status === 'success' ? 'text-success' : ''">
                {{ log.status }}
              </span>
              — {{ log.message || log.error || '—' }}
              <span v-if="log.transferred"> ({{ log.transferred }})</span>
              <small v-if="log.created_at">{{ new Date(log.created_at).toLocaleString() }}</small>
            </li>
          </ul>
        </details>
      </div>
    </div>
  </div>
</template>

<style scoped>
.frl-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  z-index: 1200;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.frl-modal {
  width: min(920px, 100%);
  max-height: 85vh;
  display: flex;
  flex-direction: column;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.card-body {
  overflow: auto;
  max-height: 70vh;
}
.frl-structure {
  margin-bottom: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.frl-catalog {
  margin: 0 0 12px;
}
.frl-report {
  margin-bottom: 12px;
  padding: 12px;
  border-radius: 8px;
  background: rgba(40, 167, 69, 0.08);
  border: 1px solid rgba(40, 167, 69, 0.25);
}
.frl-meta {
  margin: 4px 0 8px;
  font-size: 0.85rem;
  opacity: 0.8;
}
.frl-report pre {
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  font-size: 0.85rem;
}
.frl-running {
  color: #f0ad4e;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 0.9rem;
}
.frl-step {
  font-weight: 500;
}
.frl-progress-detail {
  margin: 0 0 8px;
  font-size: 0.88rem;
  font-weight: 600;
}
.frl-last-file {
  margin: 0 0 12px;
  font-size: 0.8rem;
  word-break: break-all;
}
.frl-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #f0ad4e;
  animation: pulse 1s infinite;
}
@keyframes pulse {
  50% { opacity: 0.3; }
}
.frl-error {
  background: rgba(220, 53, 69, 0.12);
  border: 1px solid rgba(220, 53, 69, 0.35);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
}
.frl-error pre,
.frl-output pre {
  white-space: pre-wrap;
  word-break: break-word;
  margin: 8px 0 0;
  font-size: 0.8rem;
  max-height: 280px;
  overflow: auto;
}
.frl-output {
  margin-bottom: 12px;
}
.frl-history {
  margin-top: 16px;
  font-size: 0.85rem;
}
.frl-history ul {
  margin: 8px 0 0;
  padding-left: 18px;
}
.muted { opacity: 0.7; }
</style>
