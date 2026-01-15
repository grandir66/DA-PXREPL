<template>
    <div class="certificates-page">
        <!-- Server Configuration Section -->
        <div class="card-section mb-6 settings-header-card">
            <div class="header-row">
                 <h3 class="flex items-center gap-2">⚙️ Configurazione Server</h3>
                 <label class="checkbox-label">
                    <input type="checkbox" v-model="serverConfig.ssl_enabled"> Abilita HTTPS
                </label>
            </div>
           
            <div class="mt-4">
                 <div class="form-group" style="max-width: 200px;">
                    <label>Porta Web Server</label>
                    <input type="number" v-model.number="serverConfig.port" class="form-input">
                    <div class="text-xs text-secondary mt-1">Porta attuale: {{ initialPort }}</div>
                </div>

                <div class="actions-row mt-4">
                    <button class="btn btn-primary" @click="saveServerConfig" :disabled="working">
                        💾 Salva Configurazione
                    </button>
                    <button v-if="restartRequired" class="btn btn-warning" disabled>
                        ⚠️ Riavvio richiesto per applicare le modifiche
                    </button>
                </div>
            </div>
        </div>

        <div class="header mb-4">
            <h3>🔒 Stato SSL/HTTPS</h3>
             <div class="status-indicators">
                <div class="indicator">
                    HTTPS: <span :class="status?.ssl_enabled ? 'text-success' : 'text-danger'">{{ status?.ssl_enabled ? '✅ Attivo' : '❌ Disabilitato' }}</span>
                </div>
                 <div class="indicator">
                    Certificato: <span :class="status?.cert_exists ? 'text-success' : 'text-danger'">{{ status?.cert_exists ? '✅ Presente' : '❌ Assente' }}</span>
                </div>
                <div class="indicator" v-if="status?.cert_info">
                    Validità: <span :class="status.cert_info.valid ? 'text-success' : 'text-danger'">{{ status.cert_info.valid ? '✅ Valido' : '❌ Scaduto/Invalido' }}</span>
                </div>
                 <div class="indicator" v-if="status?.cert_info">
                    Scadenza: <span>{{ status.cert_info.days_remaining }} giorni</span>
                </div>
            </div>
        </div>

        <!-- Actions: Generate or Upload -->
        <div class="actions-container">
            <!-- Generate Tab -->
            <div class="action-card">
                <h4 class="text-primary">🛠️ Genera Certificato Auto-firmato</h4>
                <p class="text-secondary text-sm mb-4">Genera automaticamente un certificato SSL auto-firmato. Utile per ambienti di sviluppo o reti interne.</p>
                
                <div class="grid-2">
                    <div class="form-group">
                        <label>Hostname</label>
                        <input v-model="genForm.hostname" type="text" class="form-input" placeholder="es. server.local">
                    </div>
                     <div class="form-group">
                        <label>Validità (giorni)</label>
                        <input v-model.number="genForm.days_valid" type="number" class="form-input">
                    </div>
                </div>

                 <div class="form-group mt-2">
                    <label>IP Aggiuntivi (opzionale, separati da virgola)</label>
                    <input v-model="genForm.ip_addresses" type="text" class="form-input" placeholder="es. 192.168.1.10, 10.0.0.5">
                </div>
                
                <button class="btn btn-primary mt-4" @click="generateCert" :disabled="working">
                    {{ working ? 'Generazione...' : '⚡ Genera Certificato' }}
                </button>
            </div>

            <!-- Upload Tab -->
            <div class="action-card mt-6">
                <h4 class="text-info">📤 Carica Certificato Personalizzato</h4>
                <p class="text-secondary text-sm mb-4">Carica un certificato SSL esistente (es. da Let's Encrypt o CA aziendale). Formato PEM richiesto.</p>
                
                <div class="form-group">
                    <label>Certificato (PEM)</label>
                    <textarea v-model="uploadForm.certificate" class="form-input code-input" placeholder="-----BEGIN CERTIFICATE-----..."></textarea>
                </div>
                <div class="form-group">
                    <label>Chiave Privata (PEM)</label>
                    <textarea v-model="uploadForm.private_key" class="form-input code-input" placeholder="-----BEGIN PRIVATE KEY-----..."></textarea>
                </div>
                
                <button class="btn btn-info mt-2" @click="uploadCert" :disabled="working">
                    {{ working ? 'Caricamento...' : '📤 Carica Certificato' }}
                </button>
            </div>
        </div>
    </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue';
import settingsService from '../../services/settings';

const status = ref<any>(null);
const working = ref(false);
const serverConfig = reactive({ port: 8420, ssl_enabled: false });
const initialPort = ref(8420);
const restartRequired = ref(false);

const genForm = reactive({
    hostname: window.location.hostname,
    days_valid: 365,
    ip_addresses: ''
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
        alert("Configurazione salvata. Riavvio richiesto per applicare le modifiche.");
        loadServerConfig(); // Update restart required status
    } catch (e: any) {
        alert("Errore salvataggio: " + (e.response?.data?.detail || e.message));
    } finally {
        working.value = false;
    }
}

const generateCert = async () => {
    if (!confirm("Generare un nuovo certificato sovrascriverà quello esistente. Continuare?")) return;
    
    working.value = true;
    try {
        const payload = {
            ...genForm,
            ip_addresses: genForm.ip_addresses.split(',').map(ip => ip.trim()).filter(ip => ip)
        };
        await settingsService.generateCert(payload);
        alert("Certificato generato con successo!");
        loadStatus();
        loadServerConfig(); // Should update ssl ready status
    } catch (e: any) {
        alert("Errore generazione: " + (e.response?.data?.detail || e.message));
    } finally {
        working.value = false;
    }
};

// ... existing code for upload and delete ...
const uploadCert = async () => {
    if (!uploadForm.certificate || !uploadForm.private_key) {
        alert("Inserire certificato e chiave privata");
        return;
    }
    
    working.value = true;
    try {
        await settingsService.uploadCert(uploadForm);
        alert("Certificato caricato con successo!");
        uploadForm.certificate = '';
        uploadForm.private_key = '';
        loadStatus();
        loadServerConfig();
    } catch (e: any) {
        alert("Errore caricamento: " + (e.response?.data?.detail || e.message));
    } finally {
        working.value = false;
    }
};

const deleteCert = async () => {
    if (!confirm("Eliminare il certificato SSL? HTTPS smetterà di funzionare.")) return;
    
    try {
        await settingsService.deleteCert();
        alert("Certificato eliminato");
        loadStatus();
        loadServerConfig();
    } catch (e) {
        alert("Errore eliminazione");
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
