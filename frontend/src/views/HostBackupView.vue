<template>
    <div class="host-backup-page">
        <div class="page-header">
            <h1 class="page-title">📦 Host Config Backup</h1>
            <p class="page-subtitle">Backup configurazione host Proxmox PVE e PBS</p>
        </div>

        <div class="info-banner mb-6">
            <div class="icon">💡</div>
            <div class="content">
                <strong>Cos'è l'Host Config Backup?</strong>
                <p>Backup dei file di configurazione del sistema Proxmox (non delle VM). Include: /etc/pve, /etc/network, configurazione cluster, chiavi SSH, cron jobs.</p>
                <div class="mt-1 text-xs opacity-75">Utile per: Disaster recovery, migrazioni server, ripristino configurazione.</div>
            </div>
        </div>

        <!-- Create Schedule Form -->
        <div class="card mb-6">
            <div class="card-header collapse-header" @click="showCreateForm = !showCreateForm">
                <h3>➕ Crea Job Host Backup Schedulato</h3>
                <span>{{ showCreateForm ? '▲' : '▼' }}</span>
            </div>
            
            <div class="card-body" v-show="showCreateForm">
                <div class="grid-2">
                    <div class="form-group">
                        <label>Nome Job</label>
                        <input type="text" v-model="form.name" class="form-input" placeholder="Backup Config PVE">
                    </div>
                     <div class="form-group">
                        <label>Nodo</label>
                        <select v-model="form.node_id" class="form-input">
                            <option :value="null" disabled>-- Seleziona nodo --</option>
                            <option v-for="node in nodes" :key="node.id" :value="node.id">
                                {{ node.name }} ({{ node.node_type }})
                            </option>
                        </select>
                    </div>
                </div>

                <div class="grid-3">
                    <div class="form-group">
                        <label>Schedule</label>
                        <select v-model="form.schedule" class="form-input">
                            <option :value="null">⏸️ Manuale (disattivato)</option>
                            <option value="daily">📅 Giornaliero (00:00)</option>
                            <option value="weekly">📅 Settimanale (Domenica)</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Retention (mantieni ultimi)</label>
                        <input type="number" v-model.number="form.keep_last" class="form-input" min="1" max="100">
                    </div>
                    <div class="form-group">
                        <label>Percorso Destinazione</label>
                        <input type="text" v-model="form.dest_path" class="form-input" placeholder="/var/backups/proxmox-config">
                    </div>
                </div>

                 <div class="grid-2 mt-4">
                    <label class="checkbox-label">
                        <input type="checkbox" v-model="form.compress"> 📦 Comprimi (gzip)
                    </label>
                     <div class="flex-col gap-2">
                        <label class="checkbox-label">
                            <input type="checkbox" v-model="form.encrypt"> 🔒 Cripta (AES-256)
                        </label>
                        <input v-if="form.encrypt" type="password" v-model="form.encrypt_password" class="form-input mt-1" placeholder="Password crittografia">
                    </div>
                </div>

                 <div class="grid-2 mt-4">
                     <div class="form-group">
                        <label>Notifiche Email</label>
                         <select v-model="form.notify_mode" class="form-input">
                            <option value="never">Mai</option>
                            <option value="always">Sempre</option>
                            <option value="failure">Solo su errore</option>
                            <option value="daily">📅 Solo nel riepilogo giornaliero</option>
                         </select>
                    </div>
                    <div class="form-group" v-if="form.notify_mode !== 'never' && form.notify_mode !== 'daily'">
                        <label>Soggetto Email</label>
                        <input type="text" v-model="form.notify_subject" class="form-input" placeholder="[HOST BACKUP] config-{node_name}">
                    </div>
                 </div>

                <div class="mt-4 text-right">
                    <button class="btn btn-primary" @click="createJob" :disabled="creating">
                        {{ creating ? 'Creazione...' : '+ Crea Job' }}
                    </button>
                </div>
            </div>
        </div>

        <!-- Scheduled Jobs List -->
        <div class="card mb-6">
            <div class="card-header">
                <h3>📋 Job Host Backup Configurati</h3>
                <button class="btn btn-sm btn-secondary" @click="loadJobs">🔄 Aggiorna</button>
            </div>
            <div class="card-body p-0">
                <div class="table-container">
                    <table class="data-table" v-if="jobs.length > 0">
                         <thead>
                            <tr>
                                <th>Nome</th>
                                <th>Nodo</th>
                                <th>Schedule</th>
                                <th>Retention</th>
                                <th>Ultimo Run</th>
                                <th>Stato</th>
                                <th>Azioni</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="job in jobs" :key="job.id">
                                <td class="font-bold">{{ job.name }}</td>
                                <td>{{ job.node_name }}</td>
                                <td>{{ job.schedule || 'Manuale' }}</td>
                                <td>{{ job.keep_last }}</td>
                                <td class="text-xs">{{ formatDate(job.last_run) }}</td>
                                <td>
                                    <span class="badge" :class="getStatusClass(job.last_status)">
                                        {{ job.last_status || 'Mai eseguito' }}
                                    </span>
                                </td>
                                <td>
                                    <div class="btn-group">
                                         <button class="btn btn-xs btn-primary" @click="runJob(job)" :disabled="job.running">
                                            ▶️ Run
                                        </button>
                                        <button class="btn btn-xs btn-danger" @click="deleteJob(job)">
                                            🗑️
                                        </button>
                                    </div>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                    <div v-else class="empty-state">
                        Nessun job configurato. Crea un nuovo job per iniziare.
                    </div>
                </div>
            </div>
        </div>

        <!-- Manual Backup Section -->
        <div class="card">
            <div class="card-header">
                <h3>⚡ Backup Manuale Rapido</h3>
            </div>
            <div class="card-body">
                <div style="display: flex; gap: 12px; align-items: flex-end;">
                     <div class="form-group" style="flex: 1;">
                        <label>Nodo</label>
                        <select v-model="manualNodeId" class="form-input">
                            <option :value="null" disabled>-- Seleziona nodo --</option>
                             <option v-for="node in nodes" :key="node.id" :value="node.id">
                                {{ node.name }}
                            </option>
                        </select>
                    </div>
                    <button class="btn btn-success" @click="runManualBackup" :disabled="!manualNodeId || runningManual">
                         {{ runningManual ? 'Esecuzione...' : '💾 Backup Ora' }}
                    </button>
                </div>
            </div>
        </div>

        <!-- Backup Files List -->
        <div class="card mb-6">
            <div class="card-header">
                <h3>📁 Backup Esistenti</h3>
                <div style="display: flex; gap: 12px; align-items: center;">
                    <select v-model="backupListNodeId" class="form-input" style="width: 200px;" @change="loadBackups">
                        <option :value="null">-- Nodo --</option>
                        <option v-for="node in nodes" :key="node.id" :value="node.id">
                            {{ node.name }}
                        </option>
                    </select>
                    <button class="btn btn-sm btn-secondary" @click="loadBackups" :disabled="!backupListNodeId">🔄 Aggiorna</button>
                </div>
            </div>
            <div class="card-body p-0">
                <div class="table-container">
                    <table class="data-table" v-if="backups.length > 0">
                        <thead>
                            <tr>
                                <th>File</th>
                                <th>Dimensione</th>
                                <th>Data Creazione</th>
                                <th>Azioni</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="backup in backups" :key="backup.filename">
                                <td class="font-mono text-sm">{{ backup.filename }}</td>
                                <td>{{ backup.size_human }}</td>
                                <td class="text-sm">{{ formatDate(backup.created_at) }}</td>
                                <td>
                                    <div class="btn-group">
                                        <button class="btn btn-xs btn-secondary" @click="downloadBackup(backup)" title="Download">
                                            📥 Download
                                        </button>
                                        <button class="btn btn-xs btn-danger" @click="deleteBackup(backup)" title="Elimina">
                                            🗑️
                                        </button>
                                    </div>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                    <div v-else-if="backupListNodeId && !loadingBackups" class="empty-state">
                        Nessun backup trovato per questo nodo.
                    </div>
                    <div v-else-if="loadingBackups" class="empty-state">
                        ⏳ Caricamento...
                    </div>
                    <div v-else class="empty-state">
                        Seleziona un nodo per visualizzare i backup.
                    </div>
                </div>
            </div>
        </div>
    </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue';
