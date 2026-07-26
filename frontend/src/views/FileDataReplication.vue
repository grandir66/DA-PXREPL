<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import NasSyncEndpointForm from '../components/nas-sync/NasSyncEndpointForm.vue'
import NasSyncJobModal from '../components/nas-sync/NasSyncJobModal.vue'
import NasSyncLogModal from '../components/nas-sync/NasSyncLogModal.vue'
import FileReplJobModal from '../components/file-replication/FileReplJobModal.vue'
import FileReplLogModal from '../components/file-replication/FileReplLogModal.vue'
import FileReplPathMapping from '../components/file-replication/FileReplPathMapping.vue'
import Icon from '../components/ui/Icon.vue'
import { fileEndpointsApi, type FileEndpoint } from '../services/fileEndpoints'
import { nasSyncApi, type NasSyncJob, type EndpointCapabilities } from '../services/nasSync'
import { fileReplicationApi, type FileReplicationJob } from '../services/fileReplication'
import { formatFileReplProgress, type FileReplProgress } from '../utils/fileReplProgress'

type TabId = 'all' | 'nas' | 'worm'

const activeTab = ref<TabId>('all')

// --- stato NAS→NAS (nas-sync) ---
const nasJobs = ref<NasSyncJob[]>([])
const nasStats = ref({ total: 0, active: 0, running: 0, failed: 0 })
const endpointCaps = ref<Record<number, EndpointCapabilities>>({})
const nasProgress = ref<Record<number, FileReplProgress>>({})

// --- stato QNAP WORM (file-replication) ---
const wormJobs = ref<FileReplicationJob[]>([])
const wormStats = ref({ total: 0, active: 0, running: 0, failed: 0 })
const wormProgress = ref<Record<number, FileReplProgress>>({})

// --- comune ---
const endpoints = ref<FileEndpoint[]>([])
const loading = ref(false)
const runError = ref('')
const listError = ref('')

// modali
const showNasJobModal = ref(false)
const editingNasJob = ref<NasSyncJob | null>(null)
const showWormJobModal = ref(false)
const editingWormJob = ref<FileReplicationJob | null>(null)
const showLogModal = ref(false)
const logType = ref<'nas' | 'worm'>('nas')
const logNasJob = ref<NasSyncJob | null>(null)
const logWormJob = ref<FileReplicationJob | null>(null)
const showEndpointForm = ref(false)
const editingEndpoint = ref<FileEndpoint | null>(null)
const endpointError = ref('')
const showNewMenu = ref(false)

let pollTimer: ReturnType<typeof setInterval> | null = null

// --- stat aggregate ---
const totalCount = computed(() => nasStats.value.total + wormStats.value.total)
const activeCount = computed(() => nasStats.value.active + wormStats.value.active)
const runningCount = computed(() => nasStats.value.running + wormStats.value.running)
const failedCount = computed(() => nasStats.value.failed + wormStats.value.failed)

const showNas = computed(() => activeTab.value === 'all' || activeTab.value === 'nas')
const showWorm = computed(() => activeTab.value === 'all' || activeTab.value === 'worm')
const isEmpty = computed(() => nasJobs.value.length === 0 && wormJobs.value.length === 0)

const tabs = computed<{ id: TabId; label: string; count: number }[]>(() => [
  { id: 'all', label: 'Tutti', count: nasJobs.value.length + wormJobs.value.length },
  { id: 'nas', label: 'NAS→NAS', count: nasJobs.value.length },
  { id: 'worm', label: 'QNAP WORM', count: wormJobs.value.length },
])

// --- caricamento ---
async function loadCapabilities(force = false) {
  await Promise.all(
    endpoints.value.map(async (ep) => {
      if (!force && endpointCaps.value[ep.id]) return
      try {
        const { data } = await nasSyncApi.capabilities(ep.id)
        endpointCaps.value[ep.id] = data
      } catch { /* ignore */ }
    }),
  )
}

