<script setup lang="ts">
import axios from 'axios'
import { onMounted, onUnmounted, ref } from 'vue'
import Icon from '../components/ui/Icon.vue'
import VmSnapshotBrowserModal from '../components/vm-snapshot/VmSnapshotBrowserModal.vue'
import VmSnapshotJobModal from '../components/vm-snapshot/VmSnapshotJobModal.vue'
import VmSnapshotLogModal from '../components/vm-snapshot/VmSnapshotLogModal.vue'
import {
  vmSnapshotsApi,
  type VmSnapshotJob,
  type VmSnapshotStats,
} from '../services/vmSnapshots'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const jobs = ref<VmSnapshotJob[]>([])
const stats = ref<VmSnapshotStats>({ total: 0, active: 0, running: 0, failed: 0 })
const loading = ref(false)
const runError = ref('')
const showJobModal = ref(false)
const editingJob = ref<VmSnapshotJob | null>(null)
const showLogModal = ref(false)
const logJob = ref<VmSnapshotJob | null>(null)
const showBrowser = ref(false)
const browserJob = ref<VmSnapshotJob | null>(null)
const expandedJob = ref<number | null>(null)
const progressByJob = ref<Record<number, { current?: number; total?: number; vm?: string }>>({})
let pollTimer: ReturnType<typeof setInterval> | null = null

async function refresh(silent = false) {
  if (!silent) loading.value = true
  try {
    const [j, s] = await Promise.all([vmSnapshotsApi.list(), vmSnapshotsApi.stats()])
    jobs.value = j.data
    stats.value = s.data
  } finally {
    if (!silent) loading.value = false
  }
}

function jobIsRunning(job: VmSnapshotJob) {
  return job.current_status === 'running'
}

function resolvedVmCount(job: VmSnapshotJob) {
  const results = job.run_state?.results
  if (results?.length) return results.length
  return job.targets.length || null
}

function statusBadge(job: VmSnapshotJob): { label: string; cls: string } {
  if (jobIsRunning(job)) return { label: t('stato.running'), cls: 'vs-running' }
  if (job.last_run_status === 'success') return { label: t('stato.success'), cls: 'vs-success' }
  if (job.last_run_status === 'partial') return { label: t('snapVm.sParziale'), cls: 'vs-partial' }
  if (job.last_run_status === 'failed') return { label: t('stato.failed'), cls: 'vs-failed' }
  return { label: t('snapVm.sMai'), cls: 'vs-idle' }
}

function fmtDate(value?: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleString('it-IT')
}

async function pollProgress() {
  const running = jobs.value.filter(jobIsRunning)
  if (!running.length) return
  await Promise.all(
    running.map(async (job) => {
      try {
        const { data } = await vmSnapshotsApi.progress(job.id)
        progressByJob.value[job.id] = data
      } catch { /* ignore */ }
    }),
  )
  await refresh(true)
}

async function runJob(job: VmSnapshotJob) {
  runError.value = ''
  try {
    await vmSnapshotsApi.run(job.id)
    await refresh(true)
  } catch (e: unknown) {
    runError.value = axios.isAxiosError(e)
      ? String(e.response?.data?.detail || e.message)
      : t('snapVm.erroreAvvio')
  }
}

async function toggleJob(job: VmSnapshotJob) {
  await vmSnapshotsApi.toggle(job.id)
  await refresh(true)
}

async function deleteJob(job: VmSnapshotJob) {
  if (!window.confirm(t('snapVm.confElimina', { nome: job.name }))) return
  await vmSnapshotsApi.delete(job.id)
  await refresh(true)
}

function openNewJob() {
  editingJob.value = null
  showJobModal.value = true
}

function openEditJob(job: VmSnapshotJob) {
  editingJob.value = job
  showJobModal.value = true
}

function openLog(job: VmSnapshotJob) {
  logJob.value = job
  showLogModal.value = true
}

function openBrowser(job: VmSnapshotJob) {
  browserJob.value = job
  showBrowser.value = true
}

function onJobSaved() {
  showJobModal.value = false
  void refresh()
}

