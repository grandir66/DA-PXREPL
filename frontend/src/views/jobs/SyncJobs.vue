<template>
  <div class="sync-jobs-page">
    <div class="page-header">
        <h1 class="page-title">⚡ Replica ZFS / BTRFS</h1>
        <p class="page-subtitle">Gestione job di sincronizzazione diretta tra server</p>
        <div style="display: flex; align-items: center; gap: 12px; margin-top: 12px;">
            <button class="btn btn-secondary btn-sm" @click="loadJobs" :disabled="loading">
                <span v-if="loading" class="spinner-sm"></span>
                <span v-else>🔄 Aggiorna</span>
            </button>
            <button class="btn btn-primary btn-sm" @click="showCreateModal = true">
                + Nuovo Job
            </button>
        </div>
    </div>

    <div class="card">
        <div class="table-container">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Nome Job</th>
                        <th>Sorgente → Destinazione</th>
                        <th>VM</th>
                        <th>Schedule</th>
                        <th>Ultimo Run</th>
                        <th>Stato</th>
                        <th>Azioni</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="job in jobs" :key="job.id">
                        <td>
                            <strong>{{ job.job_name }}</strong>
                            <div class="text-xs text-secondary">{{ job.id }}</div>
                        </td>
                        <td class="text-sm">
                            <div>{{ job.source_node_name }} : {{ job.source_dataset }}</div>
                            <div style="text-align: center; color: var(--text-secondary);">↓</div>
                            <div>{{ job.dest_node_name }} : {{ job.dest_dataset }}</div>
                        </td>
                        <td>
                            <span v-if="job.vm_id" class="badge badge-info">VM {{ job.vm_id }}</span>
                            <span v-else class="text-secondary">-</span>
                        </td>
                        <td>
                             <code v-if="job.schedule">{{ job.schedule }}</code>
                             <span v-else class="text-secondary">Manuale</span>
                        </td>
                        <td class="text-sm">
                            <div v-if="job.last_run">{{ formatDate(job.last_run) }}</div>
                            <div v-if="job.last_duration_seconds" class="text-secondary">
                                {{ formatDuration(job.last_duration_seconds) }}
                            </div>
                        </td>
                        <td>
                            <span class="badge" :class="getStatusClass(job.last_status)">
                                {{ job.last_status || 'Never' }}
                            </span>
                        </td>
                        <td>
                            <div class="btn-group">
                                <button class="btn btn-primary btn-xs" @click="runJob(job)" :disabled="job.last_status === 'running'">
                                    ▶️ Run
                                </button>
                                <button class="btn btn-secondary btn-xs" title="Modifica">✏️</button>
                                <button class="btn btn-danger btn-xs" @click="deleteJob(job)" title="Elimina">🗑️</button>
                            </div>
                        </td>
                    </tr>
                     <tr v-if="jobs.length === 0 && !loading">
                         <td colspan="7" class="empty-state-cell">Nessun job di replica configurato</td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>
    
    <!-- Create Modal -->
    <div v-if="showCreateModal" class="modal-overlay" @click.self="closeModal">
        <div class="modal">
            <div class="modal-header">
                <h3>Nuovo Job di Replica</h3>
                <button class="btn-icon" @click="closeModal">✕</button>
            </div>
            <div class="modal-body">
                <div class="grid-2">
                    <div class="form-group">
                        <label>Nodo Sorgente</label>
                        <select v-model="form.source_node_id" class="form-input">
                            <option v-for="node in nodes" :key="node.id" :value="node.id">{{ node.name }}</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Nodo Destinazione</label>
                        <select v-model="form.dest_node_id" class="form-input">
                            <option v-for="node in nodes" :key="node.id" :value="node.id">{{ node.name }}</option>
                        </select>
                    </div>
                </div>
                
                <div class="form-group">
                     <label>Dataset Sorgente (ZFS) / Path (BTRFS)</label>
                     <input type="text" v-model="form.source_dataset" class="form-input" placeholder="rpool/data/subvol-100-disk-0">
                </div>

                <div class="form-group">
                     <label>Dataset Destinazione</label>
                     <input type="text" v-model="form.dest_dataset" class="form-input" placeholder="backup/replica/subvol-100-disk-0">
                </div>
                
                <div class="grid-2">
                    <div class="form-group">
                        <label>Schedule (Cron)</label>
                        <input type="text" v-model="form.schedule" class="form-input" placeholder="*/15 * * * *">
                    </div>
                    <div class="form-group">
                        <label>Metodo Sync</label>
                        <select v-model="form.sync_method" class="form-input">
                             <option value="syncoid">Syncoid (ZFS)</option>
                             <option value="btrfs_send">BTRFS Send</option>
                        </select>
                    </div>
                </div>

                <div class="form-check">
                    <label>
                        <input type="checkbox" v-model="form.recursive">
                        Ricorsivo (-r)
                    </label>
                </div>
                
                <div class="form-check">
                    <label>
                        <input type="checkbox" v-model="form.register_vm">
                        Registra VM su destinazione
                    </label>
                </div>
                <div class="grid-2" v-if="form.register_vm">
                     <div class="form-group">
                        <label>ID VM Sorgente</label>
                        <input type="number" v-model.number="form.vm_id" class="form-input">
                    </div>
                     <div class="form-group">
                        <label>ID VM Destinazione</label>
                        <input type="number" v-model.number="form.dest_vm_id" class="form-input" placeholder="Opzionale">
                    </div>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" @click="closeModal">Annulla</button>
                <button class="btn btn-primary" @click="createJob" :disabled="creating">
                    {{ creating ? 'Creazione...' : 'Crea Job' }}
                </button>
            </div>
        </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue';
