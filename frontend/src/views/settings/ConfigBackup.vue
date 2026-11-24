<template>
 <div class="config-backup-page">
 <PageHeader
 :title="t('backupConfig.titolo')"
 :subtitle="t('backupConfig.sottotitolo')"
 icon="download"
 />

 <!-- System Info -->
 <div class="card info-card">
 <div class="card-header">
 <h3>{{ t('backupConfig.stato') }}</h3>
 <button class="btn btn-secondary btn-sm" @click="loadSystemInfo" :disabled="loading">
 {{ t('comune.aggiorna') }}
 </button>
 </div>
 <div class="card-body">
 <div v-if="systemInfo" class="system-info-grid">
 <div class="info-item">
 <span class="icon"><Icon name="monitor" :size="14" /></span>
 <div class="details">
 <span class="label">Hostname</span>
 <span class="value">{{ systemInfo.hostname }}</span>
 </div>
 </div>
 <div class="info-item">
 <span class="icon"><Icon name="box" :size="14" /></span>
 <div class="details">
 <span class="label">{{ t('comune.versione') }}</span>
 <span class="value">{{ systemInfo.version }}</span>
 </div>
 </div>
 <div class="info-item" :class="{ 'has-data': systemInfo.database.exists }">
 <span class="icon"><Icon name="archive" :size="14" /></span>
 <div class="details">
 <span class="label">{{ t('backupConfig.database') }}</span>
 <span class="value">{{ systemInfo.database.exists ? formatSize(systemInfo.database.size) : t('backupConfig.nonTrovato') }}</span>
 </div>
 </div>
 <div class="info-item" :class="{ 'has-data': systemInfo.ssh_keys.exists }">
 <span class="icon"><Icon name="key" :size="14" /></span>
 <div class="details">
 <span class="label">{{ t('backupConfig.chiavi') }}</span>
 <span class="value">{{ t('backupConfig.nChiavi', { n: systemInfo.ssh_keys.files.length }) }}</span>
 </div>
 </div>
 <div class="info-item" :class="{ 'has-data': systemInfo.certificates.exists }">
 <span class="icon"><Icon name="file-text" :size="14" /></span>
 <div class="details">
 <span class="label">{{ t('backupConfig.certificati') }}</span>
 <span class="value">{{ t('backupConfig.nFile', { n: systemInfo.certificates.files.length }) }}</span>
 </div>
 </div>
 <div class="info-item" :class="{ 'has-data': systemInfo.config.exists }">
 <span class="icon"><Icon name="settings" :size="14" /></span>
 <div class="details">
 <span class="label">{{ t('backupConfig.config') }}</span>
 <span class="value">{{ systemInfo.config.exists ? t('comune.presente') : t('backupConfig.nonTrovata') }}</span>
 </div>
 </div>
 </div>
 <div v-else class="text-center p-4">
 <span class="text-secondary">{{ t('comune.caricamento') }}</span>
 </div>
 </div>
 </div>

 <!-- Export Section -->
 <div class="card export-card">
 <div class="card-header">
 <h3>{{ t('backupConfig.esporta') }}</h3>
 </div>
 <div class="card-body">
 <p class="mb-4">{{ t('backupConfig.esportaNota') }}</p>
 
 <div class="options-grid">
 <label class="option-item">
 <input type="checkbox" v-model="exportOptions.database" />
 <span class="option-label"><Icon name="archive" :size="14" /> {{ t('backupConfig.eDatabase') }}</span>
 </label>
 <label class="option-item">
 <input type="checkbox" v-model="exportOptions.ssh_keys" />
 <span class="option-label"><Icon name="key" :size="14" /> {{ t('backupConfig.chiavi') }}</span>
 </label>
 <label class="option-item">
 <input type="checkbox" v-model="exportOptions.certificates" />
 <span class="option-label"><Icon name="file-text" :size="14" /> {{ t('backupConfig.eCertificati') }}</span>
 </label>
 <label class="option-item">
 <input type="checkbox" v-model="exportOptions.config" />
 <span class="option-label"><Icon name="settings" :size="14" /> {{ t('backupConfig.eConfig') }}</span>
 </label>
 </div>

 <div class="actions mt-4">
 <button class="btn btn-success" @click="createBackup" :disabled="exporting">
 {{ exporting ? t('backupConfig.creazione') : t('backupConfig.crea') }}
 </button>
 </div>
 </div>
 </div>

 <!-- Import Section -->
 <div class="card import-card">
 <div class="card-header">
 <h3>{{ t('backupConfig.importa') }}</h3>
 </div>
 <div class="card-body">
 <p class="mb-4">{{ t('backupConfig.importaNota') }}</p>
 
 <div class="upload-area" 
 @drop.prevent="handleDrop" 
 @dragover.prevent="isDragging = true"
 @dragleave="isDragging = false"
 :class="{ 'dragging': isDragging }">
 <input type="file" ref="fileInput" @change="handleFileSelect" accept=".tar.gz,.dapx-backup.tar.gz" hidden />
 <div class="upload-content" @click="fileInput?.click()">
 <span class="upload-icon"><Icon name="folder" :size="14" /></span>
 <span class="upload-text">{{ t('backupConfig.trascina') }}</span>
 <span class="upload-hint">.dapx-backup.tar.gz</span>
 </div>
 </div>

 <div v-if="selectedFile" class="selected-file mt-4">
 <span class="file-icon"><Icon name="box" :size="14" /></span>
 <span class="file-name">{{ selectedFile.name }}</span>
 <span class="file-size">({{ formatSize(selectedFile.size) }})</span>
 <button class="btn-remove" @click="selectedFile = null">✕</button>
 </div>

 <div v-if="selectedFile" class="options-grid mt-4">
 <label class="option-item">
 <input type="checkbox" v-model="importOptions.database" />
 <span class="option-label"><Icon name="archive" :size="14" /> {{ t('backupConfig.rDatabase') }}</span>
 </label>
 <label class="option-item">
 <input type="checkbox" v-model="importOptions.ssh_keys" />
 <span class="option-label"><Icon name="key" :size="14" /> {{ t('backupConfig.rChiavi') }}</span>
 </label>
 <label class="option-item">
 <input type="checkbox" v-model="importOptions.certificates" />
 <span class="option-label"><Icon name="file-text" :size="14" /> {{ t('backupConfig.rCertificati') }}</span>
 </label>
 <label class="option-item">
 <input type="checkbox" v-model="importOptions.config" />
 <span class="option-label"><Icon name="settings" :size="14" /> {{ t('backupConfig.rConfig') }}</span>
 </label>
 </div>

 <div v-if="selectedFile" class="warning-box mt-4">
 <strong><Icon name="alert-triangle" :size="14" /> {{ t('vm.attenzione') }}</strong>
 <ul>
 <li>{{ t('backupConfig.avviso1') }}</li>
 <li>{{ t('backupConfig.avviso2') }}</li>
 <li>{{ t('backupConfig.avviso3') }}</li>
 </ul>
 </div>

 <div v-if="selectedFile" class="actions mt-4">
 <button class="btn btn-warning" @click="restoreBackup" :disabled="importing">
 {{ importing ? t('backupConfig.ripristino') : t('backupConfig.ripristina') }}
 </button>
 </div>
 </div>
 </div>

 <!-- Restore Result -->
 <div v-if="restoreResult" class="card result-card" :class="restoreResult.success ? 'success' : 'error'">
 <div class="card-header">
 <h3><Icon :name="restoreResult.success ? 'check-circle' : 'x-circle'" :size="14" :class="restoreResult.success ? 'text-success' : 'text-danger'" /> {{ restoreResult.success ? t('backupConfig.fatto') : t('backupConfig.erroreTitolo') }}</h3>
 </div>
 <div class="card-body">
 <p>{{ restoreResult.message }}</p>
 
 <div v-if="restoreResult.restored_items.length" class="restored-items">
 <strong>{{ t('backupConfig.elementi') }}</strong>
 <ul>
 <li v-for="item in restoreResult.restored_items" :key="item">✓ {{ item }}</li>
 </ul>
 </div>
 
 <div v-if="restoreResult.warnings.length" class="warnings">
 <strong>{{ t('backupConfig.avvisi') }}</strong>
 <ul>
 <li v-for="warning in restoreResult.warnings" :key="warning"><Icon name="alert-triangle" :size="14" /> {{ warning }}</li>
 </ul>
 </div>
 </div>
 </div>

 <!-- Available Backups -->
 <div class="card backups-card">
 <div class="card-header">
 <h3>{{ t('backupConfig.disponibili') }}</h3>
 <button class="btn btn-secondary btn-sm" @click="loadBackups">{{ t('comune.aggiorna') }}</button>
 </div>
 <div class="card-body">
 <div v-if="backups.length === 0" class="text-center p-4">
 <span class="text-secondary">{{ t('backupConfig.nessuno') }}</span>
 </div>
 <table v-else class="table">
 <thead>
 <tr>
 <th>{{ t('backupConfig.file') }}</th>
 <th>{{ t('comune.data') }}</th>
 <th>{{ t('comune.dimensione') }}</th>
 <th>{{ t('backupConfig.origine') }}</th>
 <th>{{ t('backupConfig.contenuto') }}</th>
 <th>{{ t('comune.azioni') }}</th>
 </tr>
 </thead>
 <tbody>
 <tr v-for="backup in backups" :key="backup.filename">
 <td class="font-mono">{{ backup.filename }}</td>
 <td>{{ formatDate(backup.created_at) }}</td>
 <td>{{ formatSize(backup.size) }}</td>
 <td>{{ backup.source_hostname }} (v{{ backup.version }})</td>
 <td>
 <span v-if="backup.includes_database" class="badge" :title="t('backupConfig.database')"><Icon name="archive" :size="14" /></span>
 <span v-if="backup.includes_ssh_keys" class="badge" title="SSH"><Icon name="key" :size="14" /></span>
 <span v-if="backup.includes_certificates" class="badge" :title="t('backupConfig.certificati')"><Icon name="file-text" :size="14" /></span>
 <span v-if="backup.includes_config" class="badge" :title="t('backupConfig.config')"><Icon name="settings" :size="14" /></span>
 </td>
 <td>
 <button class="btn btn-sm btn-primary" @click="downloadBackup(backup.filename)">⬇️</button>
 <button class="btn btn-sm btn-danger" @click="deleteBackup(backup.filename)"><Icon name="trash" :size="14" /></button>
 </td>
 </tr>
 </tbody>
 </table>
 </div>
 </div>
 </div>
