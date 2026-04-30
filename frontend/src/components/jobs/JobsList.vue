<template>
  <div class="jobs-list">
    <div class="jl-toolbar">
      <input
        v-model="filter"
        type="text"
        class="form-input jl-search"
        placeholder="Filtra per VM, nodo, nome…"
      />
      <select v-model="statusFilter" class="form-input jl-status">
        <option value="all">Tutti gli stati</option>
        <option value="active">Solo attivi</option>
        <option value="paused">Disattivati</option>
        <option value="failed">Falliti</option>
        <option value="success">Successo</option>
        <option value="running">In esecuzione</option>
      </select>
      <button class="btn btn-secondary btn-sm" @click="$emit('refresh')" :disabled="loading">
        <span v-if="loading">Aggiorno…</span>
        <span v-else>↻ Aggiorna</span>
      </button>
    </div>

    <div v-if="loading && groups.length === 0" class="jl-empty">Caricamento…</div>
    <div v-else-if="groups.length === 0" class="jl-empty">
      Nessun job da mostrare con i filtri attuali.
    </div>

    <table v-else class="jl-table">
      <thead>
        <tr>
          <th class="jl-col-vm">VM / Job</th>
          <th class="jl-col-route">Sorgente → Destinazione</th>
          <th>Schedule</th>
          <th>Ultimo run</th>
          <th>Stato</th>
          <th class="jl-col-actions">Azioni</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="g in groups" :key="g.key">
          <tr
            class="jl-row jl-vm-row"
            :class="{ expanded: expanded.has(g.key) }"
            @click="toggle(g)"
          >
            <td>
              <button
                v-if="g.jobs.length > 1"
                class="jl-toggle"
                :aria-expanded="expanded.has(g.key)"
                @click.stop="toggle(g)"
              >
                {{ expanded.has(g.key) ? '▾' : '▸' }}
              </button>
              <span v-else class="jl-toggle-spacer"></span>
              <div class="jl-vm-block">
                <span v-if="g.vm_id" class="jl-vm-id">#{{ g.vm_id }}</span>
                <span class="jl-vm-name">{{ g.vm_name || (g.jobs[0].name) }}</span>
                <span
                  v-if="g.vm_type"
                  class="jl-vm-type"
                  :class="`type-${g.vm_type}`"
                >{{ g.vm_type }}</span>
                <span class="jl-job-count" v-if="g.jobs.length > 1">
                  {{ g.jobs.length }} job
                </span>
              </div>
            </td>
            <td>
              <div class="jl-route">
                <span class="jl-node">{{ routeSrc(g.jobs[0]) }}</span>
                <span class="jl-arrow">→</span>
                <span class="jl-node">{{ routeDst(g.jobs[0]) }}</span>
              </div>
            </td>
            <td>
              <span class="jl-schedule">{{ humanSchedule(g.jobs[0]) }}</span>
            </td>
            <td>
              <span class="jl-run">{{ formatRun(g.jobs[0].last_run) }}</span>
            </td>
            <td>
              <span class="jl-status" :class="`s-${groupStatus(g)}`">
                <span class="status-dot" /> {{ statusLabel(groupStatus(g)) }}
              </span>
              <span v-if="g.jobs.some(j => !j.is_active)" class="badge badge-outline">disattivato</span>
            </td>
            <td class="jl-actions" @click.stop>
              <button
                class="btn btn-secondary btn-sm"
                @click="$emit('run', g.jobs[0])"
                :disabled="g.jobs.length > 1"
                title="Esegui ora"
              >▶</button>
              <button
                class="btn btn-secondary btn-sm"
                @click="$emit('edit', g.jobs[0])"
                title="Modifica"
              >✎</button>
              <button
                class="btn btn-danger btn-sm"
                @click="$emit('delete', g.jobs[0])"
                title="Elimina"
              >×</button>
            </td>
          </tr>
          <template v-if="expanded.has(g.key) && g.jobs.length > 1">
            <tr v-for="j in g.jobs" :key="`${g.key}-${j.kind}-${j.id}`" class="jl-row jl-job-row">
              <td>
                <span class="jl-toggle-spacer"></span>
                <span class="jl-job-kind" :class="`kind-${j.kind}`">{{ kindShort(j.kind) }}</span>
                <span class="jl-job-name">{{ j.name }}</span>
              </td>
              <td>
                <div class="jl-route subtle">
                  <span>{{ j.source_dataset || j.source_storage || routeSrc(j) }}</span>
                  <span class="jl-arrow">→</span>
                  <span>{{ j.dest_dataset || j.pbs_datastore || routeDst(j) }}</span>
                </div>
              </td>
              <td><span class="jl-schedule subtle">{{ humanSchedule(j) }}</span></td>
              <td><span class="jl-run subtle">{{ formatRun(j.last_run) }}</span></td>
              <td>
                <span class="jl-status" :class="`s-${jobStatus(j)}`">
                  <span class="status-dot" /> {{ statusLabel(jobStatus(j)) }}
                </span>
              </td>
              <td class="jl-actions">
                <button class="btn btn-secondary btn-sm" @click="$emit('run', j)" title="Esegui">▶</button>
                <button class="btn btn-secondary btn-sm" @click="$emit('edit', j)" title="Modifica">✎</button>
                <button class="btn btn-danger btn-sm" @click="$emit('delete', j)" title="Elimina">×</button>
              </td>
            </tr>
          </template>
        </template>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { UnifiedJob, JobKind } from '../../stores/replication'
