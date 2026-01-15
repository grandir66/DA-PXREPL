<template>
  <div class="recovery-jobs-page">
    <div class="page-header" v-if="!embedded">
        <h1 class="page-title">🔄 Replica via PBS</h1>
        <p class="page-subtitle">Sincronizzazione VM tra cluster tramite Proxmox Backup Server</p>
    </div>

    <!-- Header actions for embedded mode -->
    <div class="header-actions" v-if="embedded" style="margin-bottom: 12px; display: flex; justify-content: flex-end;">
         <button class="btn btn-secondary btn-sm" @click="loadJobs" :disabled="loading">
            <span v-if="loading" class="spinner-sm"></span>
            <span v-else>🔄 Aggiorna</span>
        </button>
    </div>
    
    <div class="page-header" v-else>
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
                            <div v-if="job.current_status && job.current_status !== 'idle'" class="status-with-phase">
                                <span class="badge badge-running">
                                    <span class="pulse-dot"></span>
                                    {{ formatPhase(job.current_status) }}
                                </span>
                            </div>
                            <div v-else>
                                <span class="badge" :class="getStatusClass(job.last_status)">
                                    {{ job.last_status || 'Never' }}
                                </span>
                            </div>
                        </td>
                        <td>
                            <div class="btn-group">
                                <button class="btn btn-primary btn-xs" @click="runJob(job)" :disabled="job.last_status === 'running'" title="Esegui Ora">
                                    ▶️
                                </button>
                                <button class="btn btn-secondary btn-xs" @click="selectedJobForLogs = job" title="Visualizza Log">
                                    📜
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
    <div v-if="showEditModal" class="modal-overlay" @click.self="showEditModal = false">
        <div class="modal modal-lg">
            <div class="modal-header">
                <h3>Modifica Job: {{ editForm.name }}</h3>
                <button class="close-btn" @click="showEditModal = false">×</button>
            </div>
            <div class="modal-body">
                <!-- Read-only info section -->
                <div class="settings-section">
                    <h4>Informazioni (Non modificabili)</h4>
                    <div class="form-row">
                        <div class="form-group flex-1">
                            <label>VM Sorgente</label>
                            <input :value="`${editForm.vm_type} ${editForm.vm_id} - ${editForm.vm_name || 'N/A'}`" class="form-control" disabled />
                        </div>
                        <div class="form-group flex-1">
                            <label>Nodo Sorgente</label>
                            <input :value="editForm.source_node_name" class="form-control" disabled />
                        </div>
                    </div>
                     <div class="form-row">
                        <div class="form-group flex-1">
                            <label>Nodo PBS</label>
                            <input :value="editForm.pbs_node_name" class="form-control" disabled />
                        </div>
                        <div class="form-group flex-1">
                            <label>Nodo Destinazione</label>
                            <input :value="editForm.dest_node_name" class="form-control" disabled />
                        </div>
                    </div>
                </div>

                <!-- Editable section -->
                <div class="settings-section">
                    <h4>Impostazioni Generali</h4>
                    <div class="form-group">
                        <label>Nome Job</label>
                        <input v-model="editForm.name" type="text" class="form-control">
                    </div>
                    <div class="form-row">
                        <div class="form-group flex-1">
                            <label>Schedule (Cron)</label>
                            <input v-model="editForm.schedule" type="text" class="form-control" placeholder="es. 0 2 * * *">
                            <small class="text-secondary">Formato: minuto ora giorno mese weekday</small>
                        </div>
                        <div class="form-group flex-1">
                            <label>Datastore PBS</label>
                            <input v-model="editForm.pbs_datastore" type="text" class="form-control" placeholder="datastore1">
                        </div>
                    </div>
                </div>

                <div class="settings-section">
                    <h4>Backup</h4>
                    <div class="form-row">
                        <div class="form-group flex-1">
                            <label>Modalità Backup</label>
                            <select v-model="editForm.backup_mode" class="form-control">
                                <option value="snapshot">Snapshot (Live)</option>
                                <option value="suspend">Suspend</option>
                                <option value="stop">Stop</option>
                            </select>
                        </div>
                        <div class="form-group flex-1">
                            <label>Compressione</label>
                            <select v-model="editForm.backup_compress" class="form-control">
                                <option value="zstd">ZSTD (Consigliato)</option>
                                <option value="lzo">LZO (Veloce)</option>
                                <option value="gzip">GZIP</option>
                                <option value="none">Nessuna</option>
                            </select>
                        </div>
                    </div>
                    <div class="checkbox-group">
                        <label>
                            <input type="checkbox" v-model="editForm.include_all_disks"> Includi tutti i dischi
                        </label>
                    </div>
                </div>

                <div class="settings-section">
                    <h4>Destinazione/Restore</h4>
                    <div class="form-row">
                        <div class="form-group flex-1">
                            <label>VM ID Destinazione</label>
                            <input v-model.number="editForm.dest_vm_id" type="number" class="form-control" placeholder="Stesso della sorgente">
                        </div>
                        <div class="form-group flex-1">
                            <label>Suffisso Nome VM</label>
                            <input v-model="editForm.dest_vm_name_suffix" type="text" class="form-control" placeholder="_replica">
                        </div>
                    </div>
                    <div class="form-row">
                        <div class="form-group flex-1">
                            <label>Storage Destinazione</label>
                            <input v-model="editForm.dest_storage" type="text" class="form-control" placeholder="local-zfs">
                        </div>
                    </div>
                    <div class="checkbox-group">
                        <label>
                            <input type="checkbox" v-model="editForm.overwrite_existing"> Sovrascrivi se esiste
                        </label>
                    </div>
                    <div class="checkbox-group">
                        <label>
                            <input type="checkbox" v-model="editForm.restore_start_vm"> Avvia VM dopo restore
                        </label>
                    </div>
                    <div class="checkbox-group">
                        <label>
                            <input type="checkbox" v-model="editForm.restore_unique"> Genera UUID unici (Consigliato)
                        </label>
                    </div>
                </div>

                <div class="settings-section">
                    <h4>Retry e Notifiche</h4>
                    <div class="form-row">
                        <div class="form-group flex-1">
                            <label>Max Retry</label>
                            <input v-model.number="editForm.max_retries" type="number" class="form-control" min="0" max="10">
                        </div>
                        <div class="form-group flex-1">
                            <label>Ritardo Retry (minuti)</label>
                            <input v-model.number="editForm.retry_delay_minutes" type="number" class="form-control" min="1">
                        </div>
                    </div>
                    <div class="checkbox-group">
                        <label>
                            <input type="checkbox" v-model="editForm.retry_on_failure"> Retry automatico su fallimento
                        </label>
                    </div>
                    <div class="checkbox-group">
                        <label>
                            <input type="checkbox" v-model="editForm.is_active"> Job attivo
                        </label>
                    </div>
                    <div class="checkbox-group">
                        <label>
                            <input type="checkbox" v-model="editForm.notify_on_each_run"> Notifica ad ogni esecuzione
                        </label>
                    </div>
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
    <!-- Job Logs Viewer -->
    <JobLogViewer 
        v-if="selectedJobForLogs" 
        :job-id="selectedJobForLogs.id" 
        :job-name="selectedJobForLogs.name"
        @close="selectedJobForLogs = null" 
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive, defineProps } from 'vue';
import recoveryJobsService, { type RecoveryJob } from '../../services/recoveryJobs';

