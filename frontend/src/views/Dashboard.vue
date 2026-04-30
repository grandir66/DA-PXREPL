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
import dashboardService, { type JobStats, type NodeMetrics } from '../services/dashboard'
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
    await Promise.all([loadJobStats(), loadNodesMetrics()])
  } finally {
    loading.value = false
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
