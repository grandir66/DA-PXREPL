<template>
  <div class="backup-jobs-page">
    <div class="page-header">
        <h1 class="page-title">Backup Jobs (PBS)</h1>
        <p class="page-subtitle">Backup automatici VM verso Proxmox Backup Server</p>
    </div>

    <!-- Info Banner -->
    <div class="info-banner mb-6">
        <div class="icon">☁️</div>
        <div>
            <strong>Backup verso PBS</strong>
            <p>Configura backup schedulati delle tue VM verso Proxmox Backup Server.</p>
            <p class="text-xs opacity-75">Funzionalità: Backup Incrementali • Compressione • Retention policy • Notifiche</p>
        </div>
    </div>

    <!-- Stats Cards -->
    <div class="stats-grid mb-6">
      <div class="stat-card">
        <div class="stat-value">{{ jobs.length }}</div>
        <div class="stat-label">Backup Jobs</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ activeJobsCount }}</div>
        <div class="stat-label">Attivi</div>
        <div class="stat-indicator active"></div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ successCount }}</div>
        <div class="stat-label">Ultimi OK</div>
        <div class="stat-indicator success"></div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ failureCount }}</div>
        <div class="stat-label">Falliti</div>
        <div class="stat-indicator failure"></div>
      </div>
    </div>

    <!-- Create Form Section -->
    <div class="create-section mb-8">
        <div class="section-title">+ Nuovo Backup Job</div>
        
        <div class="form-container">
            <!-- Row 1: Name -->
            <div class="form-row">
                <div class="form-group full-width">
                    <label>Nome Job</label>
                    <input type="text" v-model="form.job_name" class="form-input" placeholder="es: Backup-VM-Web">
                </div>
            </div>

            <!-- Row 2: Source Node & VM -->
            <div class="form-row">
                <div class="form-group">
                    <label>Nodo Sorgente (PVE)</label>
                    <select v-model="form.node_id" class="form-input" @change="onSourceNodeChange">
                        <option :value="null">-- Seleziona --</option>
                        <option v-for="node in pveNodes" :key="node.id" :value="node.id">{{ node.name }}</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>VM da backuppare</label>
                    <select v-model="form.vmid" class="form-input" :disabled="!form.node_id || loadingVMs">
                        <option :value="null">-- Seleziona VM --</option>
                        <option v-for="vm in vms" :key="vm.vmid" :value="vm.vmid">{{ vm.vmid }} - {{ vm.name }}</option>
                    </select>
                </div>
            </div>

            <!-- Row 3: Destination & Mode -->
            <div class="form-row three-col">
                <div class="form-group">
                    <label>Nodo PBS Destinazione</label>
                    <select v-model="form.pbs_node_id" class="form-input">
                        <option :value="null">-- Seleziona PBS --</option>
                        <option v-for="node in pbsNodes" :key="node.id" :value="node.id">{{ node.name }}</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Storage PBS (sul nodo sorgente)</label>
                    <select v-model="form.storage_id" class="form-input" :disabled="!form.node_id || loadingStorages">
                         <option value="">-- Seleziona Storage --</option>
                         <option v-for="s in pbsStorages" :key="s.storage" :value="s.storage">{{ s.storage }}</option>
                    </select>
                    <div class="help-text" v-if="!form.node_id">Seleziona prima il nodo sorgente</div>
                </div>
                <div class="form-group">
                    <label>Modalità Backup</label>
                    <select v-model="form.mode" class="form-input">
                        <option value="snapshot">Snapshot (Live)</option>
                        <option value="suspend">Suspend</option>
                        <option value="stop">Stop</option>
                    </select>
                </div>
            </div>

            <!-- Row 4: Schedule -->
             <div class="form-row">
                <div class="form-group full-width">
                    <label>Schedule</label>
                    <select v-model="cronPreset" @change="onCronPreset" class="form-input">
                        <option value="manual">🔒 Manuale (disattivato)</option>
                        <option value="hourly">⏰ Ogni ora (0 * * * *)</option>
                        <option value="daily">📅 Giornaliero (0 0 * * *)</option>
                        <option value="custom">✏️ Personalizzato</option>
                    </select>
                    <input v-if="cronPreset === 'custom'" type="text" v-model="form.schedule" class="form-input mt-2" placeholder="*/15 * * * *">
                </div>
            </div>

            <!-- Row 5: Retention & Compression & Subject -->
            <div class="form-row three-col">
                <div class="form-group">
                    <label>Mantieni ultimi N backup</label>
                    <input type="number" v-model="form.keep_last" class="form-input" min="1">
                </div>
                <div class="form-group">
                    <label>Compressione</label>
                    <select v-model="form.compression" class="form-input">
                        <option value="zstd">ZSTD (Consigliato)</option>
                        <option value="lz4">LZ4 (Veloce)</option>
                        <option value="gzip">GZIP</option>
                        <option value="none">Nessuna</option>
                    </select>
                </div>
                 <div class="form-group">
                    <label>Soggetto Email</label>
                    <input type="text" v-model="form.email_subject" class="form-input" placeholder="[BACKUP] {vm_name}">
                </div>
            </div>

             <!-- Row 6: Notify & Button -->
            <div class="form-row button-row">
                <div class="form-group flex-grow">
                    <label>Notifiche Email</label>
                    <select v-model="form.notify_mode" class="form-input">
                         <option value="daily">📅 Solo nel riepilogo giornaliero</option>
                         <option value="always">Sempre</option>
                         <option value="failure">Solo errori</option>
                         <option value="never">Mai</option>
                    </select>
                </div>
                 <div class="form-group button-container">
                    <button class="btn btn-create" @click="createJob" :disabled="creating">
                        {{ creating ? 'Creazione...' : '+ Crea Backup Job' }}
                    </button>
                </div>
            </div>

        </div>
    </div>

    <!-- Job List Section -->
    <div class="list-section">
        <div class="section-title">
             <span class="icon">📋</span> Backup Jobs Configurati
        </div>
        <div class="table-container">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Job Name</th>
                        <th>Sorgente</th>
                        <th>Destinazione</th>
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
                        <td>
                            <div>{{ job.node_name }}</div>
                            <div class="badge badge-info mt-1">VM {{ job.vmid }}</div>
                        </td>
                        <td>
                            <div>{{ job.pbs_node_name || 'PBS' }}</div>
                            <div class="text-xs text-secondary">{{ job.storage_id }}</div>
                        </td>
                         <td>
                             <code v-if="job.schedule && job.schedule !== 'manual'">{{ job.schedule }}</code>
                             <span v-else class="text-secondary">Manuale</span>
                        </td>
                        <td>
                            <div v-if="job.last_run">{{ formatDate(job.last_run) }}</div>
                            <div v-if="job.last_duration" class="text-secondary text-xs">
                                {{ job.last_duration_seconds }}s
                            </div>
                        </td>
                         <td>
                            <span class="badge" :class="getStatusClass(job.last_status)">
                                {{ job.last_status || 'Never' }}
                            </span>
                        </td>
                        <td>
                             <div class="btn-group">
                                <button class="btn btn-primary btn-xs" @click="runJob(job)" :disabled="job.last_status === 'running'">▶️</button>
                                <button class="btn btn-danger btn-xs" @click="deleteJob(job)">🗑️</button>
                            </div>
                        </td>
                    </tr>
                     <tr v-if="jobs.length === 0 && !loading">
                         <td colspan="7" class="empty-state-cell">Nessun backup job configurato. Crea il primo backup sopra.</td>
                    </tr>
                     <tr v-if="loading">
                         <td colspan="7" class="empty-state-cell">Caricamento jobs...</td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>

  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue';