const props = defineProps({
    embedded: {
        type: Boolean,
        default: true
    }
});

const jobs = ref<RecoveryJob[]>([]);
const loading = ref(false);
const showCreateModal = ref(false);

// Edit Logic
const showEditModal = ref(false);
const saving = ref(false);
const editForm = reactive<Partial<RecoveryJob>>({});
const currentEditId = ref<string | null>(null);
const selectedJobForLogs = ref<RecoveryJob | null>(null);

import JobLogViewer from '../components/JobLogViewer.vue';

const openEditModal = (job: RecoveryJob) => {
    currentEditId.value = job.id;
    // Copy data to form (both editable and readonly for display)
    Object.assign(editForm, {
        name: job.name,
        schedule: job.schedule,
        backup_mode: job.backup_mode,
        backup_compress: job.backup_compress,
        include_all_disks: job.include_all_disks,
        overwrite_existing: job.overwrite_existing,
        restore_start_vm: job.restore_start_vm,
        restore_unique: job.restore_unique,
        // Readonly info
        vm_id: job.vm_id,
        vm_type: job.vm_type,
        vm_name: job.vm_name,
        source_node_name: job.source_node_name,
        pbs_node_name: job.pbs_node_name,
        dest_node_name: job.dest_node_name,
        // Additional editable fields
        pbs_datastore: job.pbs_datastore,
        dest_vm_id: job.dest_vm_id,
        dest_vm_name_suffix: job.dest_vm_name_suffix,
        dest_storage: job.dest_storage,
        max_retries: job.max_retries,
        retry_delay_minutes: job.retry_delay_minutes,
        retry_on_failure: job.retry_on_failure,
        is_active: job.is_active,
        notify_on_each_run: job.notify_on_each_run
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

import { onMounted, onUnmounted, ref, reactive, computed } from 'vue';

let pollingInterval: ReturnType<typeof setInterval> | null = null;

onMounted(() => {
    loadJobs();
    // Start polling for real-time updates
    pollingInterval = setInterval(() => {
        // Only refresh if any job is running
        if (jobs.value.some(j => j.current_status && j.current_status !== 'idle')) {
            loadJobs();
        }
    }, 3000);
});

onUnmounted(() => {
    if (pollingInterval) {
        clearInterval(pollingInterval);
    }
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
    if (status === 'running' || status === 'backing_up' || status === 'restoring') return 'badge-running';
    return 'badge-secondary';
};

const formatPhase = (phase: string) => {
    const phases: Record<string, string> = {
        'backing_up': '📤 Backup...',
        'restoring': '📥 Restore...',
        'running': '🔄 In esecuzione...',
        'idle': 'Idle'
    };
    return phases[phase] || phase;
};

defineExpose({ loadJobs });
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
.modal-lg {
    max-width: 700px;
    max-height: 85vh;
    overflow-y: auto;
}
.settings-section {
    background: var(--bg-secondary);
    padding: 16px;
    border-radius: 8px;
    border: 1px solid var(--border-color);
}
.settings-section h4 {
    margin: 0 0 12px 0;
    font-size: 0.9rem;
    color: var(--accent-primary);
}
.form-row {
    display: flex;
    gap: 16px;
}
.flex-1 {
    flex: 1;
}
.form-control:disabled {
    opacity: 0.6;
    cursor: not-allowed;
    background: var(--bg-tertiary);
}

/* Running status with pulse animation */
.badge-running {
    background: rgba(255, 193, 7, 0.2);
    color: #ffc107;
    display: inline-flex;
    align-items: center;
    gap: 6px;
}

.pulse-dot {
    width: 8px;
    height: 8px;
    background: #ffc107;
    border-radius: 50%;
    animation: pulse 1.5s infinite;
}

@keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.5; transform: scale(0.8); }
}

.status-with-phase {
    display: flex;
    align-items: center;
}
</style>
