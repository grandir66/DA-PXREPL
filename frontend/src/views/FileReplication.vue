<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import FileEndpointForm from '../components/file-replication/FileEndpointForm.vue'
import FileReplJobModal from '../components/file-replication/FileReplJobModal.vue'
import FileReplLogModal from '../components/file-replication/FileReplLogModal.vue'
import FileReplPathMapping from '../components/file-replication/FileReplPathMapping.vue'
import FileReplFolderCatalog from '../components/file-replication/FileReplFolderCatalog.vue'
import { fileEndpointsApi, type FileEndpoint } from '../services/fileEndpoints'
import { fileReplicationApi, type FileReplicationJob } from '../services/fileReplication'
import {
  formatFileReplProgress,
  type FileReplProgress,
} from '../utils/fileReplProgress'

const jobs = ref<FileReplicationJob[]>([])
const endpoints = ref<FileEndpoint[]>([])
const stats = ref({ total: 0, active: 0, running: 0, paused: 0, failed: 0 })
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
const pausedCount = computed(() => stats.value.paused)
const failedCount = computed(() => stats.value.failed)

function jobIsPaused(job: FileReplicationJob) {
  return job.current_status === 'paused' || job.last_run_status === 'paused'
}

function syncLogJobFromList() {
  if (!logJob.value) return
  const updated = jobs.value.find((j) => j.id === logJob.value!.id)
  if (updated) logJob.value = updated
}

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
    syncLogJobFromList()
  } finally {
    if (!silent) loading.value = false
  }
}

function jobIsRunning(job: FileReplicationJob) {
  if (job.current_status === 'running') return true
  const prog = progressByJob.value[job.id]
  return prog?.status === 'running' || prog?.status === 'cancelling'
}

function jobIsCatalogRefreshing(job: FileReplicationJob) {
  return progressByJob.value[job.id]?.status === 'catalog_refresh'
}

function jobIsBusy(job: FileReplicationJob) {
  return jobIsRunning(job) || jobIsCatalogRefreshing(job)
}

