<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import FileEndpointForm from '../components/file-replication/FileEndpointForm.vue'
import FileReplJobModal from '../components/file-replication/FileReplJobModal.vue'
import FileReplLogModal from '../components/file-replication/FileReplLogModal.vue'
import FileReplPathMapping from '../components/file-replication/FileReplPathMapping.vue'
import { fileEndpointsApi, type FileEndpoint } from '../services/fileEndpoints'
import { fileReplicationApi, type FileReplicationJob } from '../services/fileReplication'
import {
  formatFileReplProgress,
  type FileReplProgress,
} from '../utils/fileReplProgress'

const jobs = ref<FileReplicationJob[]>([])
const endpoints = ref<FileEndpoint[]>([])
const stats = ref({ total: 0, active: 0, running: 0, failed: 0 })
const showJobModal = ref(false)
const editingJob = ref<FileReplicationJob | null>(null)
const showLogModal = ref(false)
const logJob = ref<FileReplicationJob | null>(null)
const runError = ref('')
const showEndpointForm = ref(false)
const editingEndpoint = ref<FileEndpoint | null>(null)
const endpointError = ref('')
const loading = ref(false)
const progressByJob = ref<Record<number, FileReplProgress>>({})
let pollTimer: ReturnType<typeof setInterval> | null = null

const activeCount = computed(() => stats.value.active)
const runningCount = computed(() => stats.value.running)
const failedCount = computed(() => stats.value.failed)

async function refresh(silent = false) {
  if (!silent) loading.value = true
  try {
    const [j, e, s] = await Promise.all([
      fileReplicationApi.list(),
      fileEndpointsApi.list(),
      fileReplicationApi.stats(),
    ])
    jobs.value = j.data
    endpoints.value = e.data
    stats.value = s.data
  } finally {
    if (!silent) loading.value = false
  }
}

function jobIsRunning(job: FileReplicationJob) {
  return job.current_status === 'running'
}

async function refreshProgressForRunning() {
  const running = jobs.value.filter((j) => jobIsRunning(j))
  await Promise.all(
    running.map(async (j) => {
      try {
        const { data } = await fileReplicationApi.progress(j.id)
        if (data.status === 'running') {
          progressByJob.value[j.id] = data as FileReplProgress
        } else {
          delete progressByJob.value[j.id]
        }
      } catch {
        /* ignore transient progress errors */
      }
    }),
  )
}

function progressLabel(jobId: number) {
  return formatFileReplProgress(progressByJob.value[jobId])
}

function startLivePoll() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    await refresh(true)
    await refreshProgressForRunning()
    const anyRunning =
      stats.value.running > 0 || jobs.value.some((j) => jobIsRunning(j))
    if (!anyRunning) stopLivePoll()
  }, 3000)
}

function stopLivePoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function runJob(job: FileReplicationJob) {
  runError.value = ''
  try {
    await fileReplicationApi.run(job.id)
    logJob.value = job
    showLogModal.value = true
    await refresh()
    // P-10: un solo meccanismo di poll (startLivePoll a 3s che si ferma da solo
    // quando nessun job è più in esecuzione). Rimosso il loop 2s×90 parallelo
    // che raddoppiava richieste e refresh.
    startLivePoll()
  } catch (e: unknown) {
    const msg =
      typeof e === 'object' &&
      e !== null &&
      'response' in e &&
      typeof (e as { response?: { data?: { detail?: string } } }).response?.data?.detail === 'string'
        ? (e as { response: { data: { detail: string } } }).response.data.detail
        : e instanceof Error
          ? e.message
          : 'Avvio job fallito'
    runError.value = msg
  }
}

function openJobLogs(job: FileReplicationJob) {
  logJob.value = job
  showLogModal.value = true
  if (jobIsRunning(job)) {
    void refreshProgressForRunning()
    startLivePoll()
  }
}

function closeLogModal() {
  showLogModal.value = false
  logJob.value = null
}

async function toggleJob(id: number) {
  await fileReplicationApi.toggle(id)
  await refresh()
}

async function deleteJob(id: number) {
  if (!confirm('Eliminare il job?')) return
  await fileReplicationApi.delete(id)
  await refresh()
}

function onJobSaved() {
  showJobModal.value = false
  editingJob.value = null
  refresh()
}

function openNewJob() {
  editingJob.value = null
  showJobModal.value = true
}

function openEditJob(job: FileReplicationJob) {
  editingJob.value = job
  showJobModal.value = true
}

function closeJobModal() {
  showJobModal.value = false
  editingJob.value = null
}

function openNewEndpoint() {
  editingEndpoint.value = null
  showEndpointForm.value = true
  endpointError.value = ''
}

