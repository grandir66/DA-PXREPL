<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { fileReplicationApi } from '../../services/fileReplication'

interface FileReplLogEntry {
  id: number
  status: string
  message?: string | null
  output?: string | null
  error?: string | null
  created_at?: string | null
}

const props = defineProps<{
  jobId: number
  jobName: string
}>()

const emit = defineEmits<{ close: [] }>()

const logs = ref<FileReplLogEntry[]>([])
const progress = ref<{ status?: string; error?: string; percent?: string } | null>(null)
const loading = ref(true)
let pollTimer: ReturnType<typeof setInterval> | null = null

const latest = computed(() => logs.value[0] ?? null)
const liveError = computed(() => progress.value?.error || latest.value?.error || null)
const outputText = computed(() => {
  const parts: string[] = []
  if (latest.value?.message) parts.push(latest.value.message)
  if (latest.value?.output) parts.push(latest.value.output)
  return parts.join('\n\n').trim()
})

async function refresh() {
  try {
    const [logsRes, progRes] = await Promise.all([
      fileReplicationApi.logs(props.jobId),
      fileReplicationApi.progress(props.jobId),
    ])
    logs.value = logsRes.data as FileReplLogEntry[]
    progress.value = progRes.data as typeof progress.value
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
        <h3>Log — {{ jobName }}</h3>
        <button class="btn btn-sm btn-secondary" type="button" @click="emit('close')">Chiudi</button>
      </div>
      <div class="card-body">
        <p v-if="loading && !logs.length" class="muted">Caricamento log…</p>

        <div v-if="progress?.status === 'running'" class="frl-running">
          <span class="frl-dot" /> In esecuzione
          <span v-if="progress.percent"> — {{ progress.percent }}</span>
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
          <strong>Output</strong>
          <pre>{{ outputText }}</pre>
        </div>

        <p v-if="!loading && !liveError && !outputText && progress?.status !== 'running'" class="muted">
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
.card-body {
  overflow: auto;
  max-height: 70vh;
}
.frl-running {
  color: #f0ad4e;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
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