import apiClient from '../services/api';
import nodesService from '../services/nodes';

const nodes = ref<any[]>([]);
const jobs = ref<any[]>([]);
const showCreateForm = ref(true);
const creating = ref(false);
const runningManual = ref(false);
const manualNodeId = ref(null);

// Backup list state
const backups = ref<any[]>([]);
const backupListNodeId = ref<number | null>(null);
const loadingBackups = ref(false);

const form = reactive({
    name: 'Backup Config',
    node_id: null,
    schedule: null,
    keep_last: 7,
    dest_path: '/var/backups/proxmox-config',
    compress: true,
    encrypt: false,
    encrypt_password: '',
    notify_mode: 'daily',
    notify_subject: ''
});

onMounted(() => {
    loadNodes();
    loadJobs();
});

const loadNodes = async () => {
    try {
        const res = await nodesService.getNodes();
        nodes.value = res.data;
    } catch (e) {
        console.error("Error loading nodes", e);
    }
};

const loadJobs = async () => {
    try {
        const res = await apiClient.get('/host-backup/jobs');
        jobs.value = res.data.jobs;
    } catch (e) {
        console.error("Error loading jobs", e);
    }
};

const createJob = async () => {
    if (!form.node_id) { alert("Seleziona un nodo"); return; }
    creating.value = true;
    try {
        await apiClient.post('/host-backup/jobs', form);
        alert("Job creato con successo");
        loadJobs();
        showCreateForm.value = false;
    } catch (e: any) {
        alert("Errore creazione: " + (e.response?.data?.detail || e.message));
    } finally {
        creating.value = false;
    }
};

