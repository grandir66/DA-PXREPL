<template>
  <div class="repl-view">
    <header class="repl-head">
      <div class="repl-head-left">
        <h1>{{ t('repliche.titolo') }}</h1>
        <i18n-t keypath="repliche.sottotitolo" tag="p" class="repl-sub">
          <template #link><router-link :to="{ name: 'pbs-backup' }">{{ t('menu.pbsBackup') }}</router-link></template>
        </i18n-t>
      </div>
      <div class="repl-head-actions">
        <router-link :to="{ name: 'pbs-backup' }" class="btn btn-secondary mr-2">
          {{ t('menu.pbsBackup') }}
        </router-link>
        <div class="repl-new-wrap" v-click-outside="closeNewMenu">
          <button class="btn btn-primary" @click="newMenuOpen = !newMenuOpen">
            {{ t('repliche.nuovoJob') }}
            <span class="caret">▾</span>
          </button>
          <ul v-if="newMenuOpen" class="repl-new-menu">
            <li @click="openCreate('syncoid')">
              <span class="kind-dot zfs"></span>
              <div>
                <strong>{{ t('repliche.zfs') }}</strong>
                <small>{{ t('repliche.zfsSotto') }}</small>
              </div>
            </li>
            <li @click="openCreate('pve_native')">
              <span class="kind-dot zfs"></span>
              <div>
                <strong>{{ t('repliche.pveNativa') }}</strong>
                <small>{{ t('repliche.pveNativaSotto') }}</small>
              </div>
            </li>
            <li @click="openCreate('recovery_pbs')">
              <span class="kind-dot pbs"></span>
              <div>
                <strong>{{ t('repliche.viaPbs') }}</strong>
                <small>{{ t('repliche.viaPbsSotto') }}</small>
              </div>
            </li>
            <li class="repl-new-menu-link" @click="goPbsBackup">
              <span class="kind-dot pbs"></span>
              <div>
                <strong>{{ t('repliche.backupPbs') }}</strong>
                <small>{{ t('repliche.backupPbsSotto') }}</small>
              </div>
            </li>
          </ul>
        </div>
      </div>
    </header>

    <section class="repl-stats">
      <div class="repl-stat">
        <span class="repl-stat-label">{{ t('repliche.jobTotali') }}</span>
        <span class="repl-stat-val">{{ replicationJobs.length }}</span>
      </div>
      <div class="repl-stat">
        <span class="repl-stat-label">{{ t('comune.attivi') }}</span>
        <span class="repl-stat-val text-success">{{ activeCount }}</span>
      </div>
      <div class="repl-stat">
        <span class="repl-stat-label">{{ t('repliche.inEsecuzione') }}</span>
        <span class="repl-stat-val text-warning">{{ runningCount }}</span>
      </div>
      <div class="repl-stat">
        <span class="repl-stat-label">{{ t('repliche.falliti') }}</span>
        <span class="repl-stat-val text-danger">{{ failedCount }}</span>
      </div>
    </section>

    <nav class="repl-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        class="repl-tab"
        :class="{ active: activeTab === tab.id }"
        @click="activeTab = tab.id"
      >
        {{ t(`repliche.scheda.${tab.id}`) }}
        <span v-if="tab.count != null" class="repl-tab-count">{{ tab.count }}</span>
      </button>
    </nav>

    <div v-if="activeTab === 'recovery_pbs'" class="info-banner mb-4">
      <div class="icon"><Icon name="refresh" :size="20" /></div>
      <div class="content">
        <strong>{{ t('repliche.viaPbs') }}</strong>
        <i18n-t keypath="repliche.avvisoPbs" tag="p">
          <template #non><em>{{ t('repliche.non') }}</em></template>
          <template #scheda><strong>{{ t('repliche.scheda.syncoid') }}</strong></template>
        </i18n-t>
      </div>
    </div>

    <main class="repl-main">
      <!-- Tab "PVE Native" è read-only e usa la view legacy -->
      <PVELegacy v-if="activeTab === 'pve'" @import="onImportPvesr" />

      <JobsList
        v-else
        :jobs="filteredJobs"
        :loading="store.loadingJobs"
        @refresh="reload"
        @edit="onEdit"
        @run="onRun"
        @delete="onDelete"
        @show-log="onShowLog"
        @toggle-active="onToggleActive"
      />
    </main>

    <JobModal
      v-model:visible="modalVisible"
      :mode="createKind"
      :job="editingJob"
      :preset-pvesr="presetPvesr"
      @saved="onSaved"
    />

    <JobLogViewer
      v-model:visible="logVisible"
      :job-id="logJobId"
      :job-name="logJobName"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { confirmDangerous } from '../stores/confirm';
import { useToast, errorMessage } from '../stores/toast'
import { useReplicationStore, type UnifiedJob, type JobKind } from '../stores/replication'
import JobsList from '../components/jobs/JobsList.vue'
import JobModal from '../components/jobs/JobModal.vue'
import JobLogViewer from '../components/jobs/JobLogViewer.vue'
import PVELegacy from './replication/PVEReplicationJobs.vue'
import syncJobsService from '../services/syncJobs'
import recoveryJobsService from '../services/recoveryJobs'
import { pveReplicationService, type PVEReplicationJob, type PVEReplicationSummary } from '../services/pveReplication'
import Icon from '../components/ui/Icon.vue'
import { useI18n } from 'vue-i18n'

