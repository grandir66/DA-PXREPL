<template>
  <div class="dashboard">
    <PageHeader
      title="Dashboard"
      subtitle="Riepilogo job di replica, backup e metriche dei nodi."
      icon="home"
    >
      <template #actions>
        <button class="btn btn-secondary btn-sm" :disabled="loading" @click="refreshData()">
          <Icon name="refresh" :size="14" :class="{ spin: loading }" />
          {{ loading ? 'Aggiorno…' : 'Aggiorna' }}
        </button>
      </template>
    </PageHeader>

    <section class="kpi-grid">
      <div class="kpi" v-for="k in kpis" :key="k.id">
        <div class="kpi-icon" :class="`kpi-icon-${k.tone}`">
          <Icon :name="k.icon" :size="18" />
        </div>
        <div class="kpi-text">
          <span class="kpi-label">{{ k.label }}</span>
          <span class="kpi-value">{{ k.value }}</span>
          <span class="kpi-detail">{{ k.detail }}</span>
        </div>
      </div>
    </section>

    <section
      v-if="replicationHealth"
      class="card"
      :class="{ 'card-alert': replicationHealth.overdue_count > 0 }"
    >
      <div class="card-head">
        <div>
          <h2 class="card-title">Salute replica</h2>
          <p class="card-sub">
            Job schedulati in ritardo rispetto all'ultimo slot cron (UTC).
          </p>
        </div>
        <span
          class="health-badge"
          :class="replicationHealth.overdue_count > 0 ? 'health-badge-warn' : 'health-badge-ok'"
        >
          {{ replicationHealth.overdue_count > 0
            ? `${replicationHealth.overdue_group_count || replicationHealth.overdue_count} in ritardo`
            : 'Tutto ok' }}
        </span>
        <RouterLink v-if="replicationHealth.overdue_count > 0" to="/replication" class="btn btn-secondary btn-sm">
          Vai a Repliche
        </RouterLink>
      </div>

      <div v-if="replicationHealth.overdue_count === 0" class="health-ok">
        {{ replicationHealth.healthy_count }} job schedulati aggiornati
        <span v-if="scheduleGroups.length"> · {{ scheduleGroups.length }} VM/gruppi monitorati</span>.
      </div>
      <table v-else class="health-table">
        <thead>
          <tr>
            <th>VM / gruppo</th>
            <th>Ultima run</th>
            <th>Prossima run</th>
            <th>Slot saltati</th>
            <th>Ritardo</th>
            <th>Stato</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="group in overdueGroups" :key="group.key">
            <td>
              <strong>{{ group.vm_name || group.key }}</strong>
              <div v-if="group.vm_id" class="health-sub">VMID {{ group.vm_id }} · {{ group.job_count }} job</div>
              <div v-else-if="group.job_count > 1" class="health-sub">{{ group.job_count }} dischi</div>
            </td>
            <td>{{ formatLastRun(group.last_run) }}</td>
            <td>{{ formatLastRun(group.next_run) }}</td>
            <td>{{ group.missed_slots || 0 }}</td>
            <td>{{ formatDelay(group.hours_since_last_run) }}</td>
            <td>
              <span class="badge badge-warning">
                {{ group.last_status === 'failed' ? 'Ultimo fallito' : 'Run mancata' }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>

      <details v-if="scheduleGroups.length" class="schedule-details">
        <summary>Pianificazione VM/gruppi ({{ scheduleGroups.length }})</summary>
        <table class="health-table health-table-compact">
          <thead>
            <tr>
              <th>VM / gruppo</th>
              <th>Ultima run</th>
              <th>Prossima run</th>
              <th>Slot saltati</th>
              <th>Stato</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="group in scheduleGroups" :key="group.key" :class="{ 'row-overdue': group.overdue }">
              <td>
                <strong>{{ group.vm_name || group.key }}</strong>
                <div v-if="group.vm_id" class="health-sub">VMID {{ group.vm_id }}</div>
              </td>
              <td>{{ formatLastRun(group.last_run) }}</td>
              <td>{{ formatLastRun(group.next_run) }}</td>
              <td>{{ group.overdue ? (group.missed_slots || 0) : '—' }}</td>
              <td>
                <span v-if="group.overdue" class="badge badge-warning">In ritardo</span>
                <span v-else class="badge badge-success">Ok</span>
              </td>
            </tr>
          </tbody>
        </table>
      </details>
    </section>

    <section class="card">
      <div class="card-head">
        <div>
          <h2 class="card-title">Performance nodi</h2>
          <p class="card-sub">Snapshot CPU/RAM/load corrente.</p>
        </div>
        <button class="btn btn-secondary btn-sm" :disabled="loadingMetrics" @click="loadNodesMetrics">
          <Icon name="refresh" :size="14" :class="{ spin: loadingMetrics }" />
          Aggiorna
        </button>
      </div>

      <LoadingState v-if="loadingMetrics && !nodesMetrics.length" message="Caricamento metriche…" />
      <EmptyState
        v-else-if="!nodesMetrics.length"
        title="Nessun nodo online"
        message="Le metriche non sono al momento disponibili. Verifica la connettività SSH ai nodi."
        icon="server"
      />
      <table v-else class="metrics-table">
        <thead>
          <tr>
            <th>Nodo</th>
            <th>CPU</th>
            <th>RAM</th>
            <th>Load (1/5/15)</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in nodesMetrics" :key="m.node_id">
            <td><strong>{{ m.node_name }}</strong></td>
            <td>
              <div class="metric-row">
                <div class="bar">
                  <div class="bar-fill" :style="barStyle(m.cpu?.usage_percent || 0)" />
                </div>
                <span class="metric-num">{{ (m.cpu?.usage_percent || 0).toFixed(1) }}%</span>
              </div>
            </td>
            <td>
              <div class="metric-row">
                <div class="bar">
                  <div class="bar-fill" :style="barStyle(m.memory?.usage_percent || 0, 90, 75)" />
                </div>
                <span class="metric-num">{{ (m.memory?.usage_percent || 0).toFixed(1) }}%</span>
              </div>
              <div class="metric-detail">
                {{ (m.memory?.used_gb || 0).toFixed(1) }} / {{ (m.memory?.total_gb || 0).toFixed(1) }} GiB
              </div>
            </td>
            <td>
              <code class="load">
                {{ (m.cpu?.load_1min || 0).toFixed(2) }} ·
                {{ (m.cpu?.load_5min || 0).toFixed(2) }} ·
                {{ (m.cpu?.load_15min || 0).toFixed(2) }}
              </code>
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import dashboardService, {
  type JobStats,
  type NodeMetrics,
  type ReplicationHealth,
} from '../services/dashboard'
import { useToast, errorMessage } from '../stores/toast'
import PageHeader from '../components/ui/PageHeader.vue'
import Icon from '../components/ui/Icon.vue'
import LoadingState from '../components/ui/LoadingState.vue'
import EmptyState from '../components/ui/EmptyState.vue'

const toast = useToast()

const loading = ref(false)
const loadingMetrics = ref(false)
const jobStats = ref<JobStats | null>(null)
const nodesMetrics = ref<NodeMetrics[]>([])
const replicationHealth = ref<ReplicationHealth | null>(null)

const overdueGroups = computed(() =>
  replicationHealth.value?.overdue_groups?.length
    ? replicationHealth.value.overdue_groups
    : (replicationHealth.value?.jobs || []).filter(j => j.overdue).map(j => ({
        key: `job:${j.id}`,
        vm_id: j.vm_id,
        vm_name: j.vm_name || j.name,
        job_count: 1,
        overdue: true,
        missed_slots: j.missed_slots || 0,
        hours_since_last_run: j.hours_since_last_run,
        last_run: j.last_run,
        next_run: j.next_run,
        last_status: j.last_status,
        jobs: [{ id: j.id, name: j.name, disk_name: j.disk_name }],
      }))
)

const scheduleGroups = computed(() => replicationHealth.value?.groups || [])

interface Kpi {
  id: string
  label: string
  value: number
  detail: string
  icon: string
  tone: 'zfs' | 'pbs' | 'info' | 'neutral'
}

const kpis = computed<Kpi[]>(() => {
  const s = (jobStats.value || {}) as any
  return [
    { id: 'zfs',  label: 'Replica ZFS',   value: s.replica_zfs   || 0, detail: 'syncoid',     icon: 'archive',          tone: 'zfs' },
    { id: 'btr',  label: 'Replica BTRFS', value: s.replica_btrfs || 0, detail: 'btrfs send',  icon: 'archive',          tone: 'zfs' },
    { id: 'pbsB', label: 'Backup PBS',    value: s.backup_pbs    || 0, detail: 'pbs backup',  icon: 'database',         tone: 'pbs' },
    { id: 'pbsR', label: 'Replica PBS',   value: s.replica_pbs   || 0, detail: 'pbs restore', icon: 'database',         tone: 'pbs' },
    { id: 'mig',  label: 'Migrazioni',    value: s.migration     || 0, detail: 'migrations',  icon: 'arrow-right-left', tone: 'info' },
    { id: 'tot',  label: 'Totale',        value: s.total         || 0, detail: 'job conf.',   icon: 'list',             tone: 'neutral' },
  ]
})

onMounted(refreshData)

async function refreshData() {
  loading.value = true
  try {
    await Promise.all([loadJobStats(), loadNodesMetrics(), loadReplicationHealth()])
  } finally {
    loading.value = false
  }
}

async function loadReplicationHealth() {
  try {
    const r = await dashboardService.getReplicationHealth()
    replicationHealth.value = r.data
  } catch (e) {
    toast.error('Impossibile caricare salute replica', errorMessage(e))
  }
}

async function loadJobStats() {
  try {
    const r = await dashboardService.getJobStats()
    jobStats.value = r.data
  } catch (e) {
    toast.error('Impossibile caricare le statistiche', errorMessage(e))
  }
}

async function loadNodesMetrics() {
  loadingMetrics.value = true
  try {
    const r = await dashboardService.getNodesMetrics()
    nodesMetrics.value = r.data
  } catch (e) {
    toast.error('Errore metriche nodi', errorMessage(e))
  } finally {
    loadingMetrics.value = false
  }
}

function barStyle(val: number, danger = 80, warning = 60) {
  let color = 'var(--color-primary)'
  if (val > danger) color = 'var(--color-danger-fg)'
  else if (val > warning) color = 'var(--color-warning-fg)'
  return {
    width: `${Math.min(100, Math.max(0, val))}%`,
    background: color,
  }
}

function formatLastRun(iso?: string | null): string {
  if (!iso) return 'Mai'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

function formatDelay(hours?: number | null): string {
  if (hours == null) return '—'
  if (hours < 24) return `${hours.toFixed(1)} h`
  return `${(hours / 24).toFixed(1)} gg`
}
</script>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--space-3);
}
.kpi {
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.kpi-icon {
  width: 38px;
  height: 38px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.kpi-icon-zfs { background: rgba(115, 183, 86, 0.15); color: var(--color-zfs); }
.kpi-icon-pbs { background: rgba(224, 93, 68, 0.15); color: var(--color-pbs); }
.kpi-icon-info { background: var(--color-info-dim); color: var(--color-info-fg); }
.kpi-icon-neutral { background: var(--color-bg-element); color: var(--color-text-secondary); }
.kpi-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.kpi-label {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--color-text-secondary);
  font-weight: 600;
}
.kpi-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--color-text-primary);
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}
.kpi-detail {
  font-size: 0.72rem;
  color: var(--color-text-secondary);
}

