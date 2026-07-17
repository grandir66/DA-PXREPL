<template>
  <div class="pbs-hub">
    <PageHeader
      title="PBS Backup"
      subtitle="Protezione VM su Proxmox Backup Server — job schedulati, inventario e restore"
      icon="database"
    />

    <section class="pbs-stats">
      <div class="pbs-stat">
        <span class="pbs-stat-label">Job backup</span>
        <span class="pbs-stat-val">{{ stats.total }}</span>
      </div>
      <div class="pbs-stat">
        <span class="pbs-stat-label">Attivi</span>
        <span class="pbs-stat-val text-success">{{ stats.active }}</span>
      </div>
      <div class="pbs-stat">
        <span class="pbs-stat-label">Schedulati</span>
        <span class="pbs-stat-val">{{ stats.scheduled }}</span>
      </div>
      <div class="pbs-stat">
        <span class="pbs-stat-label">In esecuzione</span>
        <span class="pbs-stat-val text-warning">{{ stats.running }}</span>
      </div>
      <div class="pbs-stat">
        <span class="pbs-stat-label">Falliti (ultimo run)</span>
        <span class="pbs-stat-val text-danger">{{ stats.failed }}</span>
      </div>
    </section>

    <nav class="pbs-tabs">
      <button
        v-for="t in tabs"
        :key="t.id"
        class="pbs-tab"
        :class="{ active: activeTab === t.id }"
        @click="activeTab = t.id"
      >
        {{ t.label }}
        <span v-if="t.count != null" class="pbs-tab-count">{{ t.count }}</span>
      </button>
    </nav>

    <main class="pbs-main">
      <div v-if="activeTab === 'overview'" class="pbs-overview">
        <div class="info-banner mb-4">
          <div class="icon">🛡️</div>
          <div class="content">
            <strong>Backup vs replica</strong>
            <p>
              Qui gestisci <strong>backup su PBS</strong> (retention, schedule, alert).
              Per <strong>replicare VM verso un altro nodo</strong> quando non c'è ZFS usa
              <router-link :to="{ name: 'replication', query: { tab: 'recovery_pbs' } }">Repliche → Replica via PBS</router-link>.
            </p>
          </div>
        </div>
        <div class="pbs-quick-actions">
          <button class="btn btn-primary" @click="openCreateJob">+ Nuovo backup PBS</button>
          <button class="btn btn-secondary" @click="activeTab = 'inventory'">Inventario & restore</button>
          <router-link :to="{ name: 'settings' }" class="btn btn-secondary">Configura notifiche SMTP</router-link>
        </div>
        <div v-if="failedJobs.length" class="alert alert-danger mt-4">
          <strong>{{ failedJobs.length }} job con ultimo run fallito</strong>
          <ul class="mt-2 mb-0">
            <li v-for="j in failedJobs.slice(0, 5)" :key="j.id">
              {{ j.name }} (VM {{ j.vm_id }})
              <button class="btn btn-xs btn-secondary ml-2" @click="onEdit(j)">Apri</button>
            </li>
          </ul>
        </div>
      </div>

      <div v-else-if="activeTab === 'jobs'">
        <div class="flex justify-between items-center mb-4">
          <p class="muted mb-0">Job di backup VM verso PBS (senza restore automatico).</p>
          <button class="btn btn-primary" @click="openCreateJob">+ Nuovo job</button>
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
        <p class="muted mb-4">Log backup PBS, restore e replica (ultimi 50).</p>
        <div v-if="loadingLogs" class="empty-state">Caricamento log…</div>
        <table v-else class="data-table">
          <thead>
            <tr>
              <th>Data</th>
              <th>Tipo</th>
              <th>Stato</th>
              <th>Messaggio</th>
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
        <p v-if="!loadingLogs && logs.length === 0" class="empty-state">Nessun log PBS recente.</p>
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
import JobsList from '../components/jobs/JobsList.vue'
import JobModal from '../components/jobs/JobModal.vue'
import PBSInventoryPanel from '../components/pbs/PBSInventoryPanel.vue'
import backupJobsService, { type BackupJob } from '../services/backupJobs'
import logsService, { type JobLog } from '../services/logs'
import { useReplicationStore, type UnifiedJob } from '../stores/replication'
import { confirmDangerous } from '../stores/confirm'
import { useToast, errorMessage } from '../stores/toast'

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
  { id: 'overview' as TabId, label: 'Panoramica', count: null },
  { id: 'jobs' as TabId, label: 'Job backup', count: stats.value.total },
  { id: 'inventory' as TabId, label: 'Inventario & restore', count: null },
  { id: 'logs' as TabId, label: 'Alert & log', count: null },
])

const backupJobs = computed(() =>
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
  })),
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
    toast.success('Backup avviato')
    setTimeout(reloadJobs, 800)
  } catch (e) {
    toast.error('Errore avvio', errorMessage(e))
  }
}

async function onToggleActive(j: UnifiedJob) {
  const newActive = j.is_active === false
  if (!await confirmDangerous(`${newActive ? 'Attivare' : 'Disattivare'} "${j.name}"?`)) return
  try {
    await backupJobsService.updateJob(String(j.id), { is_active: newActive })
    await reloadJobs()
  } catch (e) {
    toast.error('Errore', errorMessage(e))
  }
}

async function onDelete(j: UnifiedJob) {
  if (!await confirmDangerous(`Eliminare "${j.name}"?`)) return
  try {
    await backupJobsService.deleteJob(String(j.id))
    await reloadJobs()
  } catch (e) {
    toast.error('Errore eliminazione', errorMessage(e))
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
