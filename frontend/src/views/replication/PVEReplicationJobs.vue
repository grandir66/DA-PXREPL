<template>
  <div class="pve-replication-jobs">
    <div v-if="loading" class="loading-state">
      Caricamento job in corso...
    </div>
    <div v-else-if="jobs.length === 0" class="empty-state">
      Nessun job di replica nativa PVE configurato.
    </div>
    <div v-else class="table-container">
      <table class="data-table">
        <thead>
          <tr>
            <th>ID / VM</th>
            <th>Sorgente</th>
            <th>Destinazione</th>
            <th>Programmazione</th>
            <th>Stato</th>
            <th>Ultima Sincronizzazione</th>
            <th>Azioni</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="job in jobs" :key="job.id">
            <td>
              <div class="job-id">{{ job.id }}</div>
              <div class="vm-info">VM {{ job.vm }}</div>
            </td>
            <td>{{ job.source || 'N/A' }}</td>
            <td>{{ job.target }}</td>
            <td>
              <code>{{ job.schedule }}</code>
              <div v-if="job.next_sync" class="next-sync">Prox: {{ formatDate(job.next_sync) }}</div>
            </td>
            <td>
              <span :class="['status-badge', getStatusClass(job)]">
                {{ getStatusLabel(job) }}
              </span>
              <div v-if="job.error" class="error-text" :title="job.error">
                Errore rilevato
              </div>
            </td>
            <td>
              <div v-if="job.last_sync">
                {{ formatDateTime(job.last_sync) }}
                <div v-if="job.duration" class="duration">({{ job.duration.toFixed(1) }}s)</div>
              </div>
              <div v-else>-</div>
            </td>
            <td class="actions-cell">
              <button class="btn-icon" title="Esegui ora" @click="runJob(job.id)" :disabled="runningJobs.has(job.id)">
                <svg v-if="!runningJobs.has(job.id)" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                <div v-else class="spinner-small"></div>
              </button>
              <button class="btn-icon text-danger" title="Elimina" @click="confirmDelete(job.id)">
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { pveReplicationService, type PVEReplicationJob } from '../../services/pveReplication';

const jobs = ref<PVEReplicationJob[]>([]);
const loading = ref(true);
const runningJobs = ref(new Set<string>());

const loadJobs = async () => {
  loading.value = true;
  try {
    jobs.value = await pveReplicationService.getJobs();
  } catch (e) {
    console.error('Errore caricamento job PVE Native:', e);
  } finally {
    loading.value = false;
  }
};

const runJob = async (id: string) => {
  runningJobs.value.add(id);
  try {
    await pveReplicationService.runJob(id);
    alert('Replica completata con successo');
    await loadJobs();
  } catch (e: any) {
    alert('Errore durante la replica: ' + (e.response?.data?.detail || e.message));
  } finally {
    runningJobs.value.delete(id);
  }
};

const confirmDelete = async (id: string) => {
  if (!confirm(`Sei sicuro di voler eliminare il job ${id}?`)) return;
  try {
    await pveReplicationService.deleteJob(id);
    await loadJobs();
  } catch (e) {
    alert('Errore eliminazione job');
  }
};

const getStatusClass = (job: PVEReplicationJob) => {
  if (!job.enabled) return 'status-disabled';
  if (job.error || (job.fail_count && job.fail_count > 0)) return 'status-error';
  return 'status-ok';
};

const getStatusLabel = (job: PVEReplicationJob) => {
  if (!job.enabled) return 'Disabilitato';
  if (job.error || (job.fail_count && job.fail_count > 0)) return 'Errore';
  return 'Attivo';
};

const formatDate = (dateStr: string) => {
  if (!dateStr) return '';
  return new Date(dateStr).toLocaleTimeString();
};

const formatDateTime = (dateStr: string) => {
  if (!dateStr || dateStr === '0') return '-';
  // PVE might return epoch or ISO
  const date = dateStr.includes('-') ? new Date(dateStr) : new Date(parseInt(dateStr) * 1000);
  return date.toLocaleString();
};

onMounted(loadJobs);

defineExpose({ loadJobs });
</script>

<style scoped>
.pve-replication-jobs {
  width: 100%;
}

.loading-state, .empty-state {
  padding: 40px;
  text-align: center;
  color: var(--text-secondary);
}

.job-id {
  font-weight: 600;
  color: var(--text-primary);
}

.vm-info {
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.status-badge {
  padding: 4px 10px;
  border-radius: 20px;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
}

.status-ok { background: rgba(0, 255, 157, 0.1); color: var(--accent-primary); }
.status-error { background: rgba(255, 78, 112, 0.1); color: var(--text-danger); }
.status-disabled { background: rgba(255, 255, 255, 0.05); color: var(--text-secondary); }

.error-text {
  font-size: 0.7rem;
  color: var(--text-danger);
  margin-top: 4px;
  text-overflow: ellipsis;
  overflow: hidden;
  white-space: nowrap;
  max-width: 150px;
}

.next-sync, .duration {
  font-size: 0.75rem;
  color: var(--text-secondary);
  margin-top: 2px;
}

.actions-cell {
  display: flex;
  gap: 8px;
}

.btn-icon {
  background: transparent;
  border: none;
  padding: 8px;
  border-radius: 6px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-icon:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-primary);
}

.btn-icon.text-danger:hover {
  background: rgba(255, 78, 112, 0.1);
  color: var(--text-danger);
}

.btn-icon svg {
  width: 18px;
  height: 18px;
}

.spinner-small {
  width: 18px; height: 18px;
  border: 2px solid rgba(255, 255, 255, 0.1);
  border-top-color: var(--accent-primary);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
