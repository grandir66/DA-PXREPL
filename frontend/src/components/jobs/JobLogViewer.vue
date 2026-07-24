<template>
  <div v-if="visible" class="jlv-overlay">
    <div class="jlv-modal">
      <header class="jlv-head">
        <div>
          <h2 class="jlv-title">
            <Icon name="terminal" :size="16" /> Log job
            <span class="jlv-subtitle" v-if="jobName">— {{ jobName }}</span>
          </h2>
          <div class="jlv-meta">
            <StatusPill
              :label="statusLabel"
              :tone="statusTone"
              :pulse="progress?.is_running"
            />
            <span v-if="progress?.last_run" class="jlv-meta-item">
              ultimo run: {{ formatTime(progress.last_run) }}
            </span>
            <span v-if="progress?.last_duration" class="jlv-meta-item">
              durata: {{ progress.last_duration }}s
            </span>
            <span v-if="progress?.last_transferred" class="jlv-meta-item">
              trasferito: {{ progress.last_transferred }}
            </span>
            <span v-if="progress?.run_count != null" class="jlv-meta-item">
              {{ progress.run_count }} run, {{ progress.error_count || 0 }} errori
            </span>
          </div>
        </div>
        <div class="jlv-head-actions">
          <label class="jlv-follow">
            <input type="checkbox" v-model="autoScroll" /> auto-scroll
          </label>
          <button class="btn btn-secondary btn-sm" @click="copyOutput" :disabled="!hasOutput">
            <Icon name="copy" :size="14" /> Copia
          </button>
          <button class="btn-icon" @click="close" aria-label="Chiudi">
            <Icon name="x" :size="18" />
          </button>
        </div>
      </header>

      <div v-if="transferProgress" class="jlv-progress-wrap">
        <div class="jlv-progress-top">
          <span>Avanzamento replica</span>
          <span class="jlv-progress-pct">{{ transferProgress.percent.toFixed(1) }}%</span>
        </div>
        <div class="jlv-progress-bar">
          <div
            class="jlv-progress-fill"
            :style="{ width: Math.min(100, transferProgress.percent) + '%' }"
          />
        </div>
        <div class="jlv-progress-sub">
          {{ transferProgress.dest_human }} scritti su {{ transferProgress.source_human }} (sorgente)
        </div>
      </div>

      <div class="jlv-output" ref="outputRef">
        <div v-if="fatalError" class="jlv-fatal">
          <Icon name="alert-triangle" :size="32" />
          <h3>Endpoint log non disponibile</h3>
          <p>
            Il backend installato non espone <code>/api/sync-jobs/{id}/progress</code>
            (oppure il servizio non è stato riavviato dopo l'update).
          </p>
          <p class="jlv-fatal-hint">
            Risoluzione: sul container <code>systemctl restart dapx-unified</code>,
            oppure verifica che la versione installata sia ≥ 3.13.0.
          </p>
          <p class="jlv-fatal-detail" v-if="fetchError">{{ fetchError }}</p>
        </div>
        <pre v-else-if="output.length"><span
          v-for="(line, i) in output"
          :key="i"
          class="jlv-line"
        >{{ line }}
</span></pre>
        <EmptyState
          v-else-if="!loading"
          title="Nessun log"
          message="Il job non ha ancora prodotto output."
          icon="file-text"
        />
        <LoadingState v-if="loading && !output.length && !fatalError" message="Caricamento log…" />
      </div>

      <footer class="jlv-foot">
        <div class="jlv-msg">
          <span v-if="progress?.log?.error" class="jlv-error">
            <Icon name="alert-triangle" :size="14" />
            {{ progress.log.error }}
          </span>
          <span v-else-if="progress?.log?.message">{{ progress.log.message }}</span>
        </div>
        <div class="jlv-stats">
          <span v-if="fatalError" class="jlv-error">polling fermo</span>
          <span v-else-if="progress?.is_running" class="jlv-pulse">
            <span class="dot" /> in esecuzione
          </span>
          <span v-else>aggiornato {{ secondsAgo }}s fa</span>
        </div>
      </footer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch, nextTick } from 'vue'
