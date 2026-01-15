<template>
  <div class="recovery-jobs-page">
    <div class="page-header">
        <h1 class="page-title">🔄 Replica via PBS</h1>
        <p class="page-subtitle">Sincronizzazione VM tra cluster tramite Proxmox Backup Server</p>
        <div style="display: flex; align-items: center; gap: 12px; margin-top: 12px;">
            <button class="btn btn-secondary btn-sm" @click="loadJobs" :disabled="loading">
                <span v-if="loading" class="spinner-sm"></span>
                <span v-else>🔄 Aggiorna</span>
            </button>
            <button class="btn btn-primary btn-sm" @click="showCreateModal = true">
                + Nuova Replica
            </button>
        </div>
    </div>

    <div class="card">
        <div class="table-container">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Nome</th>
                        <th>VM</th>
                        <th>Path (Srg → PBS → Dst)</th>
                        <th>Schedule</th>
                        <th>Ultimo Run</th>
                        <th>Stato</th>
                        <th>Azioni</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="job in jobs" :key="job.id">
                        <td>
                            <strong>{{ job.name }}</strong>
                            <div class="text-xs text-secondary">{{ job.backup_mode }}</div>
                        </td>
                        <td>
                            <span class="badge badge-info">{{ job.vm_type }} {{ job.vm_id }}</span>
                            <div class="text-xs mt-1">{{ job.vm_name }}</div>
                        </td>
                        <td class="text-sm">
                            {{ job.source_node_name }} → 
                            <span style="color: #ce93d8;">{{ job.pbs_node_name }}</span> → 
                            {{ job.dest_node_name }}
                        </td>
                        <td>
                             <code v-if="job.schedule">{{ job.schedule }}</code>
                             <span v-else class="text-secondary">Manuale</span>
                        </td>
                        <td>
                            <div v-if="job.last_run">{{ formatDate(job.last_run) }}</div>
                            <div v-if="job.last_duration" class="text-secondary text-xs">
                                {{ job.last_duration }}s
                            </div>
                        </td>
                        <td>
                            <span class="badge" :class="getStatusClass(job.last_status)">
                                {{ job.last_status || 'Never' }}
                            </span>
                        </td>
                        <td>
                            <div class="btn-group">
                                <button class="btn btn-primary btn-xs" @click="runJob(job)" :disabled="job.last_status === 'running'" title="Esegui Ora">
                                    ▶️
                                </button>
                                <button class="btn btn-secondary btn-xs" @click="openEditModal(job)" title="Modifica">
                                    ✏️
                                </button>
                                <button class="btn btn-danger btn-xs" @click="deleteJob(job)" title="Elimina">🗑️</button>
                            </div>
                        </td>
                    </tr>
                     <tr v-if="jobs.length === 0 && !loading">
                         <td colspan="7" class="empty-state-cell">Nessun job di replica PBS configurato</td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>
    <!-- Edit Modal -->
    <div v-if="showEditModal" class="modal-overlay">
        <div class="modal">
            <div class="modal-header">
                <h3>Modifica Job: {{ editForm.name }}</h3>
                <button class="close-btn" @click="showEditModal = false">×</button>
            </div>
            <div class="modal-body">
                <div class="form-group">
                    <label>Nome Job</label>
                    <input v-model="editForm.name" type="text" class="form-control">
                </div>
                <div class="form-group">
                    <label>Schedule (Cron)</label>
                    <input v-model="editForm.schedule" type="text" class="form-control" placeholder="es. 0 2 * * *">
                    <small class="text-secondary">Formato: m h dom mon dow</small>
                </div>
                <div class="form-group">
                    <label>Modalità Backup</label>
                    <select v-model="editForm.backup_mode" class="form-control">
                        <option value="snapshot">Snapshot (Live)</option>
                        <option value="suspend">Suspend</option>
                        <option value="stop">Stop</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Compressione</label>
                    <select v-model="editForm.backup_compress" class="form-control">
                        <option value="zstd">ZSTD (Consigliato)</option>
                        <option value="lzo">LZO (Veloce)</option>
                        <option value="gzip">GZIP</option>
                        <option value="none">Nessuna</option>
                    </select>
                </div>
                
                <div class="checkbox-group">
                    <label>
                        <input type="checkbox" v-model="editForm.include_all_disks"> Includi tutti i dischi
                    </label>
                </div>
                <div class="checkbox-group">
                    <label>
                        <input type="checkbox" v-model="editForm.overwrite_existing"> Sovrascrivi se esiste (Dest)
                    </label>
                </div>
                <div class="checkbox-group">
                    <label>
                        <input type="checkbox" v-model="editForm.restore_start_vm"> Avvia VM dopo restore
                    </label>
                </div>
                     
                <div class="alert alert-info mt-3">
                    <small>Nota: Per cambiare nodi o VM, si consiglia di ricreare il job.</small>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" @click="showEditModal = false">Annulla</button>
                <button class="btn btn-primary" @click="submitEdit" :disabled="saving">
                    {{ saving ? 'Salvataggio...' : 'Salva Modifiche' }}
                </button>
            </div>
        </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive } from 'vue';
