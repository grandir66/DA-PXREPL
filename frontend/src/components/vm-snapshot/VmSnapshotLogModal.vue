<script setup lang="ts">
import axios from 'axios'
import { onMounted, ref } from 'vue'
import { vmSnapshotsApi, type VmSnapshotJob } from '../../services/vmSnapshots'

interface LogEntry {
  id: number
  status: string
  message?: string | null
  output?: string | null
  error?: string | null
  duration?: number | null
  created_at?: string | null
  completed_at?: string | null
}

const props = defineProps<{ job: VmSnapshotJob }>()
const emit = defineEmits<{ close: [] }>()

const logs = ref<LogEntry[]>([])
const loading = ref(false)
const errorMsg = ref('')
const expanded = ref<number | null>(null)

function fmtDate(value?: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleString('it-IT')
}

function statusClass(status: string) {
  if (status === 'success') return 'text-success'
  if (status === 'warning') return 'text-warning'
  if (status === 'failed') return 'text-danger'
  return ''
}

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    const { data } = await vmSnapshotsApi.logs(props.job.id)
    logs.value = data
    const first = logs.value[0]
    if (first) expanded.value = first.id
  } catch (e: unknown) {
    errorMsg.value = axios.isAxiosError(e)
      ? String(e.response?.data?.detail || e.message)
      : 'Errore caricamento log'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal-card">
      <header class="modal-head">
        <h2>Log — {{ job.name }}</h2>
        <button type="button" class="btn btn-sm" @click="emit('close')">✕</button>
      </header>
      <div class="modal-body">
        <p v-if="errorMsg" class="text-danger">{{ errorMsg }}</p>
        <p v-else-if="loading" class="text-muted">Caricamento…</p>
        <p v-else-if="!logs.length" class="text-muted">Nessuna esecuzione registrata.</p>
        <div v-for="log in logs" :key="log.id" class="log-entry">
          <button type="button" class="log-head" @click="expanded = expanded === log.id ? null : log.id">
            <span :class="statusClass(log.status)">●</span>
            <span>{{ fmtDate(log.created_at) }}</span>
            <span class="log-msg">{{ log.message }}</span>
            <span v-if="log.duration" class="text-muted">{{ log.duration }}s</span>
          </button>
          <div v-if="expanded === log.id" class="log-detail">
            <p v-if="log.error" class="text-danger">{{ log.error }}</p>
            <pre v-if="log.output">{{ log.output }}</pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.55);
  display: flex; align-items: center; justify-content: center; z-index: 1000;
}
.modal-card {
  background: var(--bg-primary, #111); border-radius: 12px;
  width: min(820px, 96vw); max-height: 90vh; overflow: auto;
}
.modal-head { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; }
.modal-body { padding: 0 20px 20px; }
.log-entry { border-bottom: 1px solid var(--border-color, #333); }
.log-head {
  display: flex; gap: 10px; align-items: center; width: 100%;
  background: none; border: none; color: inherit; cursor: pointer;
  padding: 10px 0; text-align: left; font-size: .875rem;
}
.log-msg { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.log-detail pre {
  background: rgba(255,255,255,.04); border-radius: 8px; padding: 10px 12px;
  font-size: .78rem; overflow-x: auto; white-space: pre-wrap; margin: 0 0 10px;
}
.text-muted { opacity: .75; font-size: .85rem; }
.text-warning { color: #f1c40f; }
</style>