import apiClient from '../../services/api'
import Icon from '../ui/Icon.vue'
import StatusPill from '../ui/StatusPill.vue'
import EmptyState from '../ui/EmptyState.vue'
import LoadingState from '../ui/LoadingState.vue'
import { useToast, errorMessage } from '../../stores/toast'

const props = withDefaults(
  defineProps<{
    visible: boolean
    jobId: number | string | null
    jobName?: string
    /** intervallo polling ms */
    pollMs?: number
  }>(),
  {
    pollMs: 3000,  // P-09: 1.5s era troppo aggressivo
  }
)
const emit = defineEmits<{ (e: 'update:visible', v: boolean): void }>()
const toast = useToast()

interface TransferProgress {
  percent: number
  source_bytes: number
  dest_bytes: number
  source_human: string
  dest_human: string
  label: string
}

interface ProgressPayload {
  id: number
  name: string
  is_running: boolean
  current_status: string | null
  last_status: string | null
  last_run: string | null
  last_duration: number | null
  last_transferred: string | null
  run_count: number
  error_count: number
  transfer_progress?: TransferProgress | null
  log: null | {
    id: number
    status: string
    started_at: string | null
    completed_at: string | null
    message: string | null
    duration: number | null
    transferred: string | null
    error: string | null
    output_tail: string[]
  }
}

const progress = ref<ProgressPayload | null>(null)
const loading = ref(false)
const autoScroll = ref(true)
const outputRef = ref<HTMLElement | null>(null)
const lastFetchedAt = ref<number>(0)
const secondsAgo = ref(0)
const fetchError = ref<string | null>(null)
const fatalError = ref<boolean>(false)

let poller: number | null = null
let secTicker: number | null = null
let toastShown = false

const output = computed(() => progress.value?.log?.output_tail || [])
const hasOutput = computed(() => output.value.length > 0)
const transferProgress = computed(() => progress.value?.transfer_progress ?? null)

const statusLabel = computed(() => {
  if (progress.value?.is_running) return 'in esecuzione'
  const logStatus = (progress.value?.log?.status || '').toLowerCase()
  if (logStatus === 'started') return 'in esecuzione'
  const s = (progress.value?.current_status || progress.value?.last_status || 'idle').toLowerCase()
  return ({
    success: 'successo',
    failed: 'fallito',
    running: 'in esecuzione',
    started: 'in esecuzione',
    idle: 'in attesa',
  } as Record<string, string>)[s] || s
})
const statusTone = computed<'success' | 'danger' | 'warning' | 'info' | 'neutral'>(() => {
  if (progress.value?.is_running) return 'warning'
  const logStatus = (progress.value?.log?.status || '').toLowerCase()
  if (logStatus === 'started') return 'warning'
  const s = (progress.value?.current_status || progress.value?.last_status || '').toLowerCase()
  if (s === 'success') return 'success'
  if (s === 'failed' || s === 'error') return 'danger'
  if (s === 'running' || s === 'started') return 'warning'
  return 'neutral'
})

async function fetchViaLegacyLogs(): Promise<ProgressPayload | null> {
  // Fallback per backend pre-3.13.0 (no /progress): ricostruisce il
  // payload usando l'endpoint storico /logs che ritorna un array di
  // JobLog, e fa lo stesso per /sync-jobs/{id} per le metadata.
  if (!props.jobId) return null
  const [logsR, jobR] = await Promise.all([
    apiClient.get<any[]>(`/sync-jobs/${props.jobId}/logs?limit=1`),
    apiClient.get<any>(`/sync-jobs/${props.jobId}`).catch(() => ({ data: {} })),
  ])
  const logs = logsR.data || []
  const last = logs[0] || null
  const job = jobR.data || {}
  const output = (last?.output || '').replace(/\r/g, '\n')
  const lines = output.split('\n').filter((l: string) => l.trim()).slice(-400)
  return {
    id: Number(props.jobId) || 0,
    name: job.name || '',
    is_running: (job.last_status || '').toLowerCase() === 'running',
    current_status: job.current_status || job.last_status || null,
    last_status: job.last_status || null,
    last_run: job.last_run || null,
    last_duration: job.last_duration ?? null,
    last_transferred: job.last_transferred ?? null,
    run_count: job.run_count ?? 0,
    error_count: job.error_count ?? 0,
    log: last
      ? {
          id: last.id,
          status: last.status,
          started_at: last.started_at,
          completed_at: last.completed_at,
          message: last.message,
          duration: last.duration,
          transferred: last.transferred,
          error: last.error,
          output_tail: lines,
        }
      : null,
  }
}