import scheduleService from '../../services/schedule'

interface JobGroup {
  key: string
  vm_id?: number | string
  vm_name?: string
  vm_type?: string
  jobs: UnifiedJob[]
}

const props = withDefaults(
  defineProps<{
    jobs: UnifiedJob[]
    loading?: boolean
  }>(),
  {
    loading: false,
  }
)

defineEmits<{
  (e: 'edit', j: UnifiedJob): void
  (e: 'run', j: UnifiedJob): void
  (e: 'delete', j: UnifiedJob): void
  (e: 'refresh'): void
}>()

const filter = ref('')
const statusFilter = ref<'all' | 'active' | 'paused' | 'failed' | 'success' | 'running'>('all')
const expanded = ref<Set<string>>(new Set())

const groups = computed<JobGroup[]>(() => {
  const q = filter.value.trim().toLowerCase()
  const filtered = props.jobs.filter(j => {
    if (q) {
      const hay = [
        j.name,
        j.vm_name,
        String(j.vm_id ?? ''),
        j.source_node_name,
        j.dest_node_name,
        j.pbs_node_name,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      if (!hay.includes(q)) return false
    }
    if (statusFilter.value !== 'all') {
      const s = jobStatus(j)
      if (statusFilter.value === 'active' && j.is_active === false) return false
      if (statusFilter.value === 'paused' && j.is_active !== false) return false
      if (
        ['failed', 'success', 'running'].includes(statusFilter.value) &&
        s !== statusFilter.value
      )
        return false
    }
    return true
  })

  const out: JobGroup[] = []
  const idx = new Map<string, JobGroup>()
  for (const j of filtered) {
    const key =
      j.vm_id != null
        ? `vm:${j.vm_id}:${j.kind === 'syncoid' && j.raw?.vm_group_id ? j.raw.vm_group_id : 'all'}`
        : `solo:${j.kind}:${j.id}`
    let g = idx.get(key)
    if (!g) {
      g = { key, vm_id: j.vm_id, vm_name: j.vm_name, vm_type: j.vm_type, jobs: [] }
      idx.set(key, g)
      out.push(g)
    }
    g.jobs.push(j)
  }
  return out
})

function toggle(g: JobGroup) {
  if (g.jobs.length === 1) return
  if (expanded.value.has(g.key)) expanded.value.delete(g.key)
  else expanded.value.add(g.key)
  // forza reattività
  expanded.value = new Set(expanded.value)
}

function jobStatus(j: UnifiedJob): 'success' | 'failed' | 'running' | 'idle' {
  const cur = (j.current_status || '').toLowerCase()
  if (['running', 'backing_up', 'restoring', 'registering'].includes(cur)) return 'running'
  const last = (j.last_status || '').toLowerCase()
  if (['success', 'completed', 'ok'].includes(last)) return 'success'
  if (['error', 'failed'].includes(last)) return 'failed'
  return 'idle'
}

function groupStatus(g: JobGroup): 'success' | 'failed' | 'running' | 'idle' {
  if (g.jobs.some(j => jobStatus(j) === 'running')) return 'running'
  if (g.jobs.some(j => jobStatus(j) === 'failed')) return 'failed'
  if (g.jobs.every(j => jobStatus(j) === 'success')) return 'success'
  return 'idle'
}

function statusLabel(s: string): string {
  return {
    success: 'Successo',
    failed: 'Fallito',
    running: 'In esecuzione',
    idle: 'In attesa',
  }[s] || s
}

const humanCache = new Map<string, string>()
function humanSchedule(j: UnifiedJob) {
  const cfg = j.schedule_config
  if (cfg && cfg.kind) {
    const key = JSON.stringify(cfg)
    if (humanCache.has(key)) return humanCache.get(key)!
    // best-effort sincrono: uso una traduzione locale leggera
    const out = humanizeLocal(cfg)
    humanCache.set(key, out)
    return out
  }
  if (j.schedule) return j.schedule
  return 'Manuale'
}

function humanizeLocal(cfg: any): string {
  switch (cfg.kind) {
    case 'manual':
      return 'Manuale'
    case 'hourly':
      return `Ogni ora :${String(cfg.minute ?? 0).padStart(2, '0')}`
    case 'every_n_hours':
      return `Ogni ${cfg.hours}h :${String(cfg.minute ?? 0).padStart(2, '0')}`
    case 'daily':
      return `Giornaliero · ${cfg.time}`
    case 'every_n_days':
      return `Ogni ${cfg.days}g · ${cfg.time}`
    case 'weekly': {
      const labels: Record<string, string> = { mon: 'Lun', tue: 'Mar', wed: 'Mer', thu: 'Gio', fri: 'Ven', sat: 'Sab', sun: 'Dom' }
      const days = (cfg.weekdays || []).map((d: string) => labels[d] || d).join(', ')
      return `Settim. (${days}) · ${cfg.time}`
    }
    case 'monthly':
      return `Mensile · giorno ${cfg.day_of_month} · ${cfg.time}`
    case 'advanced':
      return `Avanzato: ${cfg.cron}`
  }
  return cfg.cron || '—'
}

function formatRun(iso?: string | null) {
  if (!iso) return 'mai'
  try {
    return new Date(iso).toLocaleString('it-IT', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function routeSrc(j: UnifiedJob) {
  if (j.kind === 'syncoid') return j.source_node_name || '?'
  if (j.kind === 'backup_pbs') return j.source_node_name || '?'
  if (j.kind === 'recovery_pbs') return `${j.source_node_name || '?'} → ${j.pbs_node_name || 'PBS'}`
  return '?'
}
function routeDst(j: UnifiedJob) {
  if (j.kind === 'syncoid') return j.dest_node_name || '?'
  if (j.kind === 'backup_pbs') return `${j.pbs_node_name || 'PBS'}/${j.pbs_datastore || ''}`
  if (j.kind === 'recovery_pbs') return j.dest_node_name || '?'
  return '?'
}

function kindShort(k: JobKind) {
  return k === 'syncoid' ? 'ZFS' : k === 'backup_pbs' ? 'PBS-B' : 'PBS-R'
}
</script>

<style scoped>
.jobs-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.jl-toolbar {
  display: flex;
  gap: var(--space-2);
  align-items: center;
}
.jl-search {
  flex: 1;
  min-width: 200px;
}
.jl-status {
  max-width: 200px;
}
.jl-empty {
  padding: var(--space-5);
  text-align: center;
  color: var(--color-text-secondary);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-md);
}

.jl-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.86rem;
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
}
.jl-table thead th {
  text-align: left;
  background: var(--color-bg-body);
  color: var(--color-text-secondary);
  font-weight: 600;
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 10px 12px;
  border-bottom: 1px solid var(--color-border);
  position: sticky;
  top: 0;
  z-index: 1;
}
.jl-row td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--color-border);
  vertical-align: middle;
}
.jl-row:last-child td {
  border-bottom: 0;
}
.jl-vm-row {
  cursor: pointer;
  transition: background 0.12s;
}
.jl-vm-row:hover {
  background: var(--color-bg-hover);
}
.jl-vm-row.expanded {
  background: var(--color-primary-dim);
}
.jl-job-row td {
  background: var(--color-bg-body);
  font-size: 0.8rem;
  color: var(--color-text-secondary);
}
.jl-job-row td:first-child {
  padding-left: 40px;
}