async function refresh(silent = false) {
  if (!silent) loading.value = true
  listError.value = ''
  const results = await Promise.allSettled([
    nasSyncApi.list(),
    nasSyncApi.stats(),
    fileReplicationApi.list(),
    fileReplicationApi.stats(),
    fileEndpointsApi.list(),
  ])
  const [nasL, nasS, wormL, wormS, eps] = results
  if (nasL.status === 'fulfilled') nasJobs.value = nasL.value.data
  if (nasS.status === 'fulfilled') nasStats.value = nasS.value.data
  if (wormL.status === 'fulfilled') wormJobs.value = wormL.value.data
  if (wormS.status === 'fulfilled') wormStats.value = wormS.value.data
  if (eps.status === 'fulfilled') endpoints.value = eps.value.data
  const failed = results.some((r) => r.status === 'rejected')
  if (failed) listError.value = 'Alcuni dati non sono stati caricati; mostro ciò che è disponibile.'
  if (!silent) loading.value = false
  await loadCapabilities(!silent)
}

// --- NAS: stato/running (logica ricca del modulo nas-sync) ---
function nasIsRunning(job: NasSyncJob) {
  if (job.current_status === 'running') return true
  const prog = nasProgress.value[job.id]
  return prog?.status === 'running' || prog?.status === 'cancelling'
}
function nasIsCatalogRefreshing(job: NasSyncJob) {
  return nasProgress.value[job.id]?.status === 'catalog_refresh'
}
function nasIsBusy(job: NasSyncJob) {
  return nasIsRunning(job) || nasIsCatalogRefreshing(job)
}
function sourceHasSsh(job: NasSyncJob) {
  return Boolean(endpointCaps.value[job.source_endpoint_id]?.rsync_source)
}
function catalogFresherThanLastRun(job: NasSyncJob): boolean {
  if (!job.catalog_updated_at || !job.last_run_at) return Boolean(job.catalog_updated_at)
  return new Date(job.catalog_updated_at).getTime() >= new Date(job.last_run_at).getTime()
}
function nasDisplayStatus(job: NasSyncJob): string {
  if (nasIsCatalogRefreshing(job)) return 'catalogo'
  if (nasIsRunning(job)) return 'running'
  if (job.current_status === 'failed' && catalogFresherThanLastRun(job)) return 'idle'
  if (job.current_status && job.current_status !== 'idle') return job.current_status
  if (job.last_run_status === 'failed' && catalogFresherThanLastRun(job)) return 'idle'
  return job.current_status || job.last_run_status || 'idle'
}
function nasStatusTone(job: NasSyncJob): string {
  const s = nasDisplayStatus(job)
  if (s === 'running' || s === 'catalogo' || s === 'cancelling') return 'text-warning'
  if (s === 'failed') return 'text-danger'
  if (s === 'success') return 'text-success'
  return ''
}
function nasStatusSummary(job: NasSyncJob): string {
  const p = nasProgress.value[job.id]
  if (nasIsCatalogRefreshing(job)) return p?.message || 'Catalogo du in corso…'
  if (nasIsRunning(job) && p) {
    const parts: string[] = []
    if (p.current_folder_index && p.current_folder_total) parts.push(`${p.current_folder_index}/${p.current_folder_total}`)
    else if (p.folders_done != null && p.current_folder_total) parts.push(`${p.folders_done}/${p.current_folder_total}`)
    const folderRef = p.current_folder_path || p.current_folder_name
    if (folderRef) parts.push(folderRef.length > 40 ? `…${folderRef.slice(-39)}` : folderRef)
    const pct = p.progress_percent || p.percent
    if (pct && pct !== '-' && pct !== '-%') parts.push(String(pct))
    const eta = p.eta || p.eta_human
    if (eta && eta !== '-') parts.push(`ETA ${eta}`)
    if (!parts.length && p.phase_label) return p.phase_label
    if (!parts.length && p.message) return p.message
    return parts.join(' · ')
  }
  if (job.catalog_has_du && job.catalog_bytes_est) {
    return `du ${job.catalog_folder_count || '?'} cart. · ${formatBytes(job.catalog_bytes_est)}`
  }
  if (sourceHasSsh(job)) return 'Catalogo du assente'
  return ''
}
function nasShowLastRunError(job: NasSyncJob): boolean {
  if (!job.last_run_error || nasIsBusy(job)) return false
  if (catalogFresherThanLastRun(job)) return false
  return job.current_status === 'failed' || job.last_run_status === 'failed'
}