async function fetchProgress() {
  if (!props.jobId) return
  loading.value = !progress.value
  try {
    const r = await apiClient.get<ProgressPayload>(`/sync-jobs/${props.jobId}/progress?tail=400`)
    progress.value = r.data
    fetchError.value = null
    fatalError.value = false
    lastFetchedAt.value = Date.now()
    if (autoScroll.value) {
      nextTick(() => {
        if (outputRef.value) outputRef.value.scrollTop = outputRef.value.scrollHeight
      })
    }
  } catch (e: any) {
    const status = e?.response?.status
    // Su 404 di /progress proviamo il fallback al vecchio endpoint
    // /sync-jobs/{id}/logs (esistente da sempre). Cosi' il viewer
    // funziona anche se il backend non e' stato riavviato dopo l'update.
    if (status === 404 || status === 405) {
      try {
        const fallback = await fetchViaLegacyLogs()
        if (fallback) {
          progress.value = fallback
          fetchError.value = null
          fatalError.value = false
          lastFetchedAt.value = Date.now()
          if (autoScroll.value) {
            nextTick(() => {
              if (outputRef.value) outputRef.value.scrollTop = outputRef.value.scrollHeight
            })
          }
          if (!toastShown) {
            toast.warning(
              'Modalità log compatibile',
              "Il backend non espone /progress; uso l'endpoint legacy /logs (no aggiornamento live)."
            )
            toastShown = true
          }
          // Polling lento — il legacy non aggiorna in tempo reale.
          if (poller) {
            window.clearInterval(poller)
            poller = window.setInterval(fetchProgress, 5000)
          }
          return
        }
      } catch (e2: any) {
        // anche il fallback fallisce → fatale
      }
      fetchError.value = errorMessage(e)
      fatalError.value = true
      stopPolling()
      if (!toastShown) {
        toast.error('Impossibile leggere il log', errorMessage(e))
        toastShown = true
      }
      return
    }
    fetchError.value = errorMessage(e)
    if (!toastShown) {
      toast.error('Impossibile leggere il log', errorMessage(e))
      toastShown = true
    }
  } finally {
    loading.value = false
  }
}

function startPolling() {
  stopPolling()
  toastShown = false
  fetchError.value = null
  fatalError.value = false
  // Inizializza lastFetchedAt al mount per evitare di mostrare
  // "1.7 miliardi di secondi fa" nel piedino prima della prima
  // risposta.
  lastFetchedAt.value = Date.now()
  fetchProgress()
  poller = window.setInterval(fetchProgress, props.pollMs)
  secTicker = window.setInterval(() => {
    secondsAgo.value = Math.max(0, Math.floor((Date.now() - lastFetchedAt.value) / 1000))
  }, 1000)
}

function stopPolling() {
  if (poller) {
    window.clearInterval(poller)
    poller = null
  }
  if (secTicker) {
    window.clearInterval(secTicker)
    secTicker = null
  }
}

watch(
  () => [props.visible, props.jobId],
  ([vis]) => {
    if (vis) {
      // output è computed da progress → azzerando progress si azzera anche
      // l'output del job precedente (rimossa la vecchia riga no-op `output.value`).
      progress.value = null
      startPolling()
    } else {
      stopPolling()
    }
  },
  { immediate: true }
)
onUnmounted(stopPolling)

function close() {
  emit('update:visible', false)
}

function onKeydown(e: KeyboardEvent) {
  if (!props.visible) return
  if (e.key === 'Escape') {
    e.preventDefault()
    close()
  }
}
import { onMounted as _onM, onUnmounted as _onU } from 'vue'
_onM(() => window.addEventListener('keydown', onKeydown))
_onU(() => window.removeEventListener('keydown', onKeydown))

