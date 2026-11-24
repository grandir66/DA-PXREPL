<template>
 <div class="host-backup-page">
 <PageHeader
 :title="t('hostBackup.titolo')"
 :subtitle="t('hostBackup.sottotitolo')"
 icon="shield"
 />

 <div class="info-banner mb-6">
 <div class="icon"><Icon name="lightbulb" :size="20" /></div>
 <div class="content">
 <strong>{{ t('hostBackup.cose') }}</strong>
 <p>{{ t('hostBackup.coseNota') }}</p>
 <div class="mt-1 text-xs opacity-75">{{ t('hostBackup.utile') }}</div>
 </div>
 </div>

 <!-- Create Schedule Form -->
 <div class="card mb-6">
 <div class="card-header collapse-header" @click="showCreateForm = !showCreateForm">
 <h3>{{ t('hostBackup.creaTitolo') }}</h3>
 <span>{{ showCreateForm ? '▲' : '▼' }}</span>
 </div>
 
 <div class="card-body" v-show="showCreateForm">
 <div class="grid-2">
 <div class="form-group">
 <label>{{ t('hostBackup.nomeJob') }}</label>
 <input type="text" v-model="form.name" class="form-input" :placeholder="t('hostBackup.segnNome')">
 </div>
 <div class="form-group">
 <label>{{ t('comune.nodo') }}</label>
 <select v-model="form.node_id" class="form-input">
 <option :value="null" disabled>{{ t('hostBackup.selNodo') }}</option>
 <option v-for="node in nodes" :key="node.id" :value="node.id">
 {{ node.name }} ({{ node.node_type }})
 </option>
 </select>
 </div>
 </div>

 <div class="grid-3">
 <div class="form-group">
 <label>{{ t('hostBackup.pianificazione') }}</label>
 <!-- I valori sono cron: la parola «daily» che c'era prima lo scheduler
      la scartava a ogni avvio, e il backup non partiva mai (2026-09-13). -->
 <select v-model="form.schedule" class="form-input">
 <option :value="null">{{ t('hostBackup.manuale') }}</option>
 <option value="0 1 * * *">{{ t('hostBackup.giorno') }}</option>
 <option value="0 1 * * 0">{{ t('hostBackup.settimana') }}</option>
 </select>
 </div>
 <div class="form-group">
 <label>{{ t('hostBackup.conserva') }}</label>
 <input type="number" v-model.number="form.keep_last" class="form-input" min="1" max="100">
 </div>
 <div class="form-group">
 <label>{{ t('hostBackup.percorso') }}</label>
 <input type="text" v-model="form.dest_path" class="form-input" placeholder="/var/backups/proxmox-config">
 </div>
 </div>

 <div class="grid-2 mt-4">
 <label class="checkbox-label">
 <input type="checkbox" v-model="form.compress"> <Icon name="box" :size="14" /> {{ t('hostBackup.comprimi') }}
 </label>
 <div class="flex-col gap-2">
 <label class="checkbox-label">
 <input type="checkbox" v-model="form.encrypt"> <Icon name="lock" :size="14" /> {{ t('hostBackup.cifra') }}
 </label>
 <input v-if="form.encrypt" type="password" v-model="form.encrypt_password" class="form-input mt-1" :placeholder="t('hostBackup.segnPassword')">
 </div>
 </div>

 <div class="grid-2 mt-4">
 <div class="form-group">
 <label>{{ t('hostBackup.notifiche') }}</label>
 <select v-model="form.notify_mode" class="form-input">
 <option value="daily">{{ t('hostBackup.nDaily') }}</option>
 <option value="failure">{{ t('hostBackup.nFailure') }}</option>
 <option value="always">{{ t('hostBackup.nAlways') }}</option>
 <option value="never">{{ t('hostBackup.nNever') }}</option>
 </select>
 </div>
 <div class="form-group" v-if="form.notify_mode !== 'never' && form.notify_mode !== 'daily'">
 <label>{{ t('hostBackup.oggetto') }}</label>
 <input type="text" v-model="form.notify_subject" class="form-input" placeholder="[HOST BACKUP] config-{node_name}">
 </div>
 </div>

 <div class="mt-4 text-right">
 <button class="btn btn-primary" @click="createJob" :disabled="creating">
 {{ creating ? t('hostBackup.creazione') : t('hostBackup.crea') }}
 </button>
 </div>
 </div>
 </div>

 <!-- Scheduled Jobs List -->
 <div class="card mb-6">
 <div class="card-header">
 <h3>{{ t('hostBackup.configurati') }}</h3>
 <button class="btn btn-sm btn-secondary" @click="loadJobs">{{ t('comune.aggiorna') }}</button>
 </div>
 <div class="card-body p-0">
 <div class="table-container">
 <table class="data-table" v-if="jobs.length > 0">
 <thead>
 <tr>
 <th>{{ t('comune.nome') }}</th>
 <th>{{ t('comune.nodo') }}</th>
 <th>{{ t('hostBackup.pianificazione') }}</th>
 <th>{{ t('hostBackup.colConserva') }}</th>
 <th>{{ t('hostBackup.ultima') }}</th>
 <th>{{ t('comune.stato') }}</th>
 <th>{{ t('comune.azioni') }}</th>
 </tr>
 </thead>
 <tbody>
 <tr v-for="job in jobs" :key="job.id">
 <td class="font-bold">{{ job.name }}</td>
 <td>{{ job.node_name }}</td>
 <td :title="job.schedule || ''">{{ etichettaSchedule(job.schedule) }}</td>
 <td>{{ job.keep_last }}</td>
 <td class="text-xs">{{ formatDate(job.last_run) }}</td>
 <td>
 <span class="badge" :class="getStatusClass(job.last_status)">
 {{ job.last_status || t('hostBackup.mai') }}
 </span>
 </td>
 <td>
 <div class="btn-group">
 <button class="btn btn-xs btn-primary" @click="runJob(job)" :disabled="job.running">
 <Icon name="play" :size="14" />{{ t('hostBackup.esegui') }}
 </button>
 <button class="btn btn-xs btn-danger" @click="deleteJob(job)">
 <Icon name="trash" :size="14" />
 </button>
 </div>
 </td>
 </tr>
 </tbody>
 </table>
 <div v-else class="empty-state">
 {{ t('hostBackup.nessunJob') }}
 </div>
 </div>
 </div>
 </div>

 <!-- Manual Backup Section -->
 <div class="card">
 <div class="card-header">
 <h3>{{ t('hostBackup.rapido') }}</h3>
 </div>
 <div class="card-body">
 <div style="display: flex; gap: 12px; align-items: flex-end;">
 <div class="form-group" style="flex: 1;">
 <label>{{ t('comune.nodo') }}</label>
 <select v-model="manualNodeId" class="form-input">
 <option :value="null" disabled>{{ t('hostBackup.selNodo') }}</option>
 <option v-for="node in nodes" :key="node.id" :value="node.id">
 {{ node.name }}
 </option>
 </select>
 </div>
 <button class="btn btn-success" @click="runManualBackup" :disabled="!manualNodeId || runningManual">
 {{ runningManual ? t('hostBackup.esecuzione') : t('hostBackup.ora') }}
 </button>
 </div>
 </div>
 </div>

 <!-- Backup Files List -->
 <div class="card mb-6">
 <div class="card-header">
 <h3>{{ t('hostBackup.esistenti') }}</h3>
 <div style="display: flex; gap: 12px; align-items: center;">
 <select v-model="backupListNodeId" class="form-input" style="width: 200px;" @change="loadBackups">
 <option :value="null">{{ t('hostBackup.nodoSel') }}</option>
 <option v-for="node in nodes" :key="node.id" :value="node.id">
 {{ node.name }}
 </option>
 </select>
 <button class="btn btn-sm btn-secondary" @click="loadBackups" :disabled="!backupListNodeId">{{ t('comune.aggiorna') }}</button>
 </div>
 </div>
 <div class="card-body p-0">
 <div class="table-container">
 <table class="data-table" v-if="backups.length > 0">
 <thead>
 <tr>
 <th>{{ t('hostBackup.file') }}</th>
 <th>{{ t('comune.dimensione') }}</th>
 <th>{{ t('hostBackup.dataCreazione') }}</th>
 <th>{{ t('comune.azioni') }}</th>
 </tr>
 </thead>
 <tbody>
 <tr v-for="backup in backups" :key="backup.filename">
 <td class="font-mono text-sm">{{ backup.filename }}</td>
 <td>{{ backup.size_human }}</td>
 <td class="text-sm">{{ formatDate(backup.created_at) }}</td>
 <td>
 <div class="btn-group">
 <button class="btn btn-xs btn-secondary" @click="downloadBackup(backup)" :title="t('hostBackup.scarica')">
 <Icon name="download" :size="14" /> {{ t('hostBackup.scarica') }}
 </button>
 <button class="btn btn-xs btn-danger" @click="deleteBackup(backup)" :title="t('comune.elimina')">
 <Icon name="trash" :size="14" />
 </button>
 </div>
 </td>
 </tr>
 </tbody>
 </table>
 <div v-else-if="backupListNodeId && !loadingBackups" class="empty-state">
 {{ t('hostBackup.nessunBackup') }}
 </div>
 <div v-else-if="loadingBackups" class="empty-state">
 {{ t('hostBackup.carico') }}
 </div>
 <div v-else class="empty-state">
 {{ t('hostBackup.selPerVedere') }}
 </div>
 </div>
 </div>
 </div>
 </div>