import recoveryJobsService, { type RecoveryJob } from '../../services/recoveryJobs';

const jobs = ref<RecoveryJob[]>([]);
const loading = ref(false);
const showCreateModal = ref(false);

// Edit Logic
const showEditModal = ref(false);
const saving = ref(false);
const editForm = reactive<Partial<RecoveryJob>>({});
const currentEditId = ref<string | null>(null);

const openEditModal = (job: RecoveryJob) => {
    currentEditId.value = job.id;
    // Copy data to form
    Object.assign(editForm, {
        name: job.name,
        schedule: job.schedule,
        backup_mode: job.backup_mode,
        backup_compress: job.backup_compress,
        include_all_disks: job.include_all_disks,
        overwrite_existing: job.overwrite_existing,
        restore_start_vm: job.restore_start_vm
    });
    showEditModal.value = true;
};

const submitEdit = async () => {
    if (!currentEditId.value) return;
    saving.value = true;
    try {
        await recoveryJobsService.updateJob(currentEditId.value, editForm);
        showEditModal.value = false;
        loadJobs(); // Refresh list
    } catch (e) {
        alert('Errore salvataggio modifiche');
        console.error(e);
    } finally {
        saving.value = false;
    }
};

onMounted(() => {
    loadJobs();
});

const loadJobs = async () => {
    loading.value = true;
    try {
        const res = await recoveryJobsService.getJobs();
        jobs.value = res.data;
    } catch (e) {
        console.error('Error loading recovery jobs', e);
    } finally {
        loading.value = false;
    }
};

const runJob = async (job: RecoveryJob) => {
    if (!confirm(`Avviare replica per ${job.name}?`)) return;
    try {
        await recoveryJobsService.runJob(job.id);
        loadJobs();
    } catch (e) {
        alert('Errore avvio job');
    }
};

const deleteJob = async (job: RecoveryJob) => {
    if (!confirm('Eliminare questo job di replica?')) return;
    try {
        await recoveryJobsService.deleteJob(job.id);
        loadJobs();
    } catch (e) {
        alert('Errore eliminazione job');
    }
};

const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString();
};

const getStatusClass = (status?: string) => {
    if (status === 'success' || status === 'OK') return 'badge-success';
    if (status === 'error' || status === 'failed') return 'badge-danger';
    if (status === 'running') return 'badge-warning';
    return 'badge-secondary';
};
</script>

<style scoped>
.text-xs { font-size: 0.75em; }
.mt-1 { margin-top: 4px; }
.mt-3 { margin-top: 12px; }
.text-sm { font-size: 0.85em; }
.text-secondary { color: var(--text-secondary); }
.btn-group { display: flex; gap: 4px; }
.btn-xs { padding: 4px 8px; font-size: 0.75rem; }
.badge-info { background: rgba(0, 212, 255, 0.15); color: #00d4ff; }
.badge-success { background: rgba(0, 184, 148, 0.15); color: #00b894; }
.badge-danger { background: rgba(255, 82, 82, 0.15); color: #ff5252; }
.badge-warning { background: rgba(255, 179, 0, 0.15); color: #ffb300; }
.empty-state-cell { text-align: center; padding: 40px; color: var(--text-secondary); }
.spinner-sm {
    display: inline-block;
    width: 12px; height: 12px;
    border: 2px solid currentColor;
    border-top-color: transparent;
    border-radius: 50%;
    animation: spin 1s linear infinite;
}

/* Modal Styles */
.modal-overlay {
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    justify-content: center;
    align-items: center;
    z-index: 1000;
}
.modal {
    background: var(--bg-card);
    padding: 24px;
    border-radius: 12px;
    width: 100%;
    max-width: 500px;
    border: 1px solid var(--border-color);
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
}
.modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
}
.modal-body {
    display: flex;
    flex-direction: column;
    gap: 16px;
}
.modal-footer {
    display: flex;
    justify-content: flex-end;
    gap: 12px;
    margin-top: 24px;
}
.form-group {
    display: flex;
    flex-direction: column;
    gap: 6px;
}
.form-control {
    background: var(--bg-input);
    border: 1px solid var(--border-color);
    padding: 8px 12px;
    border-radius: 6px;
    color: var(--text-primary);
}
.checkbox-group label {
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
}
.close-btn {
    background: none;
    border: none;
    font-size: 24px;
    cursor: pointer;
    color: var(--text-secondary);
}
.alert-info {
    background: rgba(0, 212, 255, 0.1);
    color: #00d4ff;
    padding: 10px;
    border-radius: 6px;
    border-left: 3px solid #00d4ff;
}
</style>