.card {
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
}
.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-bg-body);
  flex-wrap: wrap;
}
.card-title {
  margin: 0;
  font-size: 0.95rem;
  color: var(--color-text-primary);
  font-weight: 600;
}
.card-sub {
  margin: 2px 0 0;
  font-size: 0.78rem;
  color: var(--color-text-secondary);
}

.card-alert {
  border-color: rgba(245, 158, 11, 0.35);
}

.health-badge {
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.25rem 0.6rem;
  border-radius: 999px;
  white-space: nowrap;
}
.health-badge-ok {
  background: rgba(34, 197, 94, 0.15);
  color: var(--color-success-fg, #4ade80);
}
.health-badge-warn {
  background: rgba(245, 158, 11, 0.15);
  color: var(--color-warning-fg, #fbbf24);
}

.health-ok {
  padding: var(--space-3) var(--space-4);
  font-size: 0.86rem;
  color: var(--color-text-secondary);
}

.health-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.86rem;
}
.health-table th {
  text-align: left;
  padding: 10px var(--space-4);
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--color-text-secondary);
  background: var(--color-bg-body);
  border-bottom: 1px solid var(--color-border);
}
.health-table td {
  padding: 10px var(--space-4);
  border-bottom: 1px solid var(--color-border);
  vertical-align: middle;
}
.health-table tr:last-child td {
  border-bottom: 0;
}
.health-sub {
  font-size: 0.72rem;
  color: var(--color-text-secondary);
  margin-top: 2px;
}

