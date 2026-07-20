<template>
  <section class="cluster-pbs-jobs">
    <div v-if="summary && summary.total > 0" class="cluster-banner mb-4">
      <strong>{{ summary.total }} backup Proxmox (Datacenter)</strong> verso PBS rilevati sul cluster.
      <span v-if="summary.unlinked > 0" class="ml-2">
        {{ summary.unlinked }} non collegati a job dapx.
      </span>
      <span v-if="summary.partial > 0" class="ml-2 text-warning">
        {{ summary.partial }} parzialmente tracciati.
      </span>
    </div>

    <div class="flex justify-between items-center mb-3">
      <div>
        <p class="muted section-sub mb-0">
          Job vzdump da <strong>Proxmox Datacenter → Backup</strong> con destinazione storage PBS
          (es. <code>PBS-BACK-DTS1</code>). Non confonderli con i job creati in dapx (tab Job dapx).
        </p>
      </div>
      <button class="btn btn-secondary btn-sm" :disabled="loading" @click="loadJobs">Aggiorna</button>
    </div>

    <div v-if="loading" class="loading-state">Caricamento job backup cluster…</div>
    <div v-else-if="jobs.length === 0" class="empty-state compact">
      Nessun job Datacenter verso storage PBS trovato sul cluster.
      <p class="muted mt-2 mb-0">Controlla in Proxmox che i job backup usino uno storage di tipo PBS.</p>
    </div>
    <div v-else class="table-container">
      <table class="data-table">
        <thead>
          <tr>
            <th>Job</th>
            <th>Storage PBS</th>
            <th>VM</th>
            <th>Schedule</th>
            <th>Stato</th>
            <th>In dapx</th>
            <th>Azioni</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="job in jobs" :key="job.id">
            <td>
              <div class="job-id">{{ job.id }}</div>
              <div v-if="job.node" class="muted text-xs">Nodo: {{ job.node }}</div>
            </td>
            <td>
              <code>{{ job.storage }}</code>
              <div v-if="job.pbs_server" class="muted text-xs">{{ job.pbs_server }} / {{ job.pbs_datastore }}</div>
            </td>
            <td>
              <span v-if="job.vm_selection === 'all'" class="badge badge-outline">Tutte le VM</span>
              <span v-else-if="job.vm_selection?.startsWith('pool:')" class="badge badge-outline">
                {{ job.vm_selection }}
              </span>
              <template v-else>
                <div v-for="vm in job.vm_labels.slice(0, 4)" :key="vm.vm_id" class="vm-line">
                  {{ vm.vm_name || `VM ${vm.vm_id}` }}
                  <span class="muted">· {{ vm.vm_type === 'lxc' ? 'LXC' : 'QEMU' }}</span>
                </div>
                <div v-if="job.vm_count > 4" class="muted text-xs">+{{ job.vm_count - 4 }} altre</div>
              </template>
            </td>
            <td><code>{{ job.schedule || '—' }}</code></td>
            <td>
              <span :class="['status-badge', job.enabled ? 'status-ok' : 'status-disabled']">
                {{ job.enabled ? 'Attivo' : 'Disabilitato' }}
              </span>
              <div class="muted text-xs">{{ job.mode }} · {{ job.compress }}</div>
            </td>
            <td>
              <span v-if="job.dapx_link === 'none'" class="badge badge-outline">Solo Proxmox</span>
              <span v-else-if="job.dapx_link === 'partial'" class="badge badge-warning">Parziale</span>
              <span v-else class="badge badge-success">Tracciato</span>
              <ul v-if="job.dapx_jobs?.length" class="dapx-job-list">
                <li v-for="dj in job.dapx_jobs.slice(0, 3)" :key="`${dj.kind}-${dj.id}`">{{ dj.name }}</li>
              </ul>
            </td>
            <td class="actions-cell">
              <button
                class="btn btn-xs btn-secondary"
                title="Esegui ora (Proxmox)"
                :disabled="runningJobs.has(job.id)"
                @click="runJob(job.id)"
              >
                {{ runningJobs.has(job.id) ? '…' : 'Run' }}
              </button>
              <template v-if="job.dapx_link !== 'backup_pbs'">
                <button
                  v-if="job.vm_count === 1"
                  class="btn btn-xs btn-primary"
                  @click="emitImport(job, job.vm_labels[0])"
                >
                  Importa in dapx
                </button>
                <div v-else-if="job.vm_labels.length" class="import-vm-btns">
                  <button
                    v-for="vm in job.vm_labels.slice(0, 3)"
                    :key="vm.vm_id"
                    class="btn btn-xs btn-primary"
                    @click="emitImport(job, vm)"
                  >
                    Import VM {{ vm.vm_id }}
                  </button>
                </div>
              </template>
              <button class="btn-icon text-danger" title="Elimina da Proxmox" @click="confirmDelete(job.id)">
                ✕
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="import-note muted mt-4">
        <strong>Importa in dapx</strong> apre il wizard backup PBS con VM, storage e schedule precompilati.
        Il job Proxmox resta attivo finché non lo disabiliti lì — evita doppi backup sulla stessa VM.
      </p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import backupJobsService, {
  type ClusterPBSBackupJob,
  type ClusterPBSBackupSummary,
  type ClusterPBSVmLabel,
} from '../../services/backupJobs'
import { useToast, errorMessage } from '../../stores/toast'
import { confirmDangerous } from '../../stores/confirm'