async function refreshProgressForRunning() {
  const toPoll = jobs.value.filter(
    (j) =>
      j.current_status === 'running' ||
      progressByJob.value[j.id]?.status === 'running' ||
      progressByJob.value[j.id]?.status === 'cancelling' ||
      progressByJob.value[j.id]?.status === 'catalog_refresh',
  )
  await Promise.all(
    toPoll.map(async (j) => {
      try {
        const { data } = await fileReplicationApi.progress(j.id)
        const status = data.status as string | undefined
        if (status === 'running' || status === 'cancelling' || status === 'catalog_refresh') {
          progressByJob.value[j.id] = data as FileReplProgress
        } else if (status === 'success' || status === 'failed' || status === 'cancelled') {
          if (progressByJob.value[j.id]?.status === 'catalog_refresh') {
            await refresh(true)
          }
          delete progressByJob.value[j.id]
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
      stats.value.running > 0 ||
      jobs.value.some((j) => jobIsRunning(j) || jobIsCatalogRefreshing(j)) ||
      Object.values(progressByJob.value).some(
        (p) =>
          p?.status === 'running' ||
          p?.status === 'cancelling' ||
          p?.status === 'catalog_refresh',
      )
    if (!anyRunning) stopLivePoll()
  }, 3000)
}

function stopLivePoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function stopJob(job: FileReplicationJob) {
  runError.value = ''
  if (!confirm(`Mettere in pausa il job "${job.name}"? Il checkpoint permette di riprendere dalla cartella corrente.`)) return
  try {
    await fileReplicationApi.stop(job.id)
    await refresh()
    await refreshProgressForRunning()
  } catch (e: unknown) {
    const msg =
      typeof e === 'object' &&
      e !== null &&
      'response' in e &&
      typeof (e as { response?: { data?: { detail?: string } } }).response?.data?.detail === 'string'
        ? (e as { response: { data: { detail: string } } }).response.data.detail
        : e instanceof Error
          ? e.message
          : 'Stop job fallito'
    runError.value = msg
  }
}

async function refreshCatalogJob(job: FileReplicationJob) {
  runError.value = ''
  if (
    !confirm(
      `Aggiornare catalogo du per "${job.name}"?\n\nScansione SSH Synology (1° livello) per dimensioni cartelle e rilevamento nuove directory. Non avvia la copia.`,
    )
  ) {
    return
  }
  try {
    await fileReplicationApi.refreshCatalog(job.id)
    progressByJob.value[job.id] = {
      status: 'catalog_refresh',
      phase_label: 'Catalogo du Synology',
      message: 'Avvio…',
    }
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
          : 'Aggiornamento catalogo fallito'
    runError.value = msg
  }
}

async function runJob(job: FileReplicationJob, fresh = false) {
  runError.value = ''
  if (
    !fresh &&
    jobIsPaused(job) &&
    !confirm(`Riprendere il job "${job.name}" da ${job.resume_from_path || 'checkpoint salvato'}?`)
  ) {
    return
  }
  if (fresh && !confirm(`Ricominciare "${job.name}" da capo (ignora checkpoint)?`)) return
  try {
    await fileReplicationApi.run(job.id, fresh)
    progressByJob.value[job.id] = { status: 'running', message: 'Avvio…' }
    const idx = jobs.value.findIndex((j) => j.id === job.id)
    if (idx >= 0) {
      jobs.value[idx] = { ...jobs.value[idx], current_status: 'running' }
    }
    logJob.value = { ...job, current_status: 'running' }
    showLogModal.value = true
    await refresh()
    startLivePoll()
    for (let i = 0; i < 90; i++) {
      await new Promise((r) => setTimeout(r, 2000))
      const { data } = await fileReplicationApi.progress(job.id)
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
        <span class="repl-stat-label">In pausa</span>
        <span class="repl-stat-val">{{ pausedCount }}</span>
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
        <div v-if="jobs.length" class="table-container fr-jobs-table">
        <table class="data-table">
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
              <td class="fr-status-cell">
                <span
                  class="fr-status-badge"
                  :class="
                    jobIsRunning(job)
                      ? 'fr-status-running'
                      : jobIsPaused(job)
                        ? 'fr-status-paused'
                        : job.current_status === 'failed' || job.last_run_status === 'failed'
                          ? 'fr-status-failed'
                          : job.last_run_status === 'success'
                            ? 'fr-status-success'
                            : 'fr-status-idle'
                  "
                >
                  {{
                    jobIsRunning(job)
                      ? 'in esecuzione'
                      : jobIsPaused(job)
                        ? 'in pausa'
                        : job.current_status || job.last_run_status || 'idle'
                  }}
                </span>
                <div v-if="jobIsRunning(job) || jobIsPaused(job)" class="fr-run-controls">
                  <button
                    v-if="jobIsRunning(job)"
                    class="btn btn-sm btn-warning"
                    title="Metti in pausa e salva checkpoint per riprendere dopo"
                    @click="stopJob(job)"
                  >
                    Pausa
                  </button>
                  <template v-else-if="jobIsPaused(job)">
                    <button class="btn btn-sm btn-primary" @click="runJob(job)">
                      Riprendi
                    </button>
                    <button
                      class="btn btn-sm btn-secondary"
                      title="Ignora checkpoint e ricomincia da capo"
                      @click="runJob(job, true)"
                    >
                      Da capo
                    </button>
                  </template>
                </div>
                <small v-if="job.catalog_has_du && job.catalog_bytes_est" class="muted d-block">
                  Catalogo du: {{ job.catalog_folder_count || '?' }} cartelle ·
                  {{ formatBytes(job.catalog_bytes_est) }}
                  <span v-if="job.catalog_du_at">
                    · {{ new Date(job.catalog_du_at).toLocaleString() }}
                  </span>
                </small>
                <small v-else-if="!jobIsCatalogRefreshing(job)" class="muted d-block text-warning">
                  Catalogo du assente — esegui «Catalogo du» prima della replica
                </small>
                <small
                  v-if="jobIsCatalogRefreshing(job)"
                  class="muted d-block"
                >
                  {{ progressByJob[job.id]?.message || 'Aggiornamento catalogo du…' }}
                </small>
                <FileReplFolderCatalog
                  v-if="jobIsCatalogRefreshing(job) && progressByJob[job.id]?.folder_catalog?.length"
                  compact
                  :folders="progressByJob[job.id]!.folder_catalog!"
                  :folders-done="0"
                />
                <small v-if="jobIsPaused(job) && job.resume_from_path" class="muted d-block">
                  Riprendi da {{ job.resume_from_path }}
                </small>
                <small v-if="jobIsRunning(job) && progressByJob[job.id]?.folder_activity_label" class="muted d-block">
                  {{ progressByJob[job.id]?.folder_activity_label }}
                </small>
                <FileReplFolderCatalog
                  v-if="jobIsRunning(job) && progressByJob[job.id]?.folder_catalog?.length"
                  compact
                  :folders="progressByJob[job.id]!.folder_catalog!"
                  :activity-label="progressByJob[job.id]?.folder_activity_label"
                  :current-name="progressByJob[job.id]?.current_folder_name"
                  :current-index="progressByJob[job.id]?.current_folder_index"
                  :current-total="progressByJob[job.id]?.current_folder_total"
                  :folders-done="progressByJob[job.id]?.folders_done"
                />
                <small v-if="jobIsRunning(job)" class="muted d-block">
                  {{ progressByJob[job.id]?.phase_label || progressLabel(job.id) }}
                </small>
                <small
                  v-if="jobIsRunning(job) && progressByJob[job.id]?.detail_lines?.[0]"
                  class="muted d-block fr-job-progress-sub"
                >
                  {{ progressByJob[job.id]?.detail_lines?.[0] }}
                </small>
                <small v-if="job.last_run_error" class="muted d-block text-danger" :title="job.last_run_error">
                  {{ job.last_run_error.length > 120 ? job.last_run_error.slice(0, 120) + '…' : job.last_run_error }}
                </small>
              </td>
              <td class="actions">
                <button
                  v-if="!jobIsBusy(job) && !jobIsPaused(job)"
                  class="btn btn-sm btn-primary"
                  @click="runJob(job)"
                >
                  Esegui
                </button>
                <button
                  class="btn btn-sm btn-secondary"
                  :disabled="jobIsBusy(job)"
                  title="Scansione du Synology per dimensioni cartelle e nuove directory"
                  @click="refreshCatalogJob(job)"
                >
                  {{ jobIsCatalogRefreshing(job) ? 'Catalogo…' : 'Catalogo du' }}
                </button>
                <button class="btn btn-sm btn-secondary" @click="openEditJob(job)">Modifica</button>
                <button class="btn btn-sm btn-secondary" @click="openJobLogs(job)">Log</button>
                <button class="btn btn-sm btn-secondary" @click="toggleJob(job.id)">
                  {{ job.is_active ? 'Off' : 'On' }}
                </button>
                <button class="btn btn-sm btn-danger" @click="deleteJob(job.id)">Del</button>
              </td>
            </tr>
          </tbody>
        </table>
        </div>
        <p v-else class="p-4">Nessun job. Crea un endpoint e un job per iniziare.</p>
      </div>
    </div>

    <FileReplLogModal
      v-if="showLogModal && logJob"
      :job-id="logJob.id"
      :job-name="logJob.name"
      :job="logJob"
      @close="closeLogModal"
      @pause="logJob && stopJob(logJob)"
      @resume="logJob && runJob(logJob)"
      @fresh="logJob && runJob(logJob, true)"
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
.actions { display: flex; gap: 6px; flex-wrap: wrap; min-width: 220px; }
.fr-jobs-table { overflow-x: auto; }
.fr-status-badge {
  display: inline-block;
  font-size: 0.8rem;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
  text-transform: lowercase;
}
.fr-status-running { background: rgba(240, 173, 78, 0.2); color: #f0ad4e; }
.fr-status-paused { background: rgba(13, 202, 240, 0.15); color: #5bc0de; }
.fr-status-failed { background: rgba(220, 53, 69, 0.15); color: #dc3545; }
.fr-status-success { background: rgba(40, 167, 69, 0.15); color: #28a745; }
.fr-status-idle { background: rgba(255, 255, 255, 0.06); color: inherit; opacity: 0.85; }
.fr-run-controls {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 8px;
}
.fr-status-cell { min-width: 280px; max-width: 420px; vertical-align: top; }
.text-warning { color: #f0ad4e; }
.fr-status-cell :deep(.frfc-compact) { margin-top: 8px; margin-bottom: 0; }
.btn-warning {
  background-color: #f0ad4e;
  color: #1a1a1a;
  border: 1px solid rgba(240, 173, 78, 0.5);
}
.btn-warning:hover:not(:disabled) {
  background-color: #ec971f;
}
.fr-job-structure { min-width: 240px; max-width: 380px; vertical-align: top; }
.fr-job-progress-sub { font-size: 0.8rem; opacity: 0.75; }
.badge { font-size: 0.75rem; background: #333; padding: 2px 8px; border-radius: 4px; }
.muted { opacity: 0.65; font-size: 0.85rem; }
.d-block { display: block; margin-top: 2px; max-width: 280px; }
.mr-2 { margin-right: 8px; }
.mt-4 { margin-top: 16px; }
.p-4 { padding: 16px; }
</style>