import backupJobsService, { type BackupJob } from '../../services/backupJobs';
import nodesService, { type Node } from '../../services/nodes';
import vmsService from '../../services/vms';

const jobs = ref<BackupJob[]>([]);
const nodes = ref<Node[]>([]);
const vms = ref<any[]>([]);
const pbsStorages = ref<any[]>([]);

const loading = ref(false);
const loadingVMs = ref(false);
const loadingStorages = ref(false);
const creating = ref(false);

const cronPreset = ref('manual');

const form = reactive({
    job_name: '',
    node_id: null as number | null,
    vmid: null as number | null,
    pbs_node_id: null as number | null,
    storage_id: '',
    mode: 'snapshot',
    schedule: '',
    keep_last: 3,
    compression: 'zstd',
    email_subject: '[BACKUP] {vm_name}',
    notify_mode: 'daily'
});

const pveNodes = computed(() => nodes.value.filter(n => n.node_type !== 'pbs'));
const pbsNodes = computed(() => nodes.value.filter(n => n.node_type === 'pbs'));

const activeJobsCount = computed(() => jobs.value.filter(j => j.schedule && j.schedule !== 'manual').length);
const successCount = computed(() => jobs.value.filter(j => j.last_status === 'success' || j.last_status === 'OK').length);
const failureCount = computed(() => jobs.value.filter(j => j.last_status === 'failed' || j.last_status === 'error').length);