function openEditEndpoint(ep: FileEndpoint) {
  editingEndpoint.value = ep
  showEndpointForm.value = true
  endpointError.value = ''
}

function closeEndpointForm() {
  showEndpointForm.value = false
  editingEndpoint.value = null
  endpointError.value = ''
}

async function testEndpoint(id: number) {
  endpointError.value = ''
  try {
    const { data } = await fileEndpointsApi.test(id)
    await refresh()
    alert(data.success ? `OK: ${data.message}` : `Fallito: ${data.message}`)
  } catch (e: unknown) {
    endpointError.value = e instanceof Error ? e.message : 'Test fallito'
  }
}

async function deleteEndpoint(ep: FileEndpoint) {
  if (!confirm(`Eliminare l'endpoint "${ep.name || ep.host}"?`)) return
  endpointError.value = ''
  try {
    await fileEndpointsApi.delete(ep.id)
    if (editingEndpoint.value?.id === ep.id) closeEndpointForm()
    await refresh()
  } catch (e: unknown) {
    const msg =
      typeof e === 'object' &&
      e !== null &&
      'response' in e &&
      typeof (e as { response?: { data?: { detail?: string } } }).response?.data?.detail === 'string'
        ? (e as { response: { data: { detail: string } } }).response.data.detail
        : e instanceof Error
          ? e.message
          : 'Eliminazione fallita'
    endpointError.value = msg
  }
}

function onEndpointSaved() {
  closeEndpointForm()
  refresh()
}

function formatDate(v?: string | null) {
  if (!v) return '—'
  return new Date(v).toLocaleString()
}