.jl-toggle {
  background: none;
  border: 0;
  color: var(--color-text-secondary);
  font-size: 0.9rem;
  cursor: pointer;
  margin-right: 6px;
  width: 18px;
  display: inline-block;
}
.jl-toggle-spacer {
  display: inline-block;
  width: 24px;
}
.jl-vm-block {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}
.jl-vm-id {
  font-family: var(--font-mono);
  color: var(--color-text-secondary);
  font-size: 0.8rem;
}
.jl-vm-name {
  font-weight: 600;
  color: var(--color-text-primary);
}
.jl-vm-type {
  font-size: 0.65rem;
  text-transform: uppercase;
  padding: 1px 6px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  color: var(--color-text-secondary);
}
.jl-vm-type.type-qemu {
  border-color: var(--color-info-fg);
  color: var(--color-info-fg);
}
.jl-vm-type.type-lxc {
  border-color: var(--color-zfs);
  color: var(--color-zfs);
}
.jl-job-count {
  font-size: 0.7rem;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--color-bg-element);
  color: var(--color-text-secondary);
}

.jl-job-kind {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  background: var(--color-bg-element);
  color: var(--color-text-secondary);
  margin-right: 6px;
}
.jl-job-kind.kind-syncoid {
  color: var(--color-zfs);
  border: 1px solid var(--color-zfs);
}
.jl-job-kind.kind-backup_pbs,
.jl-job-kind.kind-recovery_pbs {
  color: var(--color-pbs);
  border: 1px solid var(--color-pbs);
}
.jl-job-name {
  font-weight: 500;
}

.jl-route {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 0.85rem;
}
.jl-route.subtle {
  font-family: var(--font-mono);
  font-size: 0.75rem;
}
.jl-arrow {
  color: var(--color-text-tertiary);
}
.jl-node {
  color: var(--color-text-primary);
}

.jl-schedule {
  font-size: 0.82rem;
}
.jl-schedule.subtle {
  color: var(--color-text-secondary);
}
.jl-run {
  color: var(--color-text-secondary);
  font-family: var(--font-mono);
  font-size: 0.78rem;
}

.jl-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.78rem;
  text-transform: capitalize;
}
.jl-status .status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
  display: inline-block;
}
.jl-status.s-success {
  color: var(--color-success-fg);
}
.jl-status.s-failed {
  color: var(--color-danger-fg);
}
.jl-status.s-running {
  color: var(--color-warning-fg);
  animation: pulse 1.4s ease-in-out infinite;
}
.jl-status.s-idle {
  color: var(--color-text-secondary);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}

.jl-actions {
  display: flex;
  gap: 4px;
  justify-content: flex-end;
}
.jl-col-vm {
  width: 28%;
}
.jl-col-route {
  width: 26%;
}
.jl-col-actions {
  width: 130px;
  text-align: right;
}
</style>
