<template>
  <div class="dashboard">
    <PageHeader
      title="Dashboard"
      :subtitle="headerSubtitle"
      icon="home"
    >
      <template #actions>
        <button class="btn btn-secondary btn-sm" :disabled="loading" @click="refreshData()">
          <Icon name="refresh" :size="14" :class="{ spin: loading }" />
          {{ loading ? 'Aggiorno…' : 'Aggiorna' }}
        </button>
      </template>
    </PageHeader>

    <section v-if="healthStrip.length" class="health-strip">
      <div
        v-for="item in healthStrip"
        :key="item.id"
        class="health-strip-item"
        :class="`health-strip-${item.tone}`"
      >
        <Icon :name="item.icon" :size="16" />
        <div class="health-strip-text">
          <span class="health-strip-value">{{ item.value }}</span>
          <span class="health-strip-label">{{ item.label }}</span>
        </div>
      </div>
    </section>

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

      <div v-if="replicationHealth.overdue_count === 0 && !runningJobs.length" class="health-ok">
        {{ replicationHealth.healthy_count }} job schedulati aggiornati
        <span v-if="scheduleGroups.length"> · {{ scheduleGroups.length }} VM/gruppi monitorati</span>.
      </div>

      <div v-if="runningJobs.length" class="health-running">
        <strong>{{ runningJobs.length }} replica in corso</strong>
        <ul class="running-list">
          <li v-for="job in runningJobs" :key="job.id">
            {{ job.vm_name || job.name }}
            <span v-if="job.vm_id" class="health-sub">VMID {{ job.vm_id }}</span>
          </li>
        </ul>
        <RouterLink to="/replication" class="btn btn-secondary btn-sm">Apri Repliche</RouterLink>
      </div>

      <table v-if="replicationHealth.overdue_count > 0" class="health-table">
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
          <p class="card-sub">Snapshot live CPU/RAM/rete/disco · aggiornamento automatico ogni 30s.</p>
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
            <th>Trend CPU</th>
            <th>CPU</th>
            <th>RAM</th>
            <th>Rete ↓/↑</th>
            <th>Disco R/W</th>
            <th>Load (1/5/15)</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in nodesMetrics" :key="m.node_id">
            <td><strong>{{ m.node_name }}</strong></td>
            <td>
              <MetricSparkline
                :values="cpuHistory[nodeKey(m)] || []"
                :title="`CPU ${m.node_name}`"
              />
            </td>
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
              <div class="io-metric">{{ formatIoRate(m, 'net') }}</div>
              <div class="metric-detail">{{ primaryIfaceName(m) }}</div>
            </td>
            <td>
              <div class="io-metric">{{ formatIoRate(m, 'disk') }}</div>
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
import { computed, onMounted, onUnmounted, ref } from 'vue'
import dashboardService, {
  type JobStats,
  type NodeMetrics,
  type ReplicationHealth,
  type DashboardOverview,
} from '../services/dashboard'
import { useToast, errorMessage } from '../stores/toast'
import PageHeader from '../components/ui/PageHeader.vue'
import Icon from '../components/ui/Icon.vue'
import LoadingState from '../components/ui/LoadingState.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import MetricSparkline from '../components/ui/MetricSparkline.vue'
import nodesService from '../services/nodes'

const POLL_MS = 30_000
const OVERVIEW_POLL_MS = 60_000
const HISTORY_MAX = 20

const toast = useToast()

const loading = ref(false)
const loadingMetrics = ref(false)
const jobStats = ref<JobStats | null>(null)
const nodesMetrics = ref<NodeMetrics[]>([])
const replicationHealth = ref<ReplicationHealth | null>(null)
const overview = ref<DashboardOverview | null>(null)
const nodeInventory = ref<{ total: number; offline: number }>({ total: 0, offline: 0 })
const lastUpdated = ref<Date | null>(null)
const cpuHistory = ref<Record<string, number[]>>({})
const ioRates = ref<Record<string, { netRx: number; netTx: number; diskRead: number; diskWrite: number }>>({})

interface IoSample {
  ts: number
  netRx: number
  netTx: number
  diskRead: number
  diskWrite: number
}

const ioSamples = new Map<string, IoSample>()
let pollTimer: ReturnType<typeof setInterval> | null = null
let overviewTimer: ReturnType<typeof setInterval> | null = null

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