async function copyOutput() {
  try {
    await navigator.clipboard.writeText(output.value.join('\n'))
    toast.success('Log copiato negli appunti')
  } catch (e) {
    toast.error('Impossibile copiare', errorMessage(e))
  }
}

function formatTime(iso: string) {
  try {
    return new Date(iso).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'medium' })
  } catch {
    return iso
  }
}
</script>

<style scoped>
.jlv-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  z-index: 1100;
  display: flex;
  align-items: center;
  justify-content: center;
}
.jlv-modal {
  width: min(960px, 96vw);
  max-height: 92vh;
  display: flex;
  flex-direction: column;
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-lg);
}
.jlv-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-bg-body);
}
.jlv-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 1rem;
  color: var(--color-text-primary);
}
.jlv-subtitle {
  font-weight: 500;
  color: var(--color-text-secondary);
  margin-left: 4px;
}
.jlv-meta {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: center;
  font-size: 0.78rem;
  color: var(--color-text-secondary);
}
.jlv-meta-item {
  font-family: var(--font-mono);
}
.jlv-head-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.jlv-follow {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.78rem;
  color: var(--color-text-secondary);
  user-select: none;
}
.btn-icon {
  background: transparent;
  border: 0;
  color: var(--color-text-secondary);
  cursor: pointer;
  padding: 4px;
  border-radius: var(--radius-sm);
}
.btn-icon:hover {
  color: var(--color-text-primary);
  background: var(--color-bg-hover);
}

.jlv-progress-wrap {
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-bg-body);
}
.jlv-progress-top {
  display: flex;
  justify-content: space-between;
  font-size: 0.78rem;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
}
.jlv-progress-pct {
  font-family: var(--font-mono);
  color: var(--color-text-primary);
  font-weight: 600;
}
.jlv-progress-bar {
  height: 8px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 999px;
  overflow: hidden;
}
.jlv-progress-fill {
  height: 100%;
  background: var(--color-info, #3b82f6);
  border-radius: 999px;
  transition: width 0.4s ease;
}
.jlv-progress-sub {
  margin-top: 6px;
  font-size: 0.75rem;
  font-family: var(--font-mono);
  color: var(--color-text-secondary);
}

.jlv-output {
  flex: 1;
  overflow-y: auto;
  background: #0b0e13;
  padding: var(--space-3);
  font-family: var(--font-mono);
  font-size: 0.78rem;
  line-height: 1.45;
  color: #cdd6f4;
}
.jlv-output pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}
.jlv-line { display: block; }

.jlv-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-2) var(--space-4);
  border-top: 1px solid var(--color-border);
  background: var(--color-bg-body);
  font-size: 0.78rem;
  color: var(--color-text-secondary);
}
.jlv-error {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--color-danger-fg);
}
.jlv-pulse {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--color-warning-fg);
}

.jlv-fatal {
  padding: var(--space-5);
  text-align: center;
  color: var(--color-text-secondary);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  height: 100%;
  justify-content: center;
}
.jlv-fatal :deep(svg) {
  color: var(--color-warning-fg);
}
.jlv-fatal h3 {
  margin: var(--space-2) 0 0;
  color: var(--color-text-primary);
  font-size: 1rem;
}
.jlv-fatal p {
  margin: 0;
  max-width: 540px;
  font-size: 0.85rem;
  line-height: 1.5;
}
.jlv-fatal code {
  font-family: var(--font-mono);
  background: var(--color-bg-element);
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  color: var(--color-text-primary);
  font-size: 0.78rem;
}
.jlv-fatal-hint {
  font-size: 0.78rem !important;
  color: var(--color-text-secondary);
}
.jlv-fatal-detail {
  margin-top: var(--space-2) !important;
  padding: var(--space-2) var(--space-3);
  font-family: var(--font-mono);
  font-size: 0.74rem !important;
  color: var(--color-danger-fg);
  background: var(--color-danger-dim);
  border-radius: var(--radius-sm);
  max-width: 600px;
}
.jlv-pulse .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  animation: pulse 1.4s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
</style>