// --- WORM: stato/running ---
function wormIsRunning(job: FileReplicationJob) {
  return job.current_status === 'running'
}
function wormProgressLabel(jobId: number) {
  return formatFileReplProgress(wormProgress.value[jobId])
}

// --- polling unificato ---
async function refreshProgress() {
  const nasToPoll = nasJobs.value.filter(
    (j) => j.current_status === 'running' ||
      ['running', 'cancelling', 'catalog_refresh'].includes(nasProgress.value[j.id]?.status || ''),
  )
  const wormToPoll = wormJobs.value.filter((j) => wormIsRunning(j))
  await Promise.all([
    ...nasToPoll.map(async (j) => {
      try {
        const { data } = await nasSyncApi.progress(j.id)
        const status = data.status as string | undefined
        if (status === 'running' || status === 'cancelling' || status === 'catalog_refresh') {
          nasProgress.value[j.id] = data as FileReplProgress
        } else {
          if (nasProgress.value[j.id]?.status === 'catalog_refresh') await refresh(true)
          delete nasProgress.value[j.id]
        }
      } catch { /* ignore */ }
    }),
    ...wormToPoll.map(async (j) => {
      try {
        const { data } = await fileReplicationApi.progress(j.id)
        if (data.status === 'running') wormProgress.value[j.id] = data as FileReplProgress
        else delete wormProgress.value[j.id]
      } catch { /* ignore */ }
    }),
  ])
}

function anyRunning(): boolean {
  return (
    nasStats.value.running > 0 || wormStats.value.running > 0 ||
    nasJobs.value.some((j) => nasIsBusy(j)) ||
    wormJobs.value.some((j) => wormIsRunning(j)) ||
    Object.values(nasProgress.value).some((p) => ['running', 'cancelling', 'catalog_refresh'].includes(p?.status || '')) ||
    Object.values(wormProgress.value).some((p) => p?.status === 'running')
  )
}

function startLivePoll() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    await refresh(true)
    await refreshProgress()
    if (!anyRunning()) stopLivePoll()
  }, 3000)
}
function stopLivePoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

function errMsg(e: unknown, fallback: string): string {
  if (typeof e === 'object' && e !== null && 'response' in e) {
    const d = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
    if (typeof d === 'string') return d
  }
  return e instanceof Error ? e.message : fallback
}

// --- azioni NAS ---
async function nasRun(job: NasSyncJob) {
  runError.value = ''
  try {
    await nasSyncApi.run(job.id)
    nasProgress.value[job.id] = { status: 'running', message: 'Avvio…' }
    openNasLogs(job)
    await refresh()
    await refreshProgress()
    startLivePoll()
  } catch (e) { runError.value = errMsg(e, 'Avvio job fallito') }
}
async function nasStop(job: NasSyncJob) {
  runError.value = ''
  if (!confirm(`Mettere in pausa il job "${job.name}"?`)) return
  try { await nasSyncApi.stop(job.id); await refresh(); await refreshProgress() }
  catch (e) { runError.value = errMsg(e, 'Stop job fallito') }
}
async function nasRefreshCatalog(job: NasSyncJob) {
  runError.value = ''
  if (!confirm(`Aggiornare catalogo du per "${job.name}"?\n\nScansione SSH sulla sorgente (1° livello) per dimensioni cartelle e stima tempi. Non avvia la copia.`)) return
  try {
    await nasSyncApi.refreshCatalog(job.id)
    nasProgress.value[job.id] = { status: 'catalog_refresh', phase_label: 'Catalogo du sorgente', message: 'Avvio…' }
    startLivePoll()
  } catch (e) { runError.value = errMsg(e, 'Aggiornamento catalogo fallito') }
}
async function nasToggle(id: number) { await nasSyncApi.toggle(id); await refresh() }
async function nasDelete(id: number) { if (!confirm('Eliminare il job?')) return; await nasSyncApi.delete(id); await refresh() }
function openNasNew() { editingNasJob.value = null; showNasJobModal.value = true; showNewMenu.value = false }
function openNasEdit(job: NasSyncJob) { editingNasJob.value = job; showNasJobModal.value = true }
function closeNasJobModal() { showNasJobModal.value = false; editingNasJob.value = null }
function onNasSaved() { closeNasJobModal(); refresh() }
function openNasLogs(job: NasSyncJob) {
  logType.value = 'nas'; logNasJob.value = job; showLogModal.value = true
  if (nasIsBusy(job)) { void refreshProgress(); startLivePoll() }
}

