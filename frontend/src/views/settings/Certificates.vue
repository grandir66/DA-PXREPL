<template>
 <div class="certificates-page">
 <!-- Server Configuration Section -->
 <div class="card-section mb-6 settings-header-card">
 <div class="header-row">
 <h3 class="flex items-center gap-2">{{ t('certificati.server') }}</h3>
 <label class="checkbox-label">
 <input type="checkbox" v-model="serverConfig.ssl_enabled"> {{ t('certificati.https') }}
 </label>
 </div>
 
 <div class="mt-4">
 <div class="form-group" style="max-width: 200px;">
 <label>{{ t('certificati.porta') }}</label>
 <input type="number" v-model.number="serverConfig.port" class="form-input">
 <div class="text-xs text-secondary mt-1">{{ t('certificati.portaAttuale', { porta: initialPort }) }}</div>
 </div>

 <div class="actions-row mt-4">
 <button class="btn btn-primary" @click="saveServerConfig" :disabled="working">
 {{ t('certificati.salva') }}
 </button>
 <button v-if="restartRequired" class="btn btn-warning" disabled>
 {{ t('certificati.riavvio') }}
 </button>
 </div>
 </div>
 </div>

 <div class="header mb-4">
 <h3>{{ t('certificati.stato') }}</h3>
 <div class="status-indicators">
 <div class="indicator">
 HTTPS: <span :class="status?.ssl_enabled ? 'text-success' : 'text-danger'"><Icon :name="status?.ssl_enabled ? 'check-circle' : 'x-circle'" :size="14" /> {{ status?.ssl_enabled ? t('certificati.attivo') : t('certificati.disabilitato') }}</span>
 </div>
 <div class="indicator">
 {{ t('certificati.certificato') }} <span :class="status?.cert_exists ? 'text-success' : 'text-danger'"><Icon :name="status?.cert_exists ? 'check-circle' : 'x-circle'" :size="14" /> {{ status?.cert_exists ? t('comune.presente') : t('comune.assente') }}</span>
 </div>
 <div class="indicator" v-if="status?.cert_info">
 {{ t('certificati.validita') }} <span :class="status.cert_info.valid ? 'text-success' : 'text-danger'"><Icon :name="status.cert_info.valid ? 'check-circle' : 'x-circle'" :size="14" /> {{ status.cert_info.valid ? t('certificati.valido') : t('certificati.scaduto') }}</span>
 </div>
 <div class="indicator" v-if="status?.cert_info">
 {{ t('certificati.scadenza') }} <span>{{ t('certificati.giorni', { n: status.cert_info.days_remaining }) }}</span>
 </div>
 </div>
 </div>

 <!-- Actions: Generate or Upload -->
 <div class="actions-container">
 <!-- Generate Tab -->
 <div class="action-card">
 <h4 class="text-primary"><Icon name="wrench" :size="20" /> {{ t('certificati.autoTitolo') }}</h4>
 <p class="text-secondary text-sm mb-4">{{ t('certificati.autoNota') }}</p>
 
 <div class="grid-2">
 <div class="form-group">
 <label>Hostname</label>
 <input v-model="genForm.hostname" type="text" class="form-input" :placeholder="t('certificati.segnHost')">
 </div>
 <div class="form-group">
 <label>{{ t('certificati.validitaGiorni') }}</label>
 <input v-model.number="genForm.days_valid" type="number" class="form-input">
 </div>
 </div>

 <div class="form-group mt-2">
 <label>{{ t('certificati.ipExtra') }}</label>
 <input v-model="genForm.ip_addresses" type="text" class="form-input" :placeholder="t('certificati.segnIp')">
 </div>
 
 <button class="btn btn-primary mt-4" @click="generateCert" :disabled="working">
 {{ working ? t('certificati.generazione') : t('certificati.genera') }}
 </button>
 </div>

 <!-- Upload Tab -->
 <div class="action-card mt-6">
 <h4 class="text-info"><Icon name="upload" :size="20" /> {{ t('certificati.caricaTitolo') }}</h4>
 <p class="text-secondary text-sm mb-4">{{ t('certificati.caricaNota') }}</p>
 
 <div class="form-group">
 <label>{{ t('certificati.certPem') }}</label>
 <textarea v-model="uploadForm.certificate" class="form-input code-input" placeholder="-----BEGIN CERTIFICATE-----..."></textarea>
 </div>
 <div class="form-group">
 <label>{{ t('certificati.chiavePem') }}</label>
 <textarea v-model="uploadForm.private_key" class="form-input code-input" placeholder="-----BEGIN PRIVATE KEY-----..."></textarea>
 </div>
 
 <button class="btn btn-info mt-2" @click="uploadCert" :disabled="working">
 <Icon v-if="!working" name="upload" :size="14" /> {{ working ? t('comune.caricamento') : t('certificati.carica') }}
 </button>
 </div>
 </div>
 </div>
</template>