const store = useReplicationStore()
const toast = useToast()
const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const activeTab = ref<'all' | 'syncoid' | 'pve_native' | 'recovery_pbs' | 'pve'>('all')
const newMenuOpen = ref(false)

const modalVisible = ref(false)
const editingJob = ref<UnifiedJob | null>(null)
const createKind = ref<JobKind>('syncoid')

const logVisible = ref(false)
const logJobId = ref<number | string | null>(null)
const logJobName = ref<string>('')

const pvesrSummary = ref<PVEReplicationSummary | null>(null)
const presetPvesr = ref<PVEReplicationJob | null>(null)

const replicationJobs = computed(() => store.jobs.filter(j => j.kind !== 'backup_pbs'))

const tabs = computed<{ id: 'all' | 'syncoid' | 'pve_native' | 'recovery_pbs' | 'pve'; count: number | null }[]>(() => [
  { id: 'all', count: replicationJobs.value.length },
  { id: 'syncoid', count: replicationJobs.value.filter(j => j.kind === 'syncoid').length },
  { id: 'pve_native', count: replicationJobs.value.filter(j => j.kind === 'pve_native').length },
  { id: 'recovery_pbs', count: replicationJobs.value.filter(j => j.kind === 'recovery_pbs').length },
  { id: 'pve', count: pvesrSummary.value?.total ?? null },
])

const filteredJobs = computed(() => {
  if (activeTab.value === 'all') return replicationJobs.value
  if (activeTab.value === 'pve') return []
  return replicationJobs.value.filter(j => j.kind === activeTab.value)
})

const activeCount = computed(() => replicationJobs.value.filter(j => j.is_active !== false).length)
function isJobRunning(j: UnifiedJob): boolean {
  const cur = (j.current_status || '').toLowerCase()
  if (['running', 'backing_up', 'restoring', 'registering'].includes(cur)) return true
  const last = (j.last_status || '').toLowerCase()
  return last === 'running' || last === 'started'
}
const runningCount = computed(() => replicationJobs.value.filter(isJobRunning).length)
const failedCount = computed(() =>
  replicationJobs.value.filter(j => ['error', 'failed'].includes((j.last_status || '').toLowerCase())).length
)

let pollHandle: number | null = null

async function reload() {
  await store.fetchAll()
  try {
    pvesrSummary.value = await pveReplicationService.getSummary()
  } catch {
    pvesrSummary.value = null
  }
}

function onImportPvesr(job: PVEReplicationJob) {
  presetPvesr.value = job
  createKind.value = 'syncoid'
  editingJob.value = null
  modalVisible.value = true
}

onMounted(() => {
  const qtab = route.query.tab as string
  if (['all', 'syncoid', 'pve_native', 'recovery_pbs', 'pve'].includes(qtab)) {
    activeTab.value = qtab as typeof activeTab.value
  }
  reload()
  pollHandle = window.setInterval(() => store.fetchJobs().catch(() => {}), 10_000)
})

watch(activeTab, tab => {
  if (tab !== 'pve') router.replace({ query: { tab } })
})
onUnmounted(() => {
  if (pollHandle) window.clearInterval(pollHandle)
})

function goPbsBackup() {
  newMenuOpen.value = false
  router.push({ name: 'pbs-backup', query: { tab: 'jobs', action: 'create' } })
}

function openCreate(k: JobKind) {
  if (k === 'backup_pbs') {
    goPbsBackup()
    return
  }
  createKind.value = k
  editingJob.value = null
  newMenuOpen.value = false
  modalVisible.value = true
}

function onEdit(j: UnifiedJob) {
  if (j.kind === 'backup_pbs') {
    router.push({ name: 'pbs-backup', query: { tab: 'jobs' } })
    return
  }
  editingJob.value = j
  createKind.value = j.kind
  modalVisible.value = true
}

function onShowLog(j: UnifiedJob) {
  if (j.kind === 'backup_pbs' || j.kind === 'recovery_pbs') {
    toast.info(t('repliche.logPbs'), t('repliche.logPbsDett'))
    return
  }
  if (j.kind !== 'syncoid' && j.kind !== 'pve_native') return
  logJobId.value = j.id
  logJobName.value = j.name
  logVisible.value = true
}