const runningJobs = computed(() => replicationHealth.value?.running_jobs || [])

const headerSubtitle = computed(() => {
  const base = 'Riepilogo job di replica, backup e metriche dei nodi.'
  if (!lastUpdated.value) return base
  const t = lastUpdated.value.toLocaleTimeString()
  return `${base} Ultimo aggiornamento: ${t}.`
})

interface HealthStripItem {
  id: string
  label: string
  value: string | number
  icon: string
  tone: 'ok' | 'warn' | 'danger' | 'info'
}

const healthStrip = computed<HealthStripItem[]>(() => {
  const items: HealthStripItem[] = []
  const rh = replicationHealth.value
  const inv = nodeInventory.value
  const ov = overview.value

  if (inv.total > 0) {
    items.push({
      id: 'nodes',
      label: 'Nodi online',
      value: `${inv.total - inv.offline}/${inv.total}`,
      icon: 'server',
      tone: inv.offline > 0 ? 'danger' : 'ok',
    })
  }

  if (rh) {
    items.push({
      id: 'replica',
      label: 'Replica in ritardo',
      value: rh.overdue_count,
      icon: 'alert-triangle',
      tone: rh.overdue_count > 0 ? 'warn' : 'ok',
    })
    if (rh.running_count > 0) {
      items.push({
        id: 'running',
        label: 'Replica in corso',
        value: rh.running_count,
        icon: 'refresh',
        tone: 'info',
      })
    }
  }

  const hotNodes = nodesMetrics.value.filter((m) => (m.cpu?.usage_percent || 0) >= 85).length
  if (hotNodes > 0) {
    items.push({
      id: 'hot-cpu',
      label: 'Nodi CPU ≥85%',
      value: hotNodes,
      icon: 'cpu',
      tone: 'warn',
    })
  }

  if (ov && ov.total_vms > 0) {
    items.push({
      id: 'vms',
      label: 'VM attive',
      value: `${ov.running_vms}/${ov.total_vms}`,
      icon: 'monitor',
      tone: 'info',
    })
  }

  return items
})

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

onMounted(() => {
  refreshData()
  loadOverview(true)
  pollTimer = setInterval(() => refreshData(true), POLL_MS)
  overviewTimer = setInterval(() => loadOverview(true), OVERVIEW_POLL_MS)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (overviewTimer) clearInterval(overviewTimer)
})

async function refreshData(silent = false) {
  if (!silent) loading.value = true
  try {
    await Promise.all([
      loadJobStats(silent),
      loadNodesMetrics(silent),
      loadReplicationHealth(silent),
      loadNodeInventory(silent),
    ])
    lastUpdated.value = new Date()
  } finally {
    if (!silent) loading.value = false
  }
}

async function loadOverview(silent = false) {
  try {
    const r = await dashboardService.getOverview()
    overview.value = r.data
  } catch (e) {
    if (!silent) toast.error('Impossibile caricare overview', errorMessage(e))
  }
}

async function loadNodeInventory(silent = false) {
  try {
    const r = await nodesService.getNodes()
    const list = r.data || []
    nodeInventory.value = {
      total: list.length,
      offline: list.filter((n) => !n.is_online).length,
    }
  } catch (e) {
    if (!silent) toast.error('Impossibile caricare inventario nodi', errorMessage(e))
  }
}

async function loadReplicationHealth(silent = false) {
  try {
    const r = await dashboardService.getReplicationHealth()
    replicationHealth.value = r.data
  } catch (e) {
    if (!silent) toast.error('Impossibile caricare salute replica', errorMessage(e))
  }
}

async function loadJobStats(silent = false) {
  try {
    const r = await dashboardService.getJobStats()
    jobStats.value = r.data
  } catch (e) {
    if (!silent) toast.error('Impossibile caricare le statistiche', errorMessage(e))
  }
}

async function loadNodesMetrics(silent = false) {
  if (!silent) loadingMetrics.value = true
  try {
    const r = await dashboardService.getNodesMetrics()
    pushCpuHistory(r.data)
    updateIoRates(r.data)
    nodesMetrics.value = r.data
  } catch (e) {
    if (!silent) toast.error('Errore metriche nodi', errorMessage(e))
  } finally {
    if (!silent) loadingMetrics.value = false
  }
}