.schedule-details {
  border-top: 1px solid var(--color-border);
  padding: var(--space-3) var(--space-4);
}
.schedule-details summary {
  cursor: pointer;
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: var(--space-2);
}
.health-table-compact td,
.health-table-compact th {
  padding: 8px var(--space-4);
}
.row-overdue td {
  background: rgba(245, 158, 11, 0.04);
}

.metrics-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.86rem;
}
.metrics-table th {
  text-align: left;
  padding: 10px var(--space-4);
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--color-text-secondary);
  background: var(--color-bg-body);
  border-bottom: 1px solid var(--color-border);
}
.metrics-table td {
  padding: 10px var(--space-4);
  border-bottom: 1px solid var(--color-border);
  vertical-align: middle;
}
.metrics-table tr:last-child td {
  border-bottom: 0;
}
.metric-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.bar {
  flex: 1;
  height: 8px;
  border-radius: 999px;
  background: var(--color-bg-element);
  overflow: hidden;
  min-width: 80px;
}
.bar-fill {
  height: 100%;
  border-radius: 999px;
  transition: width 0.3s ease;
}
.metric-num {
  min-width: 52px;
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: var(--color-text-primary);
  font-size: 0.82rem;
}
.metric-detail {
  font-size: 0.72rem;
  color: var(--color-text-secondary);
  margin-top: 4px;
  font-family: var(--font-mono);
}
.load {
  font-family: var(--font-mono);
  font-size: 0.8rem;
  color: var(--color-text-secondary);
}

.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