</template>

<script setup lang="ts">
import { useToast } from '../../stores/toast';
import { ref, onMounted, reactive } from 'vue';
import Icon from '../../components/ui/Icon.vue';
import { confirmDangerous } from '../../stores/confirm';
import PageHeader from '../../components/ui/PageHeader.vue';
import configBackupService from '../../services/configBackup';
import type { BackupInfo, BackupSystemInfo, RestoreResult } from '../../services/configBackup';
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const toast = useToast()

const loading = ref(false);
const exporting = ref(false);
const importing = ref(false);
const isDragging = ref(false);

const systemInfo = ref<BackupSystemInfo | null>(null);
const backups = ref<BackupInfo[]>([]);
const selectedFile = ref<File | null>(null);
const restoreResult = ref<RestoreResult | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);

const exportOptions = reactive({
 database: true,
 ssh_keys: true,
 certificates: true,
 config: true
});

const importOptions = reactive({
 database: true,
 ssh_keys: true,
 certificates: true,
 config: true
});

const loadSystemInfo = async () => {
 loading.value = true;
 try {
 const res = await configBackupService.getSystemInfo();
 systemInfo.value = res.data;
 } catch (error) {
 console.error('Errore caricamento info sistema:', error);
 } finally {
 loading.value = false;
 }
};