onMounted(() => {
  void refresh()
  pollTimer = setInterval(() => void pollProgress(), 3000)
})
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="vs-view">
    <header class="vs-head">
      <div>
        <h1>{{ t('menu.snapshotVm') }}</h1>
        <p class="vs-sub">
          {{ t('snapVm.sottotitolo') }}
        </p>
      </div>
      <button class="btn btn-primary" @click="openNewJob">{{ t('snapVm.nuovo') }}</button>
    </header>

    <section class="vs-stats">
      <div class="vs-stat"><span class="vs-stat-label">{{ t('snapVm.totali') }}</span><span class="vs-stat-val">{{ stats.total }}</span></div>
      <div class="vs-stat"><span class="vs-stat-label">{{ t('comune.attivi') }}</span><span class="vs-stat-val text-success">{{ stats.active }}</span></div>
      <div class="vs-stat"><span class="vs-stat-label">{{ t('snapVm.inCorso') }}</span><span class="vs-stat-val text-warning">{{ stats.running }}</span></div>
      <div class="vs-stat"><span class="vs-stat-label">{{ t('snapVm.falliti') }}</span><span class="vs-stat-val text-danger">{{ stats.failed }}</span></div>
    </section>

    <div class="card">
      <div class="card-header">
        <h3>{{ t('snapVm.configurati') }}</h3>
        <button class="btn btn-sm btn-secondary" :disabled="loading" @click="refresh()">{{ t('comune.aggiorna') }}</button>
      </div>
      <div class="card-body p-0">
        <p v-if="runError" class="p-3 text-danger">{{ runError }}</p>
        <table v-if="jobs.length" class="data-table">
          <thead>
            <tr>
              <th></th>
              <th>{{ t('comune.nome') }}</th>
              <th>{{ t('snapVm.politica') }}</th>
              <th>VM</th>
              <th>{{ t('snapVm.pianificazione') }}</th>
              <th>{{ t('snapVm.ultima') }}</th>
              <th>{{ t('comune.stato') }}</th>
              <th>{{ t('comune.azioni') }}</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="job in jobs" :key="job.id">
              <tr :class="{ 'vs-inactive': !job.is_active }">
                <td>
                  <button
                    class="btn btn-sm vs-expander"
                    :title="expandedJob === job.id ? t('snapVm.chiudiDett') : t('snapVm.dettUltima')"
                    @click="expandedJob = expandedJob === job.id ? null : job.id"
                  >{{ expandedJob === job.id ? '▾' : '▸' }}</button>
                </td>
                <td>
                  <strong>{{ job.name }}</strong>
                  <small v-if="job.label_conflicts.length" class="d-block text-warning"
                         :title="t('snapVm.condivisaCon', { job: job.label_conflicts.join(', ') })">
                    <Icon name="alert-triangle" :size="14" /> {{ t('snapVm.condivisa') }}
                  </small>
                </td>
                <td>
                  <span class="vs-chip">{{ job.label }} × {{ job.keep }}</span>
                  <span v-if="job.include_vmstate" class="vs-chip vs-chip-ram" :title="t('snapVm.ram')">RAM</span>
                </td>
                <td>{{ resolvedVmCount(job) ?? '—' }}</td>
                <td><code>{{ job.schedule || 'manuale' }}</code></td>
                <td>
                  {{ fmtDate(job.last_run_at) }}
                  <small v-if="job.last_run_duration_sec" class="d-block muted">{{ job.last_run_duration_sec }}s</small>
                </td>
                <td>
                  <span class="vs-status" :class="statusBadge(job).cls">{{ statusBadge(job).label }}</span>
                  <small v-if="jobIsRunning(job) && progressByJob[job.id]?.total" class="d-block muted">
                    {{ progressByJob[job.id]?.current }}/{{ progressByJob[job.id]?.total }}
                    — {{ progressByJob[job.id]?.vm }}
                  </small>
                  <small v-else-if="job.last_run_error" class="d-block text-danger vs-error-line" :title="job.last_run_error">
                    {{ job.last_run_error }}
                  </small>
                </td>
                <td class="vs-actions">
                  <button class="btn btn-sm btn-primary" :disabled="jobIsRunning(job)" :title="t('snapVm.eseguiOra')" @click="runJob(job)">{{ t('snapVm.esegui') }}</button>
                  <button class="btn btn-sm btn-secondary" :title="t('snapVm.sfoglia')" @click="openBrowser(job)">{{ t('snapVm.snapshot') }}</button>
                  <button class="btn btn-sm btn-secondary" @click="openEditJob(job)">{{ t('comune.modifica') }}</button>
                  <button class="btn btn-sm btn-secondary" @click="openLog(job)">{{ t('comune.registro') }}</button>
                  <button class="btn btn-sm" :class="job.is_active ? 'btn-warning' : 'btn-success'"
                          :title="job.is_active ? t('snapVm.disattiva') : t('snapVm.attiva')"
                          @click="toggleJob(job)">{{ job.is_active ? t('snapVm.off') : t('snapVm.on') }}</button>
                  <button class="btn btn-sm btn-danger" @click="deleteJob(job)">{{ t('comune.elimina') }}</button>
                </td>
              </tr>
              <tr v-if="expandedJob === job.id">
                <td colspan="8" class="vs-detail-cell">
                  <template v-if="job.run_state?.results?.length">
                    <p class="muted">
                      <i18n-t keypath="snapVm.riepilogo" tag="span"><template #nome><code>{{ job.run_state.snapname }}</code></template><template #ok>{{ job.run_state.summary?.ok }}</template><template #totale>{{ job.run_state.results.length }}</template><template #potati>{{ job.run_state.summary?.pruned_total }}</template></i18n-t>
                    </p>
                    <ul class="vs-results">
                      <li v-for="r in job.run_state.results" :key="`${r.node_id}:${r.vmid}`">
                        <span :class="r.error ? 'text-danger' : 'text-success'">{{ r.error ? '✗' : '✓' }}</span>
                        <code>{{ r.vmid }}</code> {{ r.vm_name }} @ {{ r.node_name }}
                        <span v-if="r.error" class="text-danger">— {{ r.error }}</span>
                        <span v-else-if="r.pruned.length" class="muted">{{ t('snapVm.potati', { n: r.pruned.length }) }}</span>
                        <span v-if="r.warning" class="text-warning" :title="r.warning"><Icon name="alert-triangle" :size="14" /></span>
                      </li>
                    </ul>
                  </template>
                  <p v-else class="muted">{{ t('snapVm.nessunaEsecuzione') }}</p>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
        <p v-else class="p-4">
          <i18n-t keypath="snapVm.vuoto" tag="span"><template #bottone><strong>{{ t('snapVm.nuovo') }}</strong></template></i18n-t>
        </p>
      </div>
    </div>

    <VmSnapshotJobModal
      v-if="showJobModal"
      :job="editingJob"
      :existing-jobs="jobs"
      @saved="onJobSaved"
      @close="showJobModal = false"
    />
    <VmSnapshotLogModal v-if="showLogModal && logJob" :job="logJob" @close="showLogModal = false" />
    <VmSnapshotBrowserModal v-if="showBrowser && browserJob" :job="browserJob" @close="showBrowser = false" />
  </div>