export type ClusterVmLabel = ClusterPBSVmLabel

const emit = defineEmits<{
  import: [job: ClusterPBSBackupJob, vm: ClusterPBSVmLabel]
}>()

const toast = useToast()
const jobs = ref<ClusterPBSBackupJob[]>([])
const summary = ref<ClusterPBSBackupSummary | null>(null)
const loading = ref(true)
const runningJobs = ref(new Set<string>())

const loadJobs = async () => {
  loading.value = true
  try {
    const [listRes, sumRes] = await Promise.all([
      backupJobsService.getClusterJobs(),
      backupJobsService.getClusterSummary(),
    ])
    jobs.value = listRes.data
    summary.value = sumRes.data
  } catch (e) {
    toast.error('Errore caricamento backup cluster', errorMessage(e))
  } finally {
    loading.value = false
  }
}

const runJob = async (id: string) => {
  runningJobs.value.add(id)
  try {
    await backupJobsService.runClusterJob(id)
    toast.success('Backup cluster avviato')
    await loadJobs()
  } catch (e) {
    toast.error('Errore avvio backup', errorMessage(e))
  } finally {
    runningJobs.value.delete(id)
  }
}

const confirmDelete = async (id: string) => {
  if (!await confirmDangerous(`Eliminare il job backup cluster ${id} da Proxmox?`)) return
  try {
    await backupJobsService.deleteClusterJob(id)
    await loadJobs()
  } catch (e) {
    toast.error('Errore eliminazione', errorMessage(e))
  }
}

const emitImport = (job: ClusterPBSBackupJob, vm: ClusterPBSVmLabel) => {
  emit('import', job, vm)
}

onMounted(loadJobs)
defineExpose({ loadJobs })
</script>

<style scoped>
.section-title { font-size: 1rem; font-weight: 600; margin: 0 0 4px; }
.section-sub { font-size: 0.82rem; margin: 0; max-width: 640px; }
.cluster-banner {
  padding: var(--space-3);
  background: var(--color-bg-element);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: 0.9rem;
}
.loading-state, .empty-state { padding: 1.5rem; text-align: center; color: var(--color-text-secondary); }
.empty-state.compact { padding: 1rem; font-size: 0.88rem; }
.job-id { font-weight: 600; font-size: 0.85rem; }
.vm-line { font-size: 0.82rem; }
.status-badge {
  padding: 2px 8px; border-radius: 999px; font-size: 0.72rem; font-weight: 600;
}
.status-ok { background: rgba(34, 197, 94, 0.15); color: var(--color-success-fg); }
.status-disabled { background: var(--color-bg-element); color: var(--color-text-secondary); }
.dapx-job-list { margin: 4px 0 0; padding-left: 1rem; font-size: 0.75rem; color: var(--color-text-secondary); }
.actions-cell { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.import-vm-btns { display: flex; flex-wrap: wrap; gap: 4px; }
.btn-icon { background: none; border: none; cursor: pointer; color: var(--color-danger-fg); }
.import-note { font-size: 0.82rem; max-width: 720px; }
.text-warning { color: var(--color-warning-fg, #ca8a04); }
.text-xs { font-size: 0.75rem; }
</style>