function pushCpuHistory(metrics: NodeMetrics[]) {
  const next = { ...cpuHistory.value }
  for (const m of metrics) {
    const key = nodeKey(m)
    const cpu = m.cpu?.usage_percent
    if (!Number.isFinite(cpu)) continue
    const arr = [...(next[key] || []), cpu as number]
    next[key] = arr.length > HISTORY_MAX ? arr.slice(-HISTORY_MAX) : arr
  }
  cpuHistory.value = next
}

function nodeKey(m: NodeMetrics): string {
  return String(m.node_id)
}

function primaryIface(m: NodeMetrics) {
  return m.network?.interfaces?.[0]
}

function primaryIfaceName(m: NodeMetrics): string {
  return primaryIface(m)?.name || '—'
}

function updateIoRates(metrics: NodeMetrics[]) {
  const now = Date.now()
  const next: typeof ioRates.value = {}

  for (const m of metrics) {
    const key = nodeKey(m)
    const iface = primaryIface(m)
    const netRx = iface?.rx_bytes ?? 0
    const netTx = iface?.tx_bytes ?? 0
    const diskRead = m.disk?.io_read_bytes ?? 0
    const diskWrite = m.disk?.io_write_bytes ?? 0

    const prev = ioSamples.get(key)
    if (prev && now > prev.ts) {
      const secs = (now - prev.ts) / 1000
      if (secs > 0) {
        next[key] = {
          netRx: Math.max(0, (netRx - prev.netRx) / secs),
          netTx: Math.max(0, (netTx - prev.netTx) / secs),
          diskRead: Math.max(0, (diskRead - prev.diskRead) / secs),
          diskWrite: Math.max(0, (diskWrite - prev.diskWrite) / secs),
        }
      }
    }

    ioSamples.set(key, { ts: now, netRx, netTx, diskRead, diskWrite })
  }

  ioRates.value = { ...ioRates.value, ...next }
}

function formatBytesPerSec(bps: number): string {
  if (!bps || bps <= 0) return '0 B/s'
  const units = ['B/s', 'KiB/s', 'MiB/s', 'GiB/s']
  let v = bps
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v >= 100 ? v.toFixed(0) : v.toFixed(1)} ${units[i]}`
}

function formatIoRate(m: NodeMetrics, kind: 'net' | 'disk'): string {
  const key = nodeKey(m)
  const rates = ioRates.value[key]
  if (!rates) return '—'

  if (kind === 'net') {
    return `${formatBytesPerSec(rates.netRx)} / ${formatBytesPerSec(rates.netTx)}`
  }
  return `${formatBytesPerSec(rates.diskRead)} / ${formatBytesPerSec(rates.diskWrite)}`
}

function barStyle(val: number, danger = 85, warning = 70) {
  let color = 'var(--color-primary)'
  if (val >= danger) color = 'var(--color-danger-fg)'
  else if (val >= warning) color = 'var(--color-warning-fg)'
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

.health-strip {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}
.health-strip-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  background: var(--color-bg-surface);
  min-width: 140px;
}
.health-strip-ok { border-color: rgba(34, 197, 94, 0.25); }
.health-strip-warn { border-color: rgba(245, 158, 11, 0.35); }
.health-strip-danger { border-color: rgba(248, 113, 113, 0.35); }
.health-strip-info { border-color: rgba(59, 130, 246, 0.25); }
.health-strip-text {
  display: flex;
  flex-direction: column;
  line-height: 1.1;
}
.health-strip-value {
  font-size: 1.1rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--color-text-primary);
}
.health-strip-label {
  font-size: 0.68rem;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
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

.health-running {
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
  background: rgba(59, 130, 246, 0.06);
  font-size: 0.86rem;
}
.running-list {
  margin: var(--space-2) 0 var(--space-3);
  padding-left: 1.2rem;
  color: var(--color-text-secondary);
}
.running-list li {
  margin: 0.2rem 0;
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
.io-metric {
  font-family: var(--font-mono);
  font-size: 0.78rem;
  color: var(--color-text-primary);
  white-space: nowrap;
}
.load {
  font-family: var(--font-mono);
  font-size: 0.8rem;
  color: var(--color-text-secondary);
}

.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