</template>

<script setup lang="ts">
import { useToast, errorMessage } from '../stores/toast';
import { ref, reactive, onMounted } from 'vue';
import Icon from '../components/ui/Icon.vue';
import { confirmDangerous } from '../stores/confirm';
import PageHeader from '../components/ui/PageHeader.vue';
import apiClient from '../services/api';
import nodesService from '../services/nodes';
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const toast = useToast()

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
 if (!form.node_id) { toast.warning(t('hostBackup.serveNodo')); return; }
 creating.value = true;
 try {
 await apiClient.post('/host-backup/jobs', form);
 toast.success(t('hostBackup.creato'));
 loadJobs();
 showCreateForm.value = false;
 } catch (e: any) {
 toast.error(t('hostBackup.erroreCrea'), errorMessage(e));
 } finally {
 creating.value = false;
 }
};

const deleteJob = async (job: any) => {
 if (!await confirmDangerous(t('repliche.eliminare', { nome: job.name }))) return;
 try {
 await apiClient.delete(`/host-backup/jobs/${job.id}`);
 loadJobs();
 } catch (e) {
 toast.error(t('comune.erroreEliminazione'));
 }
}

const runJob = async (job: any) => {
 try {
 job.running = true;
 await apiClient.post(`/host-backup/jobs/${job.id}/run`);
 toast.success(t('hostBackup.fatto'), job.name);
 loadJobs();
 } catch (e: any) {
 toast.error(t('hostBackup.erroreEsegui'), errorMessage(e));
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
 toast.success(t('hostBackup.fattoMano'));
 loadJobs(); // Refresh if it impacts any list or just to be safe
 } catch (e: any) {
 toast.error(t('hostBackup.erroreMano'), errorMessage(e));
 } finally {
 runningManual.value = false;
 }
};

const etichettaSchedule = (cron: string | null) => {
 if (!cron) return t('hostBackup.pManuale');
 const m = cron.trim().match(/^(\d+) (\d+) \* \* (\*|[0-6])$/);
 if (!m) return cron;
 const ora = `${(m[2] ?? '').padStart(2, '0')}:${(m[1] ?? '').padStart(2, '0')}`;
 if (m[3] === '*') return t('hostBackup.pGiorno', { ora });
 return t('hostBackup.pSettimana', { giorno: t(`giorni.lunghi.${Number(m[3])}`), ora });
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
 if (!await confirmDangerous(t('hostBackup.confElimina', { file: backup.filename }))) return;
 try {
 await apiClient.delete(`/host-backup/nodes/${backupListNodeId.value}/backups`, {
  params: { backup_file: backup.filename },
 });
 loadBackups();
 } catch (e: any) {
 toast.error(t('comune.erroreEliminazione'), errorMessage(e));
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
 toast.error(t('hostBackup.erroreScarica'), errorMessage(e));
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

.btn-success { background: #00b894; color: var(--color-text-primary); border: none; }
.btn-success:hover { background: #00a383; }

@media (max-width: 768px) {
 .grid-2, .grid-3 { grid-template-columns: 1fr; }
}
</style>