// --- azioni WORM ---
async function wormRun(job: FileReplicationJob) {
  runError.value = ''
  try {
    await fileReplicationApi.run(job.id)
    openWormLogs(job)
    await refresh()
    startLivePoll()
  } catch (e) { runError.value = errMsg(e, 'Avvio job fallito') }
}
async function wormToggle(id: number) { await fileReplicationApi.toggle(id); await refresh() }
async function wormDelete(id: number) { if (!confirm('Eliminare il job?')) return; await fileReplicationApi.delete(id); await refresh() }
function openWormNew() { editingWormJob.value = null; showWormJobModal.value = true; showNewMenu.value = false }
function openWormEdit(job: FileReplicationJob) { editingWormJob.value = job; showWormJobModal.value = true }
function closeWormJobModal() { showWormJobModal.value = false; editingWormJob.value = null }
function onWormSaved() { closeWormJobModal(); refresh() }
function openWormLogs(job: FileReplicationJob) {
  logType.value = 'worm'; logWormJob.value = job; showLogModal.value = true
  if (wormIsRunning(job)) { void refreshProgress(); startLivePoll() }
}

function closeLogModal() { showLogModal.value = false; logNasJob.value = null; logWormJob.value = null }

// --- endpoint (condivisi) ---
function openNewEndpoint() { editingEndpoint.value = null; showEndpointForm.value = true; endpointError.value = '' }
function openEditEndpoint(ep: FileEndpoint) { editingEndpoint.value = ep; showEndpointForm.value = true; endpointError.value = '' }
function closeEndpointForm() { showEndpointForm.value = false; editingEndpoint.value = null; endpointError.value = '' }
function onEndpointSaved() { closeEndpointForm(); refresh() }
async function testEndpoint(id: number) {
  endpointError.value = ''
  try { const { data } = await fileEndpointsApi.test(id); await refresh(); alert(data.success ? `OK: ${data.message}` : `Fallito: ${data.message}`) }
  catch (e) { endpointError.value = errMsg(e, 'Test fallito') }
}
async function deleteEndpoint(ep: FileEndpoint) {
  if (!confirm(`Eliminare l'endpoint "${ep.name || ep.host}"?`)) return
  endpointError.value = ''
  try {
    await fileEndpointsApi.delete(ep.id)
    if (editingEndpoint.value?.id === ep.id) closeEndpointForm()
    await refresh()
  } catch (e) { endpointError.value = errMsg(e, 'Eliminazione fallita') }
}