import syncJobsService, { type SyncJob } from '../../services/syncJobs';
import nodesService, { type Node } from '../../services/nodes';

const jobs = ref<SyncJob[]>([]);
const nodes = ref<Node[]>([]);
const loading = ref(false);
const showCreateModal = ref(false);
const creating = ref(false);

const form = reactive({
    source_node_id: null as number | null,
    dest_node_id: null as number | null,
    source_dataset: '',
    dest_dataset: '',
    schedule: '0 * * * *',
    sync_method: 'syncoid',
    recursive: false,
    register_vm: false,
    vm_id: null as number | null,
    dest_vm_id: null as number | null
});

onMounted(() => {
    loadJobs();
    loadNodes();
});

const loadJobs = async () => {
    loading.value = true;
    try {
        const res = await syncJobsService.getJobs();
        jobs.value = res.data;
    } catch (e) {
        console.error('Error loading jobs', e);
    } finally {
        loading.value = false;
    }
};

const loadNodes = async () => {
    try {
        const res = await nodesService.getNodes();
        nodes.value = res.data;
    } catch (e) {
        console.error('Error loading nodes', e);
    }
};

const closeModal = () => {
    showCreateModal.value = false;
};

const createJob = async () => {
    if (!form.source_node_id || !form.dest_node_id || !form.source_dataset || !form.dest_dataset) {
        alert('Compila tutti i campi obbligatori');
        return;
    }
    
    creating.value = true;
    try {
        await syncJobsService.createJob(form);
        showCreateModal.value = false;
        loadJobs();
    } catch (e: any) {
        alert('Errore creazione job: ' + (e.response?.data?.detail || e.message));
    } finally {
        creating.value = false;
    }
}

const runJob = async (job: SyncJob) => {
    if (!confirm(`Avviare job ${job.job_name}?`)) return;
    try {
        await syncJobsService.runJob(job.id);
        loadJobs();
    } catch (e) {
        alert('Errore avvio job');
    }
};

const deleteJob = async (job: SyncJob) => {
    if (!confirm(`Eliminare job ${job.job_name}? Irreversibile.`)) return;
    try {
        await syncJobsService.deleteJob(job.id);
        loadJobs();
    } catch (e) {
        alert('Errore eliminazione job');
    }
};

const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString();
};

const formatDuration = (seconds: number) => {
    if (seconds < 60) return seconds + 's';
    return (seconds / 60).toFixed(1) + 'm';
};

const getStatusClass = (status?: string) => {
    if (status === 'success') return 'badge-success';
    if (status === 'error' || status === 'failed') return 'badge-danger';
    if (status === 'running') return 'badge-warning';
    return 'badge-secondary';
};
</script>

<style scoped>
.sync-jobs-page { padding-bottom: 40px; }
.text-xs { font-size: 0.75em; }
.text-sm { font-size: 0.85em; }
.btn-group { display: flex; gap: 4px; }
.btn-xs { padding: 4px 8px; font-size: 0.75rem; }
.badge-success { background: rgba(0, 184, 148, 0.15); color: #00b894; }
.badge-danger { background: rgba(255, 82, 82, 0.15); color: #ff5252; }
.badge-warning { background: rgba(255, 179, 0, 0.15); color: #ffb300; }
.empty-state-cell { text-align: center; padding: 40px; color: var(--text-secondary); }

/* Modal Styles */
.modal-overlay {
    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.7);
    display: flex; align-items: center; justify-content: center;
    z-index: 1000;
}
.modal {
    background: var(--bg-card);
    padding: 24px;
    border-radius: 12px;
    width: 90%; max-width: 600px;
    border: 1px solid var(--border-color);
}
.modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.btn-icon { background: none; border: none; font-size: 1.2rem; color: var(--text-secondary); cursor: pointer; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.form-group { margin-bottom: 16px; }
.form-group label { display: block; margin-bottom: 6px; color: var(--text-secondary); font-size: 0.9em; }
.modal-footer {
    display: flex; justify-content: flex-end; gap: 12px; margin-top: 24px;
}
.form-check { margin-bottom: 12px; }
</style>