const loadBackups = async () => {
 try {
 const res = await configBackupService.listBackups();
 backups.value = res.data;
 } catch (error) {
 console.error('Errore caricamento backup:', error);
 }
};

const createBackup = async () => {
 exporting.value = true;
 try {
 const res = await configBackupService.createBackup({
 include_database: exportOptions.database,
 include_ssh_keys: exportOptions.ssh_keys,
 include_certificates: exportOptions.certificates,
 include_config: exportOptions.config
 });
 
 if (res.data.success) {
 toast.success(t('backupConfig.creato'), `${res.data.filename} — ${formatSize(res.data.size)}`);
 // Refresh lista
 loadBackups();
 // Scarica automaticamente
 downloadBackup(res.data.filename);
 }
 } catch (error) {
 console.error('Errore creazione backup:', error);
 toast.error(t('backupConfig.erroreCrea'));
 } finally {
 exporting.value = false;
 }
};

const downloadBackup = async (filename: string) => {
 try {
 const response = await configBackupService.downloadBackup(filename);
 
 // Crea URL blob e scarica
 const url = window.URL.createObjectURL(new Blob([response.data]));
 const link = document.createElement('a');
 link.href = url;
 link.setAttribute('download', filename);
 document.body.appendChild(link);
 link.click();
 
 // Cleanup
 window.URL.revokeObjectURL(url);
 document.body.removeChild(link);
 } catch (error) {
 console.error('Errore download backup:', error);
 toast.error(t('backupConfig.erroreScarica'));
 }
};

