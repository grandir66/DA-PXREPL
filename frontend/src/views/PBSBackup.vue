<template>
  <div class="pbs-hub">
    <PageHeader
      :title="t('menu.pbsBackup')"
      :subtitle="t('pbsBackup.sottotitolo')"
      icon="database"
    />

    <section class="pbs-stats">
      <div class="pbs-stat">
        <span class="pbs-stat-label">{{ t('pbsBackup.jobBackup') }}</span>
        <span class="pbs-stat-val">{{ stats.total }}</span>
      </div>
      <div class="pbs-stat">
        <span class="pbs-stat-label">{{ t('comune.attivi') }}</span>
        <span class="pbs-stat-val text-success">{{ stats.active }}</span>
      </div>
      <div class="pbs-stat">
        <span class="pbs-stat-label">{{ t('pbsBackup.pianificati') }}</span>
        <span class="pbs-stat-val">{{ stats.scheduled }}</span>
      </div>
      <div class="pbs-stat">
        <span class="pbs-stat-label">{{ t('pbsBackup.inCorso') }}</span>
        <span class="pbs-stat-val text-warning">{{ stats.running }}</span>
      </div>
      <div class="pbs-stat">
        <span class="pbs-stat-label">{{ t('pbsBackup.falliti') }}</span>
        <span class="pbs-stat-val text-danger">{{ stats.failed }}</span>
      </div>
    </section>

    <nav class="pbs-tabs">
      <button
        v-for="tab in tabs" :key="tab.id" class="pbs-tab" :class="{ active: activeTab === tab.id }" @click="activeTab = tab.id">
        {{ tab.label }}
        <span v-if="tab.count != null" class="pbs-tab-count">{{ tab.count }}</span>
      </button>
    </nav>

    <main class="pbs-main">
      <div v-if="activeTab === 'overview'" class="pbs-overview">
        <div class="info-banner mb-4">
          <div class="icon"><Icon name="shield" :size="20" /></div>
          <div class="content">
            <strong>{{ t('pbsBackup.vs') }}</strong>
            <p>
              <i18n-t keypath="pbsBackup.vsNota" tag="span"><template #link><router-link :to="{ name: 'replication', query: { tab: 'recovery_pbs' } }">{{ t('pbs.linkRepliche') }}</router-link></template></i18n-t>
            </p>
          </div>
        </div>
        <div class="pbs-quick-actions">
          <button class="btn btn-primary" @click="openCreateJob">{{ t('pbsBackup.nuovo') }}</button>
          <button class="btn btn-secondary" @click="activeTab = 'inventory'">{{ t('pbsBackup.inventario') }}</button>
          <router-link :to="{ name: 'settings' }" class="btn btn-secondary">{{ t('pbsBackup.smtp') }}</router-link>
        </div>
        <div v-if="failedJobs.length" class="alert alert-danger mt-4">
          <strong>{{ t('pbsBackup.nFalliti', { n: failedJobs.length }) }}</strong>
          <ul class="mt-2 mb-0">
            <li v-for="j in failedJobs.slice(0, 5)" :key="j.id">
              {{ j.name }} (VM {{ j.vm_id }})
              <button class="btn btn-xs btn-secondary ml-2" @click="onEdit(j)">{{ t('pbsBackup.apri') }}</button>
            </li>
          </ul>
        </div>
      </div>

      <div v-else-if="activeTab === 'jobs'">
        <div class="flex justify-between items-center mb-4">
          <p class="muted mb-0">{{ t('pbsBackup.jobNota') }}</p>
          <button class="btn btn-primary" @click="openCreateJob">{{ t('pbsBackup.nuovoJob') }}</button>
        </div>
        <JobsList
          :jobs="backupJobs"
          :loading="loadingJobs"
          @refresh="reloadJobs"
          @edit="onEdit"
          @run="onRun"
          @delete="onDelete"
          @show-log="onShowLog"
          @toggle-active="onToggleActive"
        />
      </div>

      <PBSInventoryPanel v-else-if="activeTab === 'inventory'" />

      <div v-else-if="activeTab === 'logs'">
        <p class="muted mb-4">{{ t('pbsBackup.logNota') }}</p>
        <div v-if="loadingLogs" class="empty-state">{{ t('pbsBackup.logCarico') }}</div>
        <table v-else class="data-table">
          <thead>
            <tr>
              <th>{{ t('comune.data') }}</th>
              <th>{{ t('comune.tipo') }}</th>
              <th>{{ t('comune.stato') }}</th>
              <th>{{ t('comune.messaggio') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="log in logs" :key="log.id">
              <td>{{ formatDate(log.started_at) }}</td>
              <td><span class="badge badge-outline">{{ log.job_type }}</span></td>
              <td>
                <span class="badge" :class="statusBadge(log.status)">{{ log.status }}</span>
              </td>
              <td class="log-msg">{{ log.message }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="!loadingLogs && logs.length === 0" class="empty-state">{{ t('pbsBackup.logNessuno') }}</p>
      </div>
    </main>

    <JobModal
      v-model:visible="modalVisible"
      mode="backup_pbs"
      :job="editingJob"
      @saved="onSaved"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '../components/ui/PageHeader.vue'
import Icon from '../components/ui/Icon.vue'
import JobsList from '../components/jobs/JobsList.vue'
import JobModal from '../components/jobs/JobModal.vue'
import PBSInventoryPanel from '../components/pbs/PBSInventoryPanel.vue'
import backupJobsService, { type BackupJob } from '../services/backupJobs'
import logsService, { type JobLog } from '../services/logs'
import { useReplicationStore, type UnifiedJob } from '../stores/replication'
import { confirmDangerous } from '../stores/confirm'
import { useToast, errorMessage } from '../stores/toast'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const route = useRoute()
const router = useRouter()
const toast = useToast()
const store = useReplicationStore()

type TabId = 'overview' | 'jobs' | 'inventory' | 'logs'
const activeTab = ref<TabId>('overview')
const stats = ref({ total: 0, active: 0, running: 0, failed: 0, scheduled: 0 })
const backupJobsRaw = ref<BackupJob[]>([])
const loadingJobs = ref(false)
const logs = ref<JobLog[]>([])
const loadingLogs = ref(false)
const modalVisible = ref(false)
const editingJob = ref<UnifiedJob | null>(null)

const tabs = computed(() => [
  { id: 'overview' as TabId, label: t('pbsBackup.tPanoramica'), count: null },
  { id: 'jobs' as TabId, label: t('pbsBackup.jobBackup'), count: stats.value.total },
  { id: 'inventory' as TabId, label: t('pbsBackup.inventario'), count: null },
  { id: 'logs' as TabId, label: t('pbsBackup.tLog'), count: null },
])

const backupJobs = computed<UnifiedJob[]>(() =>
  backupJobsRaw.value.map(j => ({
    kind: 'backup_pbs' as const,
    id: j.id,
    name: j.name,
    vm_id: j.vm_id,
    vm_name: j.vm_name,
    vm_type: j.vm_type,
    source_node_id: j.source_node_id,
    source_node_name: j.source_node_name,
    pbs_node_id: j.pbs_node_id,
    pbs_node_name: j.pbs_node_name,
    pbs_datastore: j.pbs_datastore,
    schedule: j.schedule,
    schedule_config: j.schedule_config,
    is_active: j.is_active,
    last_run: j.last_run,
    last_status: j.last_status,
    current_status: j.current_status,
    raw: j,
  }) as UnifiedJob),
)

const failedJobs = computed(() =>
  backupJobs.value.filter(j => ['failed', 'error'].includes((j.last_status || '').toLowerCase())),
)

function applyRouteQuery() {
  const tab = route.query.tab as string
  if (tab === 'jobs' || tab === 'inventory' || tab === 'logs' || tab === 'overview') {
    activeTab.value = tab
  }
  if (route.query.action === 'create') {
    openCreateJob()
    router.replace({ query: { tab: activeTab.value } })
  }
}

watch(activeTab, (tab) => {
  router.replace({ query: { ...route.query, tab } })
  if (tab === 'logs') loadLogs()
})

async function reloadStats() {
  try {
    const { data } = await backupJobsService.getStats()
    stats.value = data
  } catch {
    /* ignore */
  }
}

async function reloadJobs() {
  loadingJobs.value = true
  try {
    const { data } = await backupJobsService.getJobs()
    backupJobsRaw.value = data
    await reloadStats()
  } finally {
    loadingJobs.value = false
  }
}

async function loadLogs() {
  loadingLogs.value = true
  try {
    const types = ['backup', 'restore', 'recovery']
    const results = await Promise.all(
      types.map(t => logsService.getLogs({ job_type: t, limit: 20 }).catch(() => ({ data: [] }))),
    )
    const merged = results.flatMap(r => r.data as JobLog[])
    merged.sort((a, b) => {
      const ta = new Date(a.started_at || 0).getTime()
      const tb = new Date(b.started_at || 0).getTime()
      return tb - ta
    })
    logs.value = merged.slice(0, 50)
  } finally {
    loadingLogs.value = false
  }
}

function openCreateJob() {
  editingJob.value = null
  modalVisible.value = true
  activeTab.value = 'jobs'
}

function onEdit(j: UnifiedJob) {
  editingJob.value = j
  modalVisible.value = true
}

async function onRun(j: UnifiedJob) {
  try {
    await backupJobsService.runJob(String(j.id))
    toast.success(t('pbsBackup.avviato'))
    setTimeout(reloadJobs, 800)
  } catch (e) {
    toast.error(t('pbsBackup.erroreAvvio'), errorMessage(e))
  }
}

async function onToggleActive(j: UnifiedJob) {
  const newActive = j.is_active === false
  if (!await confirmDangerous(newActive ? t('repliche.attivare', { nome: j.name }) : t('repliche.disattivare', { nome: j.name }))) return
  try {
    await backupJobsService.updateJob(String(j.id), { is_active: newActive })
    await reloadJobs()
  } catch (e) {
    toast.error(t('comune.errore'), errorMessage(e))
  }
}

async function onDelete(j: UnifiedJob) {
  if (!await confirmDangerous(t('repliche.eliminare', { nome: j.name }))) return
  try {
    await backupJobsService.deleteJob(String(j.id))
    await reloadJobs()
  } catch (e) {
    toast.error(t('comune.erroreEliminazione'), errorMessage(e))
  }
}

function onShowLog() {
  activeTab.value = 'logs'
  loadLogs()
}

function onSaved() {
  modalVisible.value = false
  reloadJobs()
}

function formatDate(v?: string | null) {
  if (!v) return '—'
  return new Date(v).toLocaleString()
}

function statusBadge(s?: string) {
  const x = (s || '').toLowerCase()
  if (x === 'success' || x === 'completed') return 'badge-success'
  if (x === 'failed' || x === 'error') return 'badge-danger'
  if (x === 'running' || x === 'started') return 'badge-warning'
  return 'badge-outline'
}

onMounted(async () => {
  await store.fetchNodes()
  applyRouteQuery()
  await reloadJobs()
  if (activeTab.value === 'logs') loadLogs()
})
</script>

<style scoped>
.pbs-hub {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  padding: var(--space-5);
}
.pbs-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--space-3);
}
.pbs-stat {
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3);
}
.pbs-stat-label {
  font-size: 0.7rem;
  color: var(--color-text-secondary);
  text-transform: uppercase;
}
.pbs-stat-val {
  font-size: 1.5rem;
  font-weight: 700;
  font-family: var(--font-mono);
}
.pbs-tabs {
  display: flex;
  gap: 2px;
  border-bottom: 1px solid var(--color-border);
}
.pbs-tab {
  background: none;
  border: 0;
  padding: var(--space-3) var(--space-4);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  font-weight: 600;
  color: var(--color-text-secondary);
}
.pbs-tab.active {
  color: var(--color-primary);
  border-bottom-color: var(--color-primary);
}
.pbs-tab-count {
  font-size: 0.7rem;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--color-bg-element);
  margin-left: 4px;
}
.pbs-main {
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
}
.pbs-quick-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}
.log-msg {
  max-width: 420px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.text-success { color: var(--color-success-fg); }
.text-warning { color: var(--color-warning-fg); }
.text-danger { color: var(--color-danger-fg); }
</style>