async function onRun(j: UnifiedJob, group?: { jobs: UnifiedJob[] }) {
  // Dopo una migrazione live la destinazione non ha snapshot in comune e
  // syncoid si rifiuta: il job lo segna e qui si chiede se ricreare la
  // destinazione da zero (replica completa) per questa corsa soltanto.
  const chiedeCompleta = [j, ...(group?.jobs ?? [])].some(x => x.raw?.richiede_replica_completa)
  let replicaCompleta = false
  if (chiedeCompleta && (j.kind === 'syncoid' || j.kind === 'pve_native')) {
    replicaCompleta = await confirmDangerous(
      t('repliche.chiedeCompleta', { nome: j.name }),
      undefined,
      t('repliche.replicaCompleta')
    )
    if (!replicaCompleta) return
  }
  try {
    if (
      (j.kind === 'syncoid' || j.kind === 'pve_native') &&
      j.raw?.vm_group_id
    ) {
      await syncJobsService.runVmGroup(String(j.raw.vm_group_id), replicaCompleta)
    } else if (j.kind === 'syncoid' || j.kind === 'pve_native') {
      // pve_native vive nello stesso endpoint /api/sync-jobs
      await syncJobsService.runJob(String(j.id), replicaCompleta)
    } else if (j.kind === 'recovery_pbs') {
      await recoveryJobsService.runJob(String(j.id))
    }
    setTimeout(reload, 800)
  } catch (e) {
    const msg = (e as any)?.response?.data?.detail || (e as any)?.message
    ;(window as any).alert?.(t('repliche.erroreAvvio', { msg }))
  }
}

async function onToggleActive(j: UnifiedJob) {
  const newActive = j.is_active === false
  if (!await confirmDangerous(
    newActive ? t('repliche.attivare', { nome: j.name }) : t('repliche.disattivare', { nome: j.name }),
    undefined,
    newActive ? t('comune.attiva') : t('comune.disattiva')
  )) return
  try {
    if (j.kind === 'syncoid' || j.kind === 'pve_native') {
      await syncJobsService.toggleJob(String(j.id))
    } else if (j.kind === 'recovery_pbs') {
      await recoveryJobsService.updateJob(String(j.id), { is_active: newActive })
    }
    toast.success(newActive ? t('repliche.attivato') : t('repliche.disattivato'))
    await reload()
  } catch (e) {
    toast.error(t('repliche.erroreStato'), errorMessage(e))
  }
}

async function onDelete(j: UnifiedJob) {
  if (!await confirmDangerous(t('repliche.eliminare', { nome: j.name }))) return
  try {
    if (j.kind === 'syncoid' || j.kind === 'pve_native') await syncJobsService.deleteJob(String(j.id))
    else if (j.kind === 'recovery_pbs') await recoveryJobsService.deleteJob(String(j.id))
    await reload()
  } catch (e) {
    toast.error(t('comune.erroreEliminazione'), errorMessage(e))
  }
}

function onSaved() {
  modalVisible.value = false
  presetPvesr.value = null
  reload()
}

function closeNewMenu() {
  newMenuOpen.value = false
}

// Direttiva minimale per chiudere il dropdown click-outside
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

<style scoped>
.repl-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  padding: var(--space-5);
}

.repl-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-3);
}
.repl-head h1 {
  margin: 0;
  font-size: 1.4rem;
  color: var(--color-text-primary);
}
.repl-sub {
  margin: 4px 0 0;
  color: var(--color-text-secondary);
  font-size: 0.85rem;
}

.repl-new-wrap {
  position: relative;
}
.caret {
  margin-left: 6px;
  font-size: 0.75rem;
  opacity: 0.7;
}
.repl-new-menu {
  position: absolute;
  right: 0;
  top: calc(100% + 6px);
  min-width: 280px;
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  list-style: none;
  margin: 0;
  padding: 4px;
  z-index: 50;
}
.repl-new-menu li {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.repl-new-menu li:hover {
  background: var(--color-bg-hover);
}
.repl-new-menu strong {
  display: block;
  font-size: 0.85rem;
  color: var(--color-text-primary);
}
.repl-new-menu small {
  display: block;
  font-size: 0.74rem;
  color: var(--color-text-secondary);
}
.kind-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.kind-dot.zfs {
  background: var(--color-zfs);
}
.kind-dot.pbs {
  background: var(--color-pbs);
}

.repl-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--space-3);
}
.repl-stat {
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.repl-stat-label {
  font-size: 0.7rem;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.repl-stat-val {
  font-size: 1.6rem;
  font-weight: 700;
  color: var(--color-text-primary);
  font-family: var(--font-mono);
}
.text-success {
  color: var(--color-success-fg) !important;
}
.text-warning {
  color: var(--color-warning-fg) !important;
}
.text-danger {
  color: var(--color-danger-fg) !important;
}

.repl-tabs {
  display: flex;
  gap: 2px;
  border-bottom: 1px solid var(--color-border);
}
.repl-tab {
  background: none;
  border: 0;
  padding: var(--space-3) var(--space-4);
  color: var(--color-text-secondary);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  font-weight: 600;
  font-size: 0.86rem;
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}
.repl-tab:hover {
  color: var(--color-text-primary);
}
.repl-tab.active {
  color: var(--color-primary);
  border-bottom-color: var(--color-primary);
}
.repl-tab-count {
  font-size: 0.7rem;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--color-bg-element);
  color: var(--color-text-secondary);
}
.repl-tab.active .repl-tab-count {
  background: var(--color-primary-dim);
  color: var(--color-primary);
}

.repl-main {
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
}

.info-banner {
  display: flex;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-element);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}
.info-banner .icon { font-size: 1.5rem; }
.info-banner p { margin: 0.25rem 0 0; font-size: 0.9rem; color: var(--color-text-secondary); }
</style>