const handleFileSelect = (event: Event) => {
 const input = event.target as HTMLInputElement;
 if (input.files && input.files.length > 0) {
 selectedFile.value = input.files[0]!;
 restoreResult.value = null;
 }
};

const handleDrop = (event: DragEvent) => {
 isDragging.value = false;
 if (event.dataTransfer?.files && event.dataTransfer.files.length > 0) {
 selectedFile.value = event.dataTransfer.files[0]!;
 restoreResult.value = null;
 }
};

const restoreBackup = async () => {
 if (!selectedFile.value) return;
 
 if (!await confirmDangerous(t('backupConfig.confRipristina'))) {
 return;
 }
 
 importing.value = true;
 restoreResult.value = null;
 
 try {
 const res = await configBackupService.restoreBackup(selectedFile.value, {
 restore_database: importOptions.database,
 restore_ssh_keys: importOptions.ssh_keys,
 restore_certificates: importOptions.certificates,
 restore_config: importOptions.config
 });
 
 restoreResult.value = res.data;
 
 if (res.data.success) {
 selectedFile.value = null;
 }
 } catch (error: any) {
 restoreResult.value = {
 success: false,
 message: error.response?.data?.detail || t('backupConfig.erroreRipristino'),
 restored_items: [],
 warnings: []
 };
 } finally {
 importing.value = false;
 }
};

const deleteBackup = async (filename: string) => {
 if (!await confirmDangerous(`Eliminare il backup ${filename}?`)) return;
 
 try {
 await configBackupService.deleteBackup(filename);
 loadBackups();
 } catch (error) {
 console.error('Errore eliminazione backup:', error);
 toast.error(t('backupConfig.erroreElimina'));
 }
};

const formatSize = (bytes: number): string => {
 if (bytes === 0) return '0 B';
 const k = 1024;
 const sizes = ['B', 'KB', 'MB', 'GB'];
 const i = Math.floor(Math.log(bytes) / Math.log(k));
 return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
};

const formatDate = (dateStr: string): string => {
 if (!dateStr) return '';
 try {
 return new Date(dateStr).toLocaleString('it-IT');
 } catch {
 return dateStr;
 }
};

onMounted(() => {
 loadSystemInfo();
 loadBackups();
});
</script>

<style scoped>
.config-backup-page {
 padding: 2rem;
 max-width: 1000px;
}

.page-header {
 margin-bottom: 2rem;
}

