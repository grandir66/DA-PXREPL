<template>
  <div class="pve-replication-jobs">
    <div v-if="summary && summary.total > 0" class="pvesr-banner mb-4">
      <strong>{{ t('pvesr.rilevate', { n: summary.total }) }}</strong>
      <span v-if="summary.unlinked > 0" class="ml-2">
        {{ t('pvesr.nonCollegate', { n: summary.unlinked }) }}
      </span>
      <span v-if="summary.failed > 0" class="text-danger ml-2">
        {{ t('pvesr.conErrori', { n: summary.failed }) }}
      </span>
    </div>

    <div v-if="loading" class="loading-state">{{ t('pvesr.caricamento') }}</div>
    <div v-else-if="jobs.length === 0" class="empty-state">
      <i18n-t keypath="pvesr.vuoto" tag="span"><template #pvesr><code>pvesr</code></template></i18n-t>
      <p class="muted mt-2">
        {{ t('pvesr.vuotoNota') }}
      </p>
    </div>
    <div v-else class="table-container">
      <table class="data-table">
        <thead>
          <tr>
            <th>VM</th>
            <th>{{ t('pvesr.percorso') }}</th>
            <th>{{ t('pvesr.pianificazione') }}</th>
            <th>{{ t('pvesr.stato') }}</th>
            <th>{{ t('pvesr.inDapx') }}</th>
            <th>{{ t('comune.azioni') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="job in jobs" :key="job.id">
            <td>
              <div class="job-id">{{ job.id }}</div>
              <div class="vm-info">
                {{ job.vm_name || `VM ${job.vm}` }}
                <span class="muted">· {{ job.vm_type === 'lxc' ? 'LXC' : 'QEMU' }}</span>
              </div>
            </td>
            <td>
              <code>{{ job.source || '?' }}</code>
              →
              <code>{{ job.target }}</code>
            </td>
            <td>
              <code>{{ job.schedule }}</code>
              <div v-if="job.next_sync" class="next-sync">{{ t('pvesr.prossima', { quando: formatDate(job.next_sync) }) }}</div>
            </td>
            <td>
              <span :class="['status-badge', getStatusClass(job)]">{{ getStatusLabel(job) }}</span>
              <div v-if="job.error" class="error-text" :title="job.error">{{ job.error }}</div>
              <div v-if="job.last_sync" class="next-sync">{{ formatDateTime(job.last_sync) }}</div>
            </td>
            <td>
              <span v-if="job.dapx_link === 'none'" class="badge badge-outline">{{ t('pvesr.soloProxmox') }}</span>
              <span v-else-if="job.dapx_link === 'mixed'" class="badge badge-warning">{{ t('pvesr.multiplo') }}</span>
              <span v-else class="badge badge-success">{{ dapxLinkLabel(job.dapx_link) }}</span>
              <ul v-if="job.dapx_jobs?.length" class="dapx-job-list">
                <li v-for="dj in job.dapx_jobs" :key="`${dj.kind}-${dj.id}`">{{ dj.name }}</li>
              </ul>
            </td>
            <td class="actions-cell">
              <button
                class="btn btn-xs btn-secondary"
                :title="t('pvesr.esegui')"
                :disabled="runningJobs.has(job.id)"
                @click="runJob(job.id)"
              >
                {{ runningJobs.has(job.id) ? '…' : 'Run' }}
              </button>
              <button
                v-if="job.dapx_link === 'none'"
                class="btn btn-xs btn-primary"
                :title="t('pvesr.importaAiuto')"
                @click="emitImport(job)"
              >
                {{ t('pvesr.importa') }}
              </button>
              <button class="btn-icon text-danger" :title="t('pvesr.elimina')" @click="confirmDelete(job.id)">
                ✕
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="import-note muted mt-4">
        <strong>{{ t('pvesr.importa') }}</strong> {{ t('pvesr.importaNota') }}
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useToast, errorMessage } from '../../stores/toast'
import { confirmDangerous } from '../../stores/confirm'
import {
  pveReplicationService,
  type PVEReplicationJob,
  type PVEReplicationSummary,
} from '../../services/pveReplication'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const emit = defineEmits<{
  import: [job: PVEReplicationJob]
}>()

const toast = useToast()
const jobs = ref<PVEReplicationJob[]>([])
const summary = ref<PVEReplicationSummary | null>(null)
const loading = ref(true)
const runningJobs = ref(new Set<string>())

const loadJobs = async () => {
  loading.value = true
  try {
    const [list, sum] = await Promise.all([
      pveReplicationService.getJobs(),
      pveReplicationService.getSummary(),
    ])
    jobs.value = list
    summary.value = sum
  } catch (e) {
    toast.error(t('pvesr.erroreCarico'), errorMessage(e))
  } finally {
    loading.value = false
  }
}

const runJob = async (id: string) => {
  runningJobs.value.add(id)
  try {
    await pveReplicationService.runJob(id)
    toast.success(t('pvesr.avviata'))
    await loadJobs()
  } catch (e) {
    toast.error(t('pvesr.erroreReplica'), errorMessage(e))
  } finally {
    runningJobs.value.delete(id)
  }
}

const confirmDelete = async (id: string) => {
  if (!await confirmDangerous(t('pvesr.confElimina', { id }))) return
  try {
    await pveReplicationService.deleteJob(id)
    await loadJobs()
  } catch (e) {
    toast.error(t('comune.erroreEliminazione'), errorMessage(e))
  }
}

const emitImport = (job: PVEReplicationJob) => {
  emit('import', job)
}

const dapxLinkLabel = (link: string) => {
  if (link === 'syncoid') return 'Syncoid'
  if (link === 'pve_native') return 'PVE dump'
  if (link === 'recovery_pbs') return t('pvesr.viaPbs')
  return link
}

const getStatusClass = (job: PVEReplicationJob) => {
  if (!job.enabled) return 'status-disabled'
  if (job.error || (job.fail_count && job.fail_count > 0)) return 'status-error'
  return 'status-ok'
}

const getStatusLabel = (job: PVEReplicationJob) => {
  if (!job.enabled) return t('pvesr.disattivato')
  if (job.error || (job.fail_count && job.fail_count > 0)) return t('comune.errore')
  return t('pvesr.attivo')
}

const formatDate = (dateStr: string) => {
  if (!dateStr) return ''
  const date = dateStr.includes('-') ? new Date(dateStr) : new Date(parseInt(dateStr, 10) * 1000)
  return date.toLocaleTimeString()
}

const formatDateTime = (dateStr: string) => {
  if (!dateStr || dateStr === '0') return '-'
  const date = dateStr.includes('-') ? new Date(dateStr) : new Date(parseInt(dateStr, 10) * 1000)
  return date.toLocaleString()
}

onMounted(loadJobs)
defineExpose({ loadJobs })
</script>

<style scoped>
.pve-replication-jobs { width: 100%; }
.pvesr-banner {
  padding: var(--space-3);
  background: var(--color-bg-element);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: 0.9rem;
}
.loading-state, .empty-state { padding: 2rem; text-align: center; color: var(--color-text-secondary); }
.job-id { font-weight: 600; }
.vm-info { font-size: 0.8rem; color: var(--color-text-secondary); }
.status-badge {
  padding: 2px 8px; border-radius: 999px; font-size: 0.72rem; font-weight: 600;
}
.status-ok { background: rgba(34, 197, 94, 0.15); color: var(--color-success-fg); }
.status-error { background: rgba(239, 68, 68, 0.15); color: var(--color-danger-fg); }
.status-disabled { background: var(--color-bg-element); color: var(--color-text-secondary); }
.error-text { font-size: 0.72rem; color: var(--color-danger-fg); max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.next-sync { font-size: 0.75rem; color: var(--color-text-secondary); }
.dapx-job-list { margin: 4px 0 0; padding-left: 1rem; font-size: 0.75rem; color: var(--color-text-secondary); }
.actions-cell { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.btn-icon { background: none; border: none; cursor: pointer; color: var(--color-danger-fg); }
.import-note { font-size: 0.82rem; max-width: 720px; }
.text-danger { color: var(--color-danger-fg); }
</style>