onMounted(() => {
    loadJobs();
    loadNodes();
});

const loadJobs = async () => {
    loading.value = true;
    try {
        const res = await backupJobsService.getJobs();
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

const onSourceNodeChange = async () => {
    if (!form.node_id) {
        vms.value = [];
        pbsStorages.value = [];
        return;
    }
    
    loadingVMs.value = true;
    loadingStorages.value = true;
    
    // Load VMs
    try {
         const res = await vmsService.getNodeVMs(form.node_id);
         vms.value = res.data;
    } catch(e) { console.error(e); } finally { loadingVMs.value = false; }
    
    // Load Storages
    try {
        const res = await nodesService.getStorages(form.node_id);
        // Filter for PBS storages
        pbsStorages.value = (res.data.storages || []).filter((s:any) => s.type === 'pbs');
    } catch(e) { console.error(e); } finally { loadingStorages.value = false; }
};

const onCronPreset = () => {
    if (cronPreset.value === 'manual') form.schedule = '';
    else if (cronPreset.value === 'hourly') form.schedule = '0 * * * *';
    else if (cronPreset.value === 'daily') form.schedule = '0 0 * * *';
};

const createJob = async () => {
    if (!form.job_name || !form.node_id || !form.vmid || !form.storage_id) {
        alert("Compila tutti i campi obbligatori (Nome, Nodo Sorgente, VM, Storage PBS)");
        return;
    }
    
    creating.value = true;
    
    // Find missing names
    const node = pveNodes.value.find(n => n.id === form.node_id);
    const pbsNode = pbsNodes.value.find(n => n.id === form.pbs_node_id);
    
    const payload = {
        job_name: form.job_name,
        node_id: form.node_id,
        node_name: node?.name,
        vmid: form.vmid,
        pbs_node_id: form.pbs_node_id, // Optional?
        pbs_node_name: pbsNode?.name,
        storage_id: form.storage_id,
        mode: form.mode,
        schedule: form.schedule || 'manual',
        compression: form.compression,
        keep_last: form.keep_last,
        email_subject: form.email_subject,
        notify_mode: form.notify_mode
    };
    
    try {
        await backupJobsService.createJob(payload);
        loadJobs();
        // Reset form partially
        form.job_name = '';
        alert("Job creato con successo!");
    } catch (e: any) {
        alert("Errore creazione: " + (e.response?.data?.detail || e.message));
    } finally {
        creating.value = false;
    }
};

const runJob = async (job: any) => {
    if (!confirm(`Avviare job ${job.job_name}?`)) return;
    try {
        await backupJobsService.runJob(job.id);
        loadJobs();
    } catch (e) { alert("Errore avvio job"); }
};

const deleteJob = async (job: any) => {
    if (!confirm(`Eliminare job ${job.job_name}?`)) return;
    try {
        await backupJobsService.deleteJob(job.id);
        loadJobs();
    } catch (e) { alert("Errore eliminazione job"); }
};

const formatDate = (d: string) => new Date(d).toLocaleString();
const getStatusClass = (s: string) => {
    if (s === 'success' || s === 'OK') return 'badge-success';
    if (s === 'failed' || s === 'error') return 'badge-danger';
    if (s === 'running') return 'badge-warning';
    return 'badge-secondary';
};

</script>

<style scoped>
.backup-jobs-page {
    /* max-width: 1600px; margin: 0 auto; Not needed if main layout handles padding */
}

/* Info Banner */
.info-banner {
    background: rgba(0, 212, 255, 0.05);
    border-left: 4px solid #00d4ff;
    padding: 16px;
    border-radius: 4px;
    display: flex;
    gap: 16px;
    align-items: flex-start;
}
.info-banner .icon { font-size: 24px; }
.info-banner strong { color: #00d4ff; font-size: 1.1em; display: block; margin-bottom: 4px; }
.info-banner p { margin: 0; color: var(--text-primary); font-size: 0.95em; line-height: 1.4; }

/* Stats */
.stats-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
}
.stat-card {
    background: var(--bg-secondary);
    padding: 16px;
    border-radius: 8px;
    border: 1px solid var(--border-color);
    position: relative;
    overflow: hidden;
}
.stat-value { font-size: 1.8rem; font-weight: 700; color: white; margin-bottom: 4px; }
.stat-label { font-size: 0.8rem; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; }
.stat-indicator { position: absolute; left: 0; top: 0; bottom: 0; width: 4px; }
.stat-indicator.active { background: #00d4ff; }
.stat-indicator.success { background: #00b894; }
.stat-indicator.failure { background: #ff5252; }

/* Create Section */
.create-section {
    background: var(--bg-secondary);
    border-radius: 8px;
    border: 1px solid var(--border-color);
    padding: 20px;
}
.section-title {
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.form-container {
    display: flex;
    flex-direction: column;
    gap: 16px;
}
.form-row {
    display: flex;
    gap: 20px;
}
.three-col {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
}
.form-group {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 6px;
}
.full-width { width: 100%; }
.form-group label {
    font-size: 0.8rem;
    color: var(--text-secondary);
    font-weight: 500;
}
.form-input {
    padding: 10px 12px;
    background: var(--bg-input); /* Fallback or define in CSS var */
    background-color: #1a1a2e; /* Dark theme default */
    border: 1px solid var(--border-color);
    border-radius: 4px;
    color: white;
    font-size: 0.9rem;
}
.form-input:focus {
    border-color: #00d4ff;
    outline: none;
}
.form-input:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.help-text { font-size: 0.75rem; color: var(--text-secondary); margin-top: 2px; }

.button-row { align-items: flex-end; }
.button-container { flex: 0 0 auto; }
.btn-create {
    background: linear-gradient(135deg, #00b894 0%, #00a884 100%);
    color: white;
    font-weight: 600;
    padding: 10px 24px;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    white-space: nowrap;
    height: 40px; /* match input height approx */
    display: flex;
    align-items: center;
    justify-content: center;
}
.btn-create:hover { filter: brightness(1.1); }
.btn-create:disabled { filter: grayscale(1); opacity: 0.7; }

/* List Section */
.list-section {
    background: var(--bg-secondary);
    border-radius: 8px;
    border: 1px solid var(--border-color);
    padding: 20px;
}
.data-table { width: 100%; border-collapse: collapse; }
.data-table th { text-align: left; padding: 12px; color: var(--text-secondary); border-bottom: 1px solid var(--border-color); font-size: 0.8rem; text-transform: uppercase; }
.data-table td { padding: 12px; border-bottom: 1px solid var(--border-color); }
.badge { padding: 4px 8px; border-radius: 4px; font-size: 0.75rem; display: inline-block; }
.badge-info { background: rgba(0, 212, 255, 0.15); color: #00d4ff; }
.badge-success { background: rgba(0, 184, 148, 0.15); color: #00b894; }
.badge-danger { background: rgba(255, 82, 82, 0.15); color: #ff5252; }
.badge-warning { background: rgba(255, 179, 0, 0.15); color: #ffb300; }
.badge-secondary { background: rgba(255, 255, 255, 0.1); color: #ccc; }

.text-xs { font-size: 0.75rem; }
.text-secondary { color: var(--text-secondary); }
.mt-1 { margin-top: 4px; }
.mt-2 { margin-top: 8px; }
.mb-6 { margin-bottom: 24px; }
.mb-8 { margin-bottom: 32px; }

.btn-group { display: flex; gap: 6px; }
.btn-xs { padding: 4px 8px; font-size: 0.8rem; border-radius: 4px; border: none; cursor: pointer; }
.btn-primary { background: var(--bg-hover); color: white; border: 1px solid var(--border-color); }
.btn-danger { background: rgba(255, 82, 82, 0.2); color: #ff5252; border: 1px solid #ff5252; }

/* Responsive adjustments */
@media (max-width: 1024px) {
    .stats-grid { grid-template-columns: 1fr 1fr; }
    .three-col { grid-template-columns: 1fr; }
    .form-row { flex-direction: column; gap: 12px; }
}
</style>

