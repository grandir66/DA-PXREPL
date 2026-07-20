<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import NasSyncEndpointForm from '../components/nas-sync/NasSyncEndpointForm.vue'
import NasSyncJobModal from '../components/nas-sync/NasSyncJobModal.vue'
import NasSyncLogModal from '../components/nas-sync/NasSyncLogModal.vue'
import FileReplPathMapping from '../components/file-replication/FileReplPathMapping.vue'
import { fileEndpointsApi, type FileEndpoint } from '../services/fileEndpoints'
import { nasSyncApi, type NasSyncJob } from '../services/nasSync'
import type { EndpointCapabilities } from '../services/nasSync'
import {
  formatFileReplProgress,
  type FileReplProgress,
} from '../utils/fileReplProgress'

const jobs = ref<NasSyncJob[]>([])
const endpoints = ref<FileEndpoint[]>([])
const endpointCaps = ref<Record<number, EndpointCapabilities>>({})
const stats = ref({ total: 0, active: 0, running: 0, failed: 0 })
const showJobModal = ref(false)
const editingJob = ref<NasSyncJob | null>(null)
const showLogModal = ref(false)
const logJob = ref<NasSyncJob | null>(null)
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

async function loadCapabilities() {
  await Promise.all(
    endpoints.value.map(async (ep) => {
      try {
        const { data } = await nasSyncApi.capabilities(ep.id)
        endpointCaps.value[ep.id] = data
      } catch { /* ignore */ }
    }),
  )
}

async function refresh(silent = false) {
  if (!silent) loading.value = true
  try {
    const [j, e, s] = await Promise.all([
      nasSyncApi.list(),
      fileEndpointsApi.list(),
      nasSyncApi.stats(),
    ])
    jobs.value = j.data
    endpoints.value = e.data
    stats.value = s.data
  } finally {
    if (!silent) loading.value = false
  }
  await loadCapabilities()
}

function jobIsRunning(job: NasSyncJob) {
  return job.current_status === 'running'
}

async function refreshProgressForRunning() {
  const running = jobs.value.filter((j) => jobIsRunning(j))
  await Promise.all(
    running.map(async (j) => {
      try {
        const { data } = await nasSyncApi.progress(j.id)
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

async function runJob(job: NasSyncJob) {
  runError.value = ''
  try {
    await nasSyncApi.run(job.id)
    logJob.value = job
    showLogModal.value = true
    await refresh()
    startLivePoll()
    for (let i = 0; i < 90; i++) {
      await new Promise((r) => setTimeout(r, 2000))
      const { data } = await nasSyncApi.progress(job.id)
      if (data.status !== 'running') break
      await refresh()
    }
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
          : 'Avvio job fallito'
    runError.value = msg
  }
}

function openJobLogs(job: NasSyncJob) {
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
  await nasSyncApi.toggle(id)
  await refresh()
}

async function deleteJob(id: number) {
  if (!confirm('Eliminare il job?')) return
  await nasSyncApi.delete(id)
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

function openEditJob(job: NasSyncJob) {
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
        <h1>Repliche dati</h1>
        <p class="repl-sub">
          Replica cartelle NAS→NAS: motore diretto rsync (i dati non passano dal server dapx)
          o rclone SMB come fallback. Sorgenti Synology, QNAP, Linux, Windows; destinazioni QNAP e Synology.
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

    <NasSyncEndpointForm
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
              <th>Capacità</th>
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
              <td class="caps-cell">
                <template v-if="endpointCaps[ep.id]">
                  <span class="badge" :class="endpointCaps[ep.id].rsync_source ? 'badge-ok' : 'badge-off'">SSH</span>
                  <span class="badge" :class="endpointCaps[ep.id].rsync_dest ? 'badge-ok' : 'badge-off'">rsync</span>
                  <span class="badge" :class="endpointCaps[ep.id].smb ? 'badge-ok' : 'badge-off'">SMB</span>
                </template>
                <span v-else class="muted">—</span>
              </td>
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
                <span class="engine-chip" :class="job.resolved_engine === 'direct_rsync' ? 'engine-direct' : 'engine-rclone'">
                  {{ job.resolved_engine === 'direct_rsync' ? 'rsync diretto' : 'rclone SMB' }}
                </span>
                <FileReplPathMapping
                  compact
                  :max-rows="2"
                  :source-paths="job.source_paths || []"
                  :dest-share-path="job.dest_base_path"
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

    <NasSyncLogModal
      v-if="showLogModal && logJob"
      :job-id="logJob.id"
      :job-name="logJob.name"
      :job="logJob"
      @close="closeLogModal"
    />

    <NasSyncJobModal
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
.engine-chip { display: inline-block; font-size: .7rem; padding: 1px 8px; border-radius: 10px; margin-bottom: 4px; }
.engine-direct { background: rgba(46, 204, 113, .15); color: #2ecc71; }
.engine-rclone { background: rgba(241, 196, 15, .15); color: #f1c40f; }
.caps-cell .badge { margin-right: 4px; font-size: .7rem; }
.badge-ok { background: rgba(46, 204, 113, .18); color: #2ecc71; }
.badge-off { background: rgba(255,255,255,.06); opacity: .55; }
</style>