.page-header h2 {
 margin: 0 0 0.5rem 0;
}

.card {
 background: var(--bg-surface);
 border: 1px solid var(--border-color);
 border-radius: 8px;
 margin-bottom: 1.5rem;
}

.card-header {
 padding: 1rem 1.5rem;
 border-bottom: 1px solid var(--border-color);
 display: flex;
 justify-content: space-between;
 align-items: center;
}

.card-header h3 {
 margin: 0;
 font-size: 1.1rem;
}

.card-body {
 padding: 1.5rem;
}

.system-info-grid {
 display: grid;
 grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
 gap: 1rem;
}

.info-item {
 display: flex;
 align-items: center;
 gap: 0.75rem;
 padding: 1rem;
 background: var(--bg-secondary);
 border-radius: 8px;
 border: 1px solid var(--border-color);
}

.info-item.has-data {
 border-color: var(--color-success);
 background: rgba(40, 167, 69, 0.05);
}

.info-item .icon {
 font-size: 1.5rem;
}

.info-item .details {
 display: flex;
 flex-direction: column;
}

.info-item .label {
 font-size: 0.75rem;
 color: var(--text-secondary);
}

.info-item .value {
 font-weight: 600;
}

.options-grid {
 display: grid;
 grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
 gap: 0.75rem;
}

.option-item {
 display: flex;
 align-items: center;
 gap: 0.5rem;
 padding: 0.75rem;
 background: var(--bg-secondary);
 border-radius: 4px;
 cursor: pointer;
}

.option-item:hover {
 background: var(--bg-hover);
}

.option-item input {
 accent-color: var(--accent-primary);
}

.upload-area {
 border: 2px dashed var(--border-color);
 border-radius: 8px;
 padding: 2rem;
 text-align: center;
 cursor: pointer;
 transition: all 0.2s;
}

.upload-area:hover,
.upload-area.dragging {
 border-color: var(--accent-primary);
 background: rgba(0, 255, 157, 0.05);
}

.upload-content {
 display: flex;
 flex-direction: column;
 align-items: center;
 gap: 0.5rem;
}

.upload-icon {
 font-size: 2.5rem;
}

.upload-hint {
 font-size: 0.85rem;
 color: var(--text-secondary);
}

.selected-file {
 display: flex;
 align-items: center;
 gap: 0.75rem;
 padding: 1rem;
 background: var(--bg-secondary);
 border-radius: 8px;
}

.file-icon {
 font-size: 1.5rem;
}

.file-name {
 font-weight: 500;
 flex: 1;
}

.file-size {
 color: var(--text-secondary);
}

.btn-remove {
 background: none;
 border: none;
 color: var(--text-secondary);
 cursor: pointer;
 font-size: 1.2rem;
}

.btn-remove:hover {
 color: var(--color-error);
}

.warning-box {
 background: rgba(255, 193, 7, 0.1);
 border: 1px solid rgba(255, 193, 7, 0.3);
 border-radius: 4px;
 padding: 1rem;
}

.warning-box ul {
 margin: 0.5rem 0 0 1.5rem;
 padding: 0;
}

.result-card.success {
 border-color: var(--color-success);
}

.result-card.error {
 border-color: var(--color-error);
}

.restored-items, .warnings {
 margin-top: 1rem;
}

.restored-items ul, .warnings ul {
 margin: 0.5rem 0 0 1rem;
 padding: 0;
}

.table {
 width: 100%;
 border-collapse: collapse;
}

.table th,
.table td {
 padding: 0.75rem;
 text-align: left;
 border-bottom: 1px solid var(--border-color);
}

.table th {
 font-weight: 600;
 color: var(--text-secondary);
 font-size: 0.85rem;
}

.font-mono {
 font-family: monospace;
 font-size: 0.85rem;
}

.badge {
 display: inline-block;
 padding: 0.25rem;
 margin-right: 0.25rem;
}

.actions {
 display: flex;
 gap: 1rem;
}
</style>
