<template>
  <div v-if="visible" class="jlv-overlay" @click.self="close">
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

      <div class="jlv-output" ref="outputRef">
        <pre v-if="output.length"><span
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
        <LoadingState v-if="loading && !output.length" message="Caricamento log…" />
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
          <span v-if="progress?.is_running" class="jlv-pulse">
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
    pollMs: 1500,
  }
)
const emit = defineEmits<{ (e: 'update:visible', v: boolean): void }>()
const toast = useToast()

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

let poller: number | null = null
let secTicker: number | null = null

const output = computed(() => progress.value?.log?.output_tail || [])
const hasOutput = computed(() => output.value.length > 0)

const statusLabel = computed(() => {
  if (progress.value?.is_running) return 'in esecuzione'
  const s = (progress.value?.current_status || progress.value?.last_status || 'idle').toLowerCase()
  return ({
    success: 'successo',
    failed: 'fallito',
    running: 'in esecuzione',
    idle: 'in attesa',
  } as Record<string, string>)[s] || s
})
const statusTone = computed<'success' | 'danger' | 'warning' | 'info' | 'neutral'>(() => {
  if (progress.value?.is_running) return 'warning'
  const s = (progress.value?.current_status || progress.value?.last_status || '').toLowerCase()
  if (s === 'success') return 'success'
  if (s === 'failed' || s === 'error') return 'danger'
  return 'neutral'
})

async function fetchProgress() {
  if (!props.jobId) return
  loading.value = !progress.value
  try {
    const r = await apiClient.get<ProgressPayload>(`/sync-jobs/${props.jobId}/progress?tail=400`)
    progress.value = r.data
    lastFetchedAt.value = Date.now()
    if (autoScroll.value) {
      nextTick(() => {
        if (outputRef.value) outputRef.value.scrollTop = outputRef.value.scrollHeight
      })
    }
  } catch (e: any) {
    toast.error('Impossibile leggere il log', errorMessage(e))
  } finally {
    loading.value = false
  }
}

function startPolling() {
  stopPolling()
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
      progress.value = null
      output.value
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