</template>

<style scoped>
.vs-view { padding: 20px; }
.vs-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 16px; }
.vs-sub { opacity: .7; font-size: .875rem; margin-top: 4px; max-width: 640px; }
.vs-stats { display: flex; gap: 14px; margin-bottom: 16px; flex-wrap: wrap; }
.vs-stat {
  background: var(--bg-secondary, #1a1a1a); border-radius: 10px;
  padding: 10px 18px; display: flex; flex-direction: column; min-width: 110px;
}
.vs-stat-label { font-size: .75rem; opacity: .65; }
.vs-stat-val { font-size: 1.4rem; font-weight: 700; }
.vs-chip {
  display: inline-block; font-size: .75rem; padding: 2px 9px; border-radius: 10px;
  background: rgba(52, 152, 219, .16); color: #3498db; font-weight: 600;
}
.vs-chip-ram { background: rgba(155, 89, 182, .16); color: #9b59b6; margin-left: 4px; }
.vs-status { font-size: .75rem; padding: 2px 9px; border-radius: 10px; }
.vs-running { background: rgba(241, 196, 15, .18); color: #f1c40f; }
.vs-success { background: rgba(46, 204, 113, .18); color: #2ecc71; }
.vs-partial { background: rgba(230, 126, 34, .18); color: #e67e22; }
.vs-failed { background: rgba(231, 76, 60, .18); color: #e74c3c; }
.vs-idle { background: rgba(255,255,255,.08); opacity: .7; }
.vs-actions { display: flex; gap: 4px; flex-wrap: wrap; }
.vs-inactive { opacity: .55; }
.vs-expander { padding: 0 6px; }
.vs-detail-cell { background: rgba(255,255,255,.02); }
.vs-results { list-style: none; padding: 4px 0 8px; margin: 0; font-size: .82rem; display: flex; flex-direction: column; gap: 2px; }
.vs-error-line { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.muted { opacity: .65; }
.d-block { display: block; }
.text-warning { color: #f1c40f; }
</style>
