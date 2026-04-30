<template>
  <div class="repl-view">
    <header class="repl-head">
      <div class="repl-head-left">
        <h1>Repliche &amp; Backup</h1>
        <p class="repl-sub">
          Gestione unificata di repliche ZFS (Syncoid) e backup/restore via PBS,
          a livello VM.
        </p>
      </div>
      <div class="repl-head-actions">
        <div class="repl-new-wrap" v-click-outside="closeNewMenu">
          <button class="btn btn-primary" @click="newMenuOpen = !newMenuOpen">
            + Nuovo job
            <span class="caret">▾</span>
          </button>
          <ul v-if="newMenuOpen" class="repl-new-menu">
            <li @click="openCreate('syncoid')">
              <span class="kind-dot zfs"></span>
              <div>
                <strong>Replica ZFS (Syncoid)</strong>
                <small>send/receive ZFS tra due nodi PVE</small>
              </div>
            </li>
            <li @click="openCreate('backup_pbs')">
              <span class="kind-dot pbs"></span>
              <div>
                <strong>Backup verso PBS</strong>
                <small>solo backup su Proxmox Backup Server</small>
              </div>
            </li>
            <li @click="openCreate('recovery_pbs')">
              <span class="kind-dot pbs"></span>
              <div>
                <strong>Replica via PBS</strong>
                <small>backup + restore automatico su nodo destinazione</small>
              </div>
            </li>
          </ul>
        </div>
      </div>
    </header>

    <section class="repl-stats">
      <div class="repl-stat">
        <span class="repl-stat-label">Job totali</span>
        <span class="repl-stat-val">{{ store.jobs.length }}</span>
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
        <span class="repl-stat-label">Falliti (ultimo run)</span>
        <span class="repl-stat-val text-danger">{{ failedCount }}</span>
      </div>
    </section>

    <nav class="repl-tabs">
      <button
        v-for="t in tabs"
        :key="t.id"
        class="repl-tab"
        :class="{ active: activeTab === t.id }"
        @click="activeTab = t.id"
      >
        {{ t.label }}
        <span v-if="t.count != null" class="repl-tab-count">{{ t.count }}</span>
      </button>
    </nav>

    <main class="repl-main">
      <!-- Tab "PVE Native" è read-only e usa la view legacy -->
      <PVELegacy v-if="activeTab === 'pve'" />

      <JobsList
        v-else
        :jobs="filteredJobs"
        :loading="store.loadingJobs"
        @refresh="reload"
        @edit="onEdit"
        @run="onRun"
        @delete="onDelete"
      />
    </main>

    <JobModal
      v-model:visible="modalVisible"
      :mode="createKind"
      :job="editingJob"
      @saved="onSaved"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useReplicationStore, type UnifiedJob, type JobKind } from '../stores/replication'
import JobsList from '../components/jobs/JobsList.vue'
import JobModal from '../components/jobs/JobModal.vue'
import PVELegacy from './replication/PVEReplicationJobs.vue'
import syncJobsService from '../services/syncJobs'
import backupJobsService from '../services/backupJobs'
import recoveryJobsService from '../services/recoveryJobs'

const store = useReplicationStore()

const activeTab = ref<'all' | 'syncoid' | 'backup_pbs' | 'recovery_pbs' | 'pve'>('all')
const newMenuOpen = ref(false)

const modalVisible = ref(false)
const editingJob = ref<UnifiedJob | null>(null)
const createKind = ref<JobKind>('syncoid')

const tabs = computed(() => [
  { id: 'all', label: 'Tutti', count: store.jobs.length },
  { id: 'syncoid', label: 'Repliche ZFS', count: store.jobs.filter(j => j.kind === 'syncoid').length },
  { id: 'backup_pbs', label: 'Backup PBS', count: store.jobs.filter(j => j.kind === 'backup_pbs').length },
  { id: 'recovery_pbs', label: 'Replica PBS', count: store.jobs.filter(j => j.kind === 'recovery_pbs').length },
  { id: 'pve', label: 'PVE nativa', count: null },
])

const filteredJobs = computed(() => {
  if (activeTab.value === 'all') return store.jobs
  if (activeTab.value === 'pve') return []
  return store.jobs.filter(j => j.kind === activeTab.value)
})

const activeCount = computed(() => store.jobs.filter(j => j.is_active !== false).length)
const runningCount = computed(() =>
  store.jobs.filter(j => {
    const cs = (j.current_status || '').toLowerCase()
    return ['running', 'backing_up', 'restoring', 'registering'].includes(cs)
  }).length
)
const failedCount = computed(() =>
  store.jobs.filter(j => ['error', 'failed'].includes((j.last_status || '').toLowerCase())).length
)

let pollHandle: number | null = null

async function reload() {
  await store.fetchAll()
}

onMounted(() => {
  reload()
  // Light polling ogni 10s per refresh stato
  pollHandle = window.setInterval(() => store.fetchJobs().catch(() => {}), 10_000)
})
onUnmounted(() => {
  if (pollHandle) window.clearInterval(pollHandle)
})

function openCreate(k: JobKind) {
  createKind.value = k
  editingJob.value = null
  newMenuOpen.value = false
  modalVisible.value = true
}

function onEdit(j: UnifiedJob) {
  editingJob.value = j
  createKind.value = j.kind
  modalVisible.value = true
}

async function onRun(j: UnifiedJob) {
  try {
    if (j.kind === 'syncoid') await syncJobsService.runJob(String(j.id))
    else if (j.kind === 'backup_pbs') await backupJobsService.runJob(String(j.id))
    else if (j.kind === 'recovery_pbs') await recoveryJobsService.runJob(String(j.id))
    setTimeout(reload, 800)
  } catch (e) {
    alert('Errore avvio job: ' + ((e as any)?.response?.data?.detail || (e as any)?.message))
  }
}

async function onDelete(j: UnifiedJob) {
  if (!confirm(`Eliminare il job "${j.name}"?`)) return
  try {
    if (j.kind === 'syncoid') await syncJobsService.deleteJob(String(j.id))
    else if (j.kind === 'backup_pbs') await backupJobsService.deleteJob(String(j.id))
    else if (j.kind === 'recovery_pbs') await recoveryJobsService.deleteJob(String(j.id))
    await reload()
  } catch (e) {
    alert('Errore eliminazione: ' + ((e as any)?.response?.data?.detail || (e as any)?.message))
  }
}

function onSaved() {
  modalVisible.value = false
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
</style>