function formatDate(v?: string | null) { return v ? new Date(v).toLocaleString() : '—' }
function formatBytes(n?: number | null) {
  if (!n) return ''
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = n, i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

onMounted(async () => {
  await refresh()
  if (anyRunning()) { await refreshProgress(); startLivePoll() }
})
onUnmounted(stopLivePoll)

// Direttiva locale per chiudere il dropdown al click esterno (come Replication.vue)
const vClickOutside = {
  mounted(el: any, binding: any) {
    el.__co = (e: MouseEvent) => {
      if (!(el === e.target || el.contains(e.target))) binding.value?.()
    }
    document.addEventListener('mousedown', el.__co)
  },
  unmounted(el: any) {
    document.removeEventListener('mousedown', el.__co)
  },
}
</script>

<template>
  <div class="repl-view">
    <header class="repl-head">
      <div class="repl-head-left">
        <h1>Repliche file dati</h1>
        <p class="repl-sub">
          Replica di cartelle tra NAS: motore diretto rsync (i dati non passano dal server) o rclone SMB,
          e replica verso QNAP con immutabilità WORM (snapshot nativi). Anagrafica endpoint condivisa.
        </p>
      </div>
      <div class="repl-head-actions">
        <button class="btn btn-secondary mr-2" @click="openNewEndpoint">
          <Icon name="plus" :size="14" /> Endpoint
        </button>
        <div class="new-wrap" v-click-outside="() => (showNewMenu = false)">
          <button class="btn btn-primary" @click="showNewMenu = !showNewMenu">
            <Icon name="plus" :size="14" /> Nuovo job <Icon name="chevron-down" :size="14" />
          </button>
          <ul v-if="showNewMenu" class="new-menu">
            <li @click="openNasNew()">
              <strong>Replica dati NAS→NAS</strong>
              <small>rsync diretto o rclone SMB tra NAS</small>
            </li>
            <li @click="openWormNew()">
              <strong>Replica QNAP WORM</strong>
              <small>sync → staging QNAP con immutabilità snapshot</small>
            </li>
          </ul>
        </div>
      </div>
    </header>

    <section class="repl-stats">
      <div class="repl-stat">
        <span class="repl-stat-label">Job totali</span>
        <span class="repl-stat-val">{{ totalCount }}</span>
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
        <button class="btn btn-sm btn-secondary" :disabled="loading" @click="refresh()">Aggiorna</button>
      </div>
      <div class="card-body p-0">
        <p v-if="endpointError" class="p-3 text-danger">{{ endpointError }}</p>
        <table class="data-table" v-if="endpoints.length">
          <thead>
            <tr>
              <th>Nome</th><th>Tipo</th><th>Ruolo</th><th>Capacità</th><th>Host</th><th>Ultimo test</th><th>Azioni</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="ep in endpoints" :key="ep.id">
              <td><strong>{{ ep.name || '—' }}</strong></td>
              <td><span class="badge">{{ ep.endpoint_type }}</span></td>
              <td>{{ ep.role }}</td>
              <td class="caps-cell">
                <template v-if="endpointCaps[ep.id]">
                  <span class="badge" :class="endpointCaps[ep.id]?.rsync_source ? 'badge-ok' : 'badge-off'">SSH</span>
                  <span class="badge" :class="endpointCaps[ep.id]?.rsync_dest ? 'badge-ok' : 'badge-off'">rsync</span>
                  <span class="badge" :class="endpointCaps[ep.id]?.smb ? 'badge-ok' : 'badge-off'">SMB</span>
                </template>
                <span v-else class="muted">—</span>
              </td>
              <td><code>{{ ep.host }}:{{ ep.port }}</code></td>
              <td>
                <span
                  v-if="ep.last_test_status"
                  :class="ep.last_test_status === 'success' ? 'text-success' : 'text-danger'"
                  :title="ep.last_test_message || ''"
                >{{ ep.last_test_status }}</span>
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
        <div class="repl-tabs">
          <button
            v-for="t in tabs"
            :key="t.id"
            class="repl-tab"
            :class="{ active: activeTab === t.id }"
            @click="activeTab = t.id"
          >
            {{ t.label }} <span class="repl-tab-count">{{ t.count }}</span>
          </button>
        </div>
        <button class="btn btn-sm btn-secondary" :disabled="loading" @click="refresh()">Aggiorna</button>
      </div>
      <div class="card-body p-0">
        <p v-if="listError" class="p-3 text-warning">{{ listError }}</p>
        <p v-if="runError" class="p-3 text-danger">{{ runError }}</p>
        <table class="data-table" v-if="!isEmpty">
          <thead>
            <tr>
              <th>Tipo</th><th>Nome</th><th>Replica</th><th>Schedule</th><th>Ultimo run</th><th>Stato</th><th>Azioni</th>
            </tr>
          </thead>
          <tbody>
            <!-- Righe NAS→NAS -->
            <template v-if="showNas">
              <tr v-for="job in nasJobs" :key="'nas-' + job.id">
                <td><span class="type-badge type-nas">NAS→NAS</span></td>
                <td>{{ job.name }}</td>
                <td class="fr-job-structure">
                  <span class="engine-chip" :class="job.resolved_engine === 'direct_rsync' ? 'engine-direct' : 'engine-rclone'">
                    {{ job.resolved_engine === 'direct_rsync' ? 'rsync diretto' : 'rclone SMB' }}
                  </span>
                  <FileReplPathMapping
                    compact :max-rows="2"
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
                <td class="fr-job-status">
                  <span class="fr-status-badge" :class="nasStatusTone(job)">{{ nasDisplayStatus(job) }}</span>
                  <span
                    v-if="nasStatusSummary(job)" class="fr-status-line"
                    :class="{ 'text-warning': !job.catalog_has_du && sourceHasSsh(job) && !nasIsBusy(job) }"
                    :title="nasStatusSummary(job)"
                  >{{ nasStatusSummary(job) }}</span>
                  <span v-if="nasIsBusy(job)" class="fr-status-hint">Dettaglio in Log</span>
                  <span
                    v-if="nasShowLastRunError(job)" class="fr-status-err" :title="job.last_run_error || ''"
                  >{{ (job.last_run_error || '').length > 80 ? (job.last_run_error || '').slice(0, 80) + '…' : job.last_run_error }}</span>
                </td>
                <td class="actions">
                  <button v-if="nasIsRunning(job)" class="btn btn-sm btn-warning" @click="nasStop(job)">Pausa</button>
                  <button v-else class="btn btn-sm btn-primary" :disabled="nasIsBusy(job)" @click="nasRun(job)">Run</button>
                  <button
                    class="btn btn-sm btn-secondary" :disabled="nasIsBusy(job) || !sourceHasSsh(job)"
                    title="Scansione du SSH per dimensioni cartelle e stima tempi" @click="nasRefreshCatalog(job)"
                  >{{ nasIsCatalogRefreshing(job) ? 'Catalogo…' : 'Catalogo du' }}</button>
                  <button class="btn btn-sm btn-secondary" @click="openNasEdit(job)">Modifica</button>
                  <button class="btn btn-sm btn-secondary" @click="openNasLogs(job)">Log</button>
                  <button class="btn btn-sm btn-secondary" @click="nasToggle(job.id)">{{ job.is_active ? 'Off' : 'On' }}</button>
                  <button class="btn btn-sm btn-danger" @click="nasDelete(job.id)">Del</button>
                </td>
              </tr>
            </template>
            <!-- Righe QNAP WORM -->
            <template v-if="showWorm">
              <tr v-for="job in wormJobs" :key="'worm-' + job.id">
                <td><span class="type-badge type-worm">QNAP WORM</span></td>
                <td>{{ job.name }}</td>
                <td class="fr-job-structure">
                  <FileReplPathMapping
                    compact :max-rows="2"
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
                  <span :class="wormIsRunning(job) ? 'text-warning' : (job.current_status === 'failed' || job.last_run_status === 'failed') ? 'text-danger' : job.last_run_status === 'success' ? 'text-success' : ''">
                    {{ wormIsRunning(job) ? 'running' : job.current_status || job.last_run_status || 'idle' }}
                  </span>
                  <small v-if="wormIsRunning(job) && wormProgressLabel(job.id)" class="muted d-block">{{ wormProgressLabel(job.id) }}</small>
                  <small v-if="job.last_run_error" class="muted d-block text-danger" :title="job.last_run_error">
                    {{ job.last_run_error.length > 120 ? job.last_run_error.slice(0, 120) + '…' : job.last_run_error }}
                  </small>
                </td>
                <td class="actions">
                  <button class="btn btn-sm btn-primary" @click="wormRun(job)">Run</button>
                  <button class="btn btn-sm btn-secondary" @click="openWormEdit(job)">Modifica</button>
                  <button class="btn btn-sm btn-secondary" @click="openWormLogs(job)">Log</button>
                  <button class="btn btn-sm btn-secondary" @click="wormToggle(job.id)">{{ job.is_active ? 'Off' : 'On' }}</button>
                  <button class="btn btn-sm btn-danger" @click="wormDelete(job.id)">Del</button>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
        <p v-else class="p-4">Nessun job. Crea un endpoint e un job (NAS→NAS o QNAP WORM) per iniziare.</p>
      </div>
    </div>

    <!-- Log modali (per tipo) -->
    <NasSyncLogModal
      v-if="showLogModal && logType === 'nas' && logNasJob"
      :job-id="logNasJob.id" :job-name="logNasJob.name" :job="logNasJob" @close="closeLogModal"
    />
    <FileReplLogModal
      v-if="showLogModal && logType === 'worm' && logWormJob"
      :job-id="logWormJob.id" :job-name="logWormJob.name" :job="logWormJob" @close="closeLogModal"
    />

    <!-- Job modali (per tipo) -->
    <NasSyncJobModal v-if="showNasJobModal" :job="editingNasJob" @close="closeNasJobModal" @saved="onNasSaved" />
    <FileReplJobModal v-if="showWormJobModal" :job="editingWormJob" @close="closeWormJobModal" @saved="onWormSaved" />
  </div>
</template>

<style scoped>
.repl-view { padding: 0; }
.repl-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; gap: 16px; }
.repl-sub { opacity: 0.75; margin-top: 4px; max-width: 680px; }
.repl-head-actions { display: flex; align-items: flex-start; }
.new-wrap { position: relative; }
.new-menu {
  position: absolute; right: 0; top: calc(100% + 4px); z-index: 20; list-style: none; margin: 0; padding: 4px;
  min-width: 280px; background: var(--color-bg-surface); border: 1px solid var(--color-border);
  border-radius: var(--radius-md); box-shadow: var(--shadow-lg);
}
.new-menu li { padding: 8px 10px; border-radius: var(--radius-sm); cursor: pointer; }
.new-menu li:hover { background: var(--color-bg-hover); }
.new-menu li strong { display: block; font-size: 0.85rem; }
.new-menu li small { opacity: 0.7; font-size: 0.72rem; }
.repl-stats { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
.repl-stat { background: var(--bg-secondary, #1a1a2e); padding: 12px 20px; border-radius: 8px; min-width: 120px; }
.repl-stat-label { display: block; font-size: 0.75rem; opacity: 0.7; }
.repl-stat-val { font-size: 1.5rem; font-weight: 700; }
.repl-tabs { display: flex; gap: 4px; }
.repl-tab {
  background: transparent; border: 1px solid transparent; border-radius: var(--radius-sm);
  padding: 4px 12px; cursor: pointer; color: var(--color-text-secondary); font-size: 0.85rem;
}
.repl-tab.active { background: var(--color-bg-element); color: var(--color-text-primary); border-color: var(--color-border); }
.repl-tab-count { opacity: 0.6; font-size: 0.75rem; }
.type-badge { font-size: 0.7rem; padding: 2px 8px; border-radius: var(--radius-sm); white-space: nowrap; }
.type-nas { background: rgba(46, 204, 113, .15); color: #2ecc71; }
.type-worm { background: rgba(88, 166, 255, .15); color: #58a6ff; }
.actions { display: flex; gap: 6px; flex-wrap: wrap; }
.fr-job-structure { min-width: 240px; max-width: 380px; vertical-align: top; }
.fr-job-status { min-width: 160px; max-width: 240px; vertical-align: top; font-size: 0.78rem; line-height: 1.35; }
.fr-status-badge { display: inline-block; font-weight: 600; font-size: 0.8rem; }
.fr-status-line { display: block; margin-top: 2px; opacity: 0.72; font-size: 0.72rem; max-width: 230px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fr-status-hint { display: block; margin-top: 1px; font-size: 0.68rem; opacity: 0.45; }
.fr-status-err { display: block; margin-top: 2px; font-size: 0.7rem; color: #e74c3c; max-width: 230px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.badge { font-size: 0.75rem; background: #333; padding: 2px 8px; border-radius: 4px; }
.muted { opacity: 0.65; font-size: 0.85rem; }
.d-block { display: block; margin-top: 2px; max-width: 320px; }
.mr-2 { margin-right: 8px; }
.p-4 { padding: 16px; }
.engine-chip { display: inline-block; font-size: .7rem; padding: 1px 8px; border-radius: 10px; margin-bottom: 4px; }
.engine-direct { background: rgba(46, 204, 113, .15); color: #2ecc71; }
.engine-rclone { background: rgba(241, 196, 15, .15); color: #f1c40f; }
.caps-cell .badge { margin-right: 4px; font-size: .7rem; }
.badge-ok { background: rgba(46, 204, 113, .18); color: #2ecc71; }
.badge-off { background: rgba(255,255,255,.06); opacity: .55; }
</style>
