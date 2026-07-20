<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import FileReplPathMapping from './FileReplPathMapping.vue'
import FileReplFolderCatalog from './FileReplFolderCatalog.vue'
import { fileReplicationApi } from '../../services/fileReplication'
import type { FileReplicationJob } from '../../services/fileReplication'
import {
  formatFileReplProgress,
  fileReplProgressPercent,
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
  job?: FileReplicationJob | null
}>()

const emit = defineEmits<{ close: []; pause: []; resume: []; fresh: [] }>()

const logs = ref<FileReplLogEntry[]>([])
const progress = ref<FileReplProgress | null>(null)
const loading = ref(true)
let pollTimer: ReturnType<typeof setInterval> | null = null

const latest = computed(() => logs.value[0] ?? null)
const liveError = computed(() => progress.value?.error || latest.value?.error || null)
const progressText = computed(() => formatFileReplProgress(progress.value))
const isLive = computed(
  () =>
    progress.value?.status === 'running' ||
    progress.value?.status === 'cancelling' ||
    props.job?.current_status === 'running',
)
const isPaused = computed(
  () =>
    progress.value?.status === 'paused' ||
    props.job?.current_status === 'paused' ||
    props.job?.last_run_status === 'paused',
)
const reportText = computed(() => {
  if (progress.value?.status === 'running') return progressText.value
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

async function refresh() {
  try {
    const [logsRes, progRes] = await Promise.all([
      fileReplicationApi.logs(props.jobId),
      fileReplicationApi.progress(props.jobId),
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
        <div class="frl-header-actions">
          <button
            v-if="isLive"
            class="btn btn-sm btn-warning"
            type="button"
            @click="emit('pause')"
          >
            Pausa
          </button>
          <template v-else-if="isPaused">
            <button class="btn btn-sm btn-primary" type="button" @click="emit('resume')">
              Riprendi
            </button>
            <button class="btn btn-sm btn-secondary" type="button" @click="emit('fresh')">
              Da capo
            </button>
          </template>
          <button class="btn btn-sm btn-secondary" type="button" @click="emit('close')">Chiudi</button>
        </div>
      </div>
      <div class="card-body">
        <FileReplPathMapping
          v-if="job?.source_paths?.length"
          class="frl-structure"
          compact
          show-header
          :max-rows="3"
          :source-paths="job.source_paths"
          :dest-share-path="job.dest_staging_path"
          :source-label="job.source_endpoint_name"
          :dest-label="job.dest_endpoint_name"
        />

        <p v-if="loading && !logs.length" class="muted">Caricamento log…</p>

        <div v-if="isPaused && !isLive" class="frl-paused">
          <strong>In pausa</strong>
          <span v-if="job?.resume_from_path"> — riprendi da {{ job.resume_from_path }}</span>
        </div>

        <div v-if="isLive" class="frl-running">
          <span class="frl-dot" />
          {{ progress?.status === 'cancelling' ? 'Interruzione in corso…' : (progress?.phase_label || 'In esecuzione') }}
          <span v-if="progress?.message" class="frl-step"> — {{ progress.message }}</span>
        </div>

        <div v-if="isLive && progress" class="frl-live-panel">
          <FileReplFolderCatalog
            v-if="progress.folder_catalog?.length"
            :folders="progress.folder_catalog"
            :activity-label="progress.folder_activity_label"
            :current-name="progress.current_folder_name"
            :current-index="progress.current_folder_index"
            :current-total="progress.current_folder_total"
            :folders-done="progress.folders_done"
          />
          <div
            v-if="fileReplProgressPercent(progress) != null"
            class="frl-progress-bar"
            role="progressbar"
            :aria-valuenow="fileReplProgressPercent(progress) ?? 0"
          >
            <div class="frl-progress-fill" :style="{ width: `${fileReplProgressPercent(progress)}%` }" />
          </div>
          <ul v-if="progress.detail_lines?.length" class="frl-detail-lines">
            <li v-for="(line, idx) in progress.detail_lines" :key="idx">{{ line }}</li>
          </ul>
          <p v-else-if="progressText" class="frl-progress-detail">{{ progressText }}</p>
          <p v-else class="frl-progress-detail muted">In attesa dati da rclone…</p>
          <p v-if="progress.hint" class="frl-hint">{{ progress.hint }}</p>
          <p v-if="progress.show_last_file !== false && progress.last_file" class="frl-last-file muted">
            Ultimo file: {{ progress.last_file }}
          </p>
        </div>

        <FileReplFolderCatalog
          v-else-if="isPaused && progress?.folder_catalog?.length"
          :folders="progress.folder_catalog"
          :activity-label="progress.folder_activity_label"
          :current-name="progress.current_folder_name"
          :current-index="progress.current_folder_index"
          :current-total="progress.current_folder_total"
          :folders-done="progress.folders_done"
        />

        <p v-else-if="progressText" class="frl-progress-detail">
          {{ progressText }}
        </p>

        <div v-if="latest && latest.status !== 'started'" class="frl-report">
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

        <p v-if="!loading && !liveError && !reportText && !outputText && progress?.status !== 'running'" class="muted">
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
  width: min(900px, 100%);
  max-height: 85vh;
  display: flex;
  flex-direction: column;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.frl-header-actions {
  display: flex;
  gap: 8px;
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
.frl-paused {
  color: #5bc0de;
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(13, 202, 240, 0.08);
  border: 1px solid rgba(13, 202, 240, 0.25);
}
.frl-running {
  color: #f0ad4e;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.frl-step {
  font-weight: 500;
}
.frl-progress-detail {
  margin: 0 0 8px;
  font-size: 1rem;
  font-weight: 600;
}
.frl-live-panel {
  margin-bottom: 12px;
  padding: 12px;
  border-radius: 8px;
  background: rgba(240, 173, 78, 0.08);
  border: 1px solid rgba(240, 173, 78, 0.25);
}
.frl-progress-bar {
  height: 8px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 10px;
}
.frl-progress-fill {
  height: 100%;
  background: #f0ad4e;
  transition: width 0.4s ease;
}
.frl-detail-lines {
  margin: 0 0 8px;
  padding-left: 18px;
  font-size: 0.95rem;
}
.frl-detail-lines li { margin-bottom: 4px; }
.frl-hint {
  margin: 0 0 8px;
  font-size: 0.85rem;
  opacity: 0.85;
  font-style: italic;
}
.frl-last-file {
  margin: 0 0 12px;
  font-size: 0.85rem;
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
  font-size: 0.85rem;
  max-height: 320px;
  overflow: auto;
}
.frl-output {
  margin-bottom: 12px;
}
.frl-history {
  margin-top: 16px;
  font-size: 0.9rem;
}
.frl-history ul {
  margin: 8px 0 0;
  padding-left: 18px;
}
.muted { opacity: 0.7; }
</style>