const deleteJob = async (job: any) => {
    if (!confirm(`Eliminare job ${job.name}?`)) return;
    try {
        await apiClient.delete(`/host-backup/jobs/${job.id}`);
        loadJobs();
    } catch (e) {
        alert("Errore eliminazione");
    }
}

const runJob = async (job: any) => {
    try {
        job.running = true;
        await apiClient.post(`/host-backup/jobs/${job.id}/run`);
        alert(`Backup ${job.name} avviato e completato!`);
        loadJobs();
    } catch (e: any) {
        alert("Errore esecuzione: " + (e.response?.data?.detail || e.message));
    } finally {
        job.running = false;
    }
};

const runManualBackup = async () => {
    if (!manualNodeId.value) return;
    runningManual.value = true;
    try {
        // Simple manual request defaults
        await apiClient.post(`/host-backup/nodes/${manualNodeId.value}/backup`, {
            dest_path: "/var/backups/proxmox-config",
            compress: true
        });
        alert("Backup manuale completato!");
        loadJobs(); // Refresh if it impacts any list or just to be safe
    } catch (e: any) {
        alert("Errore backup manuale: " + (e.response?.data?.detail || e.message));
    } finally {
        runningManual.value = false;
    }
};

const formatDate = (d: string) => {
    if (!d) return '-';
    return new Date(d).toLocaleString();
};

const getStatusClass = (s: string) => {
    if (s === 'success') return 'badge-success';
    if (s === 'failed') return 'badge-danger';
    return 'badge-secondary';
};

const loadBackups = async () => {
    if (!backupListNodeId.value) {
        backups.value = [];
        return;
    }
    loadingBackups.value = true;
    try {
        const res = await apiClient.get(`/host-backup/nodes/${backupListNodeId.value}/backups`);
        backups.value = res.data.backups || [];
    } catch (e: any) {
        console.error("Error loading backups", e);
        backups.value = [];
    } finally {
        loadingBackups.value = false;
    }
};

const deleteBackup = async (backup: any) => {
    if (!confirm(`Eliminare backup ${backup.filename}?`)) return;
    try {
        await apiClient.delete(`/host-backup/nodes/${backupListNodeId.value}/backups/${backup.filename}`);
        loadBackups();
    } catch (e: any) {
        alert("Errore eliminazione: " + (e.response?.data?.detail || e.message));
    }
};

const downloadBackup = async (backup: any) => {
    try {
        const response = await apiClient.get(
            `/host-backup/nodes/${backupListNodeId.value}/backups/${backup.filename}/download`,
            { responseType: 'blob' }
        );
        
        // Create download link
        const url = window.URL.createObjectURL(new Blob([response.data]));
        const link = document.createElement('a');
        link.href = url;
        link.setAttribute('download', backup.filename);
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.URL.revokeObjectURL(url);
    } catch (e: any) {
        alert("Errore download: " + (e.response?.data?.detail || e.message));
    }
};
</script>

<style scoped>
.info-banner { 
    background: rgba(0, 209, 255, 0.1); border-left: 4px solid #00d1b2; 
    padding: 16px; border-radius: 4px; display: flex; gap: 16px; 
}
.info-banner .icon { font-size: 24px; }
.info-banner strong { color: #00d1b2; font-size: 1.1em; display: block; margin-bottom: 4px; }
.info-banner p { margin: 0; color: var(--text-primary); font-size: 0.95em; }

.mb-6 { margin-bottom: 24px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; }
.form-group { margin-bottom: 12px; display: flex; flex-direction: column; gap: 6px; }
.flex-col { display: flex; flex-direction: column; }
.gap-2 { gap: 8px; }

.collapse-header { cursor: pointer; display: flex; justify-content: space-between; align-items: center; user-select: none; }
.collapse-header:hover { background: rgba(255,255,255,0.02); }

.empty-state { padding: 40px; text-align: center; color: var(--text-secondary); }

.badge-success { background: rgba(0, 184, 148, 0.15); color: #00b894; }
.badge-danger { background: rgba(255, 82, 82, 0.15); color: #ff5252; }
.badge-secondary { background: rgba(255, 255, 255, 0.1); color: var(--text-secondary); }

.btn-success { background: #00b894; color: white; border: none; }
.btn-success:hover { background: #00a383; }

@media (max-width: 768px) {
    .grid-2, .grid-3 { grid-template-columns: 1fr; }
}
</style>