<script setup lang="ts">
import { useToast, errorMessage } from '../../stores/toast';
import { ref, reactive, onMounted } from 'vue';
import { confirmDangerous } from '../../stores/confirm';
import settingsService from '../../services/settings';
import Icon from '../../components/ui/Icon.vue';
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const toast = useToast()

const status = ref<any>(null);
const working = ref(false);
const serverConfig = reactive({ port: 8420, ssl_enabled: false });
const initialPort = ref(8420);
const restartRequired = ref(false);

const genForm = reactive({
 hostname: window.location.hostname.match(/^\d+\.\d+\.\d+\.\d+$/) ? 'dapx-unified.local' : window.location.hostname,
 days_valid: 365,
 ip_addresses: window.location.hostname.match(/^\d+\.\d+\.\d+\.\d+$/) ? window.location.hostname : ''
});

const uploadForm = reactive({
 certificate: '',
 private_key: ''
});

onMounted(() => {
 loadStatus();
 loadServerConfig();
});

const loadStatus = async () => {
 try {
 const res = await settingsService.getSSLStatus();
 status.value = res.data;
 } catch (e) {
 console.error("Error loading SSL status", e);
 }
};

const loadServerConfig = async () => {
 try {
 const res = await settingsService.getServerConfig();
 serverConfig.port = res.data.port;
 serverConfig.ssl_enabled = res.data.ssl_enabled;
 initialPort.value = res.data.port;
 restartRequired.value = res.data.restart_required;
 } catch (e) {
 console.error("Error loading server config", e);
 }
};

const saveServerConfig = async () => {
 working.value = true;
 try {
 await settingsService.updateServerConfig(serverConfig);
 toast.success(t('certificati.salvata'), t('certificati.riavvio'));
 loadServerConfig(); // Update restart required status
 } catch (e: any) {
 toast.error(t('comune.erroreSalvataggio'), errorMessage(e));
 } finally {
 working.value = false;
 }
}

const generateCert = async () => {
 if (!await confirmDangerous(t('certificati.confGenera'))) return;
 
 working.value = true;
 try {
 const payload = {
 ...genForm,
 ip_addresses: genForm.ip_addresses.split(',').map(ip => ip.trim()).filter(ip => ip)
 };
 await settingsService.generateCert(payload);
 toast.success(t('certificati.generato'));
 loadStatus();
 loadServerConfig(); // Should update ssl ready status
 } catch (e: any) {
 toast.error(t('certificati.erroreGenera'), errorMessage(e));
 } finally {
 working.value = false;
 }
};

// ... existing code for upload and delete ...
const uploadCert = async () => {
 if (!uploadForm.certificate || !uploadForm.private_key) {
 toast.warning(t('certificati.servono'));
 return;
 }
 
 working.value = true;
 try {
 await settingsService.uploadCert(uploadForm);
 toast.success(t('certificati.caricato'));
 uploadForm.certificate = '';
 uploadForm.private_key = '';
 loadStatus();
 loadServerConfig();
 } catch (e: any) {
 toast.error(t('certificati.erroreCarica'), errorMessage(e));
 } finally {
 working.value = false;
 }
};

</script>

<style scoped>
.mb-6 { margin-bottom: 24px; }
.mb-4 { margin-bottom: 16px; }
.mt-4 { margin-top: 16px; }
.mt-2 { margin-top: 8px; }
.gap-2 { gap: 8px; }
.flex { display: flex; }
.items-center { align-items: center; }

.settings-header-card {
 background: rgba(0, 209, 178, 0.05); /* Teal tint */
 border: 1px solid rgba(0, 209, 178, 0.2);
}

.header-row { display: flex; justify-content: space-between; align-items: center; }
.actions-row { display: flex; gap: 12px; align-items: center; }

.card-section { padding: 20px; border-radius: 8px; border: 1px solid var(--border-color); }
.status-indicators { display: flex; gap: 24px; margin-top: 8px; font-size: 0.9em; flex-wrap: wrap; }
.indicator { display: flex; gap: 6px; }

.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }

.text-success { color: #00b894; font-weight: 600; }
.text-danger { color: #ff5252; font-weight: 600; }
.text-primary { color: #00d1b2; }
.text-info { color: #00d1b2; } /* Matching the teal theme */
.text-xs { font-size: 0.75em; }

.btn-warning { background: rgba(255, 179, 0, 0.2); color: #ffb300; border: 1px solid rgba(255, 179, 0, 0.3); cursor: default; }

.action-card { padding: 24px; background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 8px; }

.form-group { margin-bottom: 12px; display: flex; flex-direction: column; gap: 6px; }
.form-input { width: 100%; padding: 10px; background: var(--bg-input); border: 1px solid var(--border-color); color: var(--text-primary); border-radius: 4px; }
.code-input { font-family: monospace; font-size: 0.8em; min-height: 120px; resize: vertical; }
.checkbox-label { display: flex; align-items: center; gap: 8px; font-weight: 500; cursor: pointer; }

@media (max-width: 768px) {
 .grid-2 { grid-template-columns: 1fr; }
 .status-indicators { flex-direction: column; gap: 8px; }
}
</style>