function formatBytes(n?: number | null) {
  if (!n) return ''
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

onMounted(async () => {
  await refresh()
  if (stats.value.running > 0 || jobs.value.some((j) => jobIsRunning(j))) {
    await refreshProgressForRunning()
    startLivePoll()
  }
})

onUnmounted(stopLivePoll)
</script>

<template>
  <div class="repl-view">
    <header class="repl-head">
      <div class="repl-head-left">
        <h1>Replica file → QNAP WORM</h1>
        <p class="repl-sub">
          Sync monodirezionale da Synology, QNAP, Linux o Windows verso share staging QuTS hero h6.0.
          Immutabilità via snapshot nativi QNAP.
        </p>
      </div>
      <div class="repl-head-actions">
        <button class="btn btn-secondary mr-2" @click="openNewEndpoint">
          + Endpoint
        </button>
        <button class="btn btn-primary" @click="openNewJob">+ Nuovo job</button>
      </div>
    </header>

    <section class="repl-stats">
      <div class="repl-stat">
        <span class="repl-stat-label">Job totali</span>
        <span class="repl-stat-val">{{ stats.total }}</span>
      </div>
      <div class="repl-stat">
        <span class="repl-stat-label">Attivi</span>
        <span class="repl-stat-val text-success">{{ activeCount }}</span>
      </div>
      <div class="repl-stat">
        <span class="repl-stat-label">In esecuzione</span>
        <span class="repl-stat-val text-warning">{{ runningCount }}</span>
      </div>
      <div class="repl-stat">
        <span class="repl-stat-label">Falliti</span>
        <span class="repl-stat-val text-danger">{{ failedCount }}</span>
      </div>
    </section>

    <FileEndpointForm
      v-if="showEndpointForm"
      :endpoint="editingEndpoint"
      @saved="onEndpointSaved"
      @cancel="closeEndpointForm"
    />

    <div class="card mb-4">
      <div class="card-header">
        <h3>Endpoint registrati ({{ endpoints.length }})</h3>
        <button class="btn btn-sm btn-secondary" :disabled="loading" @click="refresh">Aggiorna</button>
      </div>
      <div class="card-body p-0">
        <p v-if="endpointError" class="p-3 text-danger">{{ endpointError }}</p>
        <table class="data-table" v-if="endpoints.length">
          <thead>
            <tr>
              <th>Nome</th>
              <th>Tipo</th>
              <th>Ruolo</th>
              <th>Host</th>
              <th>Ultimo test</th>
              <th>Azioni</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="ep in endpoints" :key="ep.id">
              <td><strong>{{ ep.name || '—' }}</strong></td>
              <td><span class="badge">{{ ep.endpoint_type }}</span></td>
              <td>{{ ep.role }}</td>
              <td><code>{{ ep.host }}:{{ ep.port }}</code></td>
              <td>
                <span
                  v-if="ep.last_test_status"
                  :class="ep.last_test_status === 'success' ? 'text-success' : 'text-danger'"
                  :title="ep.last_test_message || ''"
                >
                  {{ ep.last_test_status }}
                </span>
                <small v-if="ep.last_test_message" class="muted d-block">{{ ep.last_test_message }}</small>
                <span v-else-if="!ep.last_test_status" class="muted">—</span>
              </td>
              <td class="actions">
                <button class="btn btn-sm btn-secondary" @click="openEditEndpoint(ep)">Modifica</button>
                <button class="btn btn-sm btn-primary" @click="testEndpoint(ep.id)">Test</button>
                <button class="btn btn-sm btn-danger" @click="deleteEndpoint(ep)">Elimina</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="p-4">Nessun endpoint. Clicca <strong>+ Endpoint</strong> per registrarne uno.</p>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <h3>Job configurati</h3>
        <button class="btn btn-sm btn-secondary" :disabled="loading" @click="refresh">Aggiorna</button>
      </div>
      <div class="card-body p-0">
        <p v-if="runError" class="p-3 text-danger">{{ runError }}</p>
        <table class="data-table" v-if="jobs.length">
          <thead>
            <tr>
              <th>Nome</th>
              <th>Replica</th>
              <th>Schedule</th>
              <th>Ultimo run</th>
              <th>Stato</th>
              <th>Azioni</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="job in jobs" :key="job.id">
              <td>{{ job.name }}</td>
              <td class="fr-job-structure">
                <FileReplPathMapping
                  compact
                  :max-rows="2"
                  :source-paths="job.source_paths || []"
                  :dest-share-path="job.dest_staging_path"
                  :source-label="job.source_endpoint_name"
                  :dest-label="job.dest_endpoint_name"
                />
              </td>
              <td><code>{{ job.schedule || 'manuale' }}</code></td>
              <td>
                {{ formatDate(job.last_run_at) }}
                <small v-if="job.last_run_duration_sec" class="muted d-block">
                  {{ job.last_run_duration_sec }}s
                  <span v-if="job.last_bytes_transferred"> · {{ formatBytes(job.last_bytes_transferred) }}</span>
                </small>
              </td>
              <td>
                <span
                  :class="
                    jobIsRunning(job)
                      ? 'text-warning'
                      : job.current_status === 'failed' || job.last_run_status === 'failed'
                        ? 'text-danger'
                        : job.last_run_status === 'success'
                          ? 'text-success'
                          : ''
                  "
                >
                  {{ jobIsRunning(job) ? 'running' : job.current_status || job.last_run_status || 'idle' }}
                </span>
                <small v-if="jobIsRunning(job) && progressLabel(job.id)" class="muted d-block">
                  {{ progressLabel(job.id) }}
                </small>
                <small v-if="job.last_run_error" class="muted d-block text-danger" :title="job.last_run_error">
                  {{ job.last_run_error.length > 120 ? job.last_run_error.slice(0, 120) + '…' : job.last_run_error }}
                </small>
              </td>
              <td class="actions">
                <button class="btn btn-sm btn-secondary" @click="openEditJob(job)">Modifica</button>
                <button class="btn btn-sm btn-secondary" @click="openJobLogs(job)">Log</button>
                <button class="btn btn-sm btn-primary" @click="runJob(job)">Run</button>
                <button class="btn btn-sm btn-secondary" @click="toggleJob(job.id)">
                  {{ job.is_active ? 'Off' : 'On' }}
                </button>
                <button class="btn btn-sm btn-danger" @click="deleteJob(job.id)">Del</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="p-4">Nessun job. Crea un endpoint e un job per iniziare.</p>
      </div>
    </div>

    <FileReplLogModal
      v-if="showLogModal && logJob"
      :job-id="logJob.id"
      :job-name="logJob.name"
      :job="logJob"
      @close="closeLogModal"
    />

    <FileReplJobModal
      v-if="showJobModal"
      :job="editingJob"
      @close="closeJobModal"
      @saved="onJobSaved"
    />
  </div>
</template>

<style scoped>
.repl-view { padding: 0; }
.repl-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; gap: 16px; }
.repl-sub { opacity: 0.75; margin-top: 4px; max-width: 640px; }
.repl-stats { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
.repl-stat { background: var(--bg-secondary, #1a1a2e); padding: 12px 20px; border-radius: 8px; min-width: 120px; }
.repl-stat-label { display: block; font-size: 0.75rem; opacity: 0.7; }
.repl-stat-val { font-size: 1.5rem; font-weight: 700; }
.actions { display: flex; gap: 6px; flex-wrap: wrap; }
.fr-job-structure { min-width: 240px; max-width: 380px; vertical-align: top; }
.badge { font-size: 0.75rem; background: #333; padding: 2px 8px; border-radius: 4px; }
.muted { opacity: 0.65; font-size: 0.85rem; }
.d-block { display: block; margin-top: 2px; max-width: 280px; }
.mr-2 { margin-right: 8px; }
.mt-4 { margin-top: 16px; }
.p-4 { padding: 16px; }
</style>
