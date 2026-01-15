<template>
    <div class="updates-page">
        <div class="page-header">
            <h2>⬆️ Aggiornamenti Sistema</h2>
            <p class="text-secondary">Gestisci gli aggiornamenti di DAPX-Unified</p>
        </div>

        <!-- Stato Versione -->
        <div class="card version-card">
            <div class="card-header">
                <h3>📦 Versione Installata</h3>
                <button class="btn btn-secondary" @click="checkForUpdates" :disabled="checking">
                    {{ checking ? 'Controllo...' : '🔄 Verifica Aggiornamenti' }}
                </button>
            </div>
            <div class="card-body">
                <div class="version-info">
                    <div class="version-current">
                        <span class="label">Versione attuale:</span>
                        <span class="version-number">{{ currentVersion || 'N/A' }}</span>
                    </div>
                    
                    <div v-if="updateInfo" class="version-available" :class="{ 'has-update': updateInfo.update_available }">
                        <span class="label">Ultima versione:</span>
                        <span class="version-number">{{ updateInfo.available_version || 'N/A' }}</span>
                        <span v-if="updateInfo.update_available" class="badge badge-success">Aggiornamento disponibile!</span>
                        <span v-else class="badge badge-secondary">Aggiornato</span>
                    </div>
                    
                    <div v-if="updateInfo?.last_check" class="last-check">
                        <span class="text-secondary">Ultimo controllo: {{ formatDate(updateInfo.last_check) }}</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Changelog -->
        <div v-if="updateInfo?.changelog" class="card changelog-card">
            <div class="card-header">
                <h3>📝 Note di Rilascio</h3>
                <a v-if="updateInfo?.release_url" :href="updateInfo.release_url" target="_blank" class="btn btn-sm">
                    🔗 Vedi su GitHub
                </a>
            </div>
            <div class="card-body">
                <div v-if="updateInfo.release_date" class="release-date">
                    📅 {{ formatDate(updateInfo.release_date) }}
                </div>
                <pre class="changelog-content">{{ updateInfo.changelog }}</pre>
            </div>
        </div>

        <!-- Azione Aggiornamento -->
        <div v-if="updateInfo?.update_available" class="card action-card">
            <div class="card-header">
                <h3>🚀 Esegui Aggiornamento</h3>
            </div>
            <div class="card-body">
                <div class="warning-box">
                    <strong>⚠️ Attenzione:</strong>
                    <ul>
                        <li>Il servizio verrà riavviato durante l'aggiornamento</li>
                        <li>Verrà creato un backup automatico del database</li>
                        <li>L'operazione potrebbe richiedere alcuni minuti</li>
                    </ul>
                </div>
                <button 
                    class="btn btn-success btn-lg" 
                    @click="startUpdate" 
                    :disabled="updateStatus?.in_progress"
                >
                    {{ updateStatus?.in_progress ? '⏳ Aggiornamento in corso...' : '⬆️ Avvia Aggiornamento' }}
                </button>
            </div>
        </div>

        <!-- Log Aggiornamento -->
        <div v-if="updateStatus && (updateStatus.in_progress || updateStatus.log.length > 0)" class="card log-card">
            <div class="card-header">
                <h3>📋 Log Aggiornamento</h3>
                <span v-if="updateStatus.in_progress" class="badge badge-warning">In corso...</span>
                <span v-else-if="updateStatus.error" class="badge badge-danger">Errore</span>
                <span v-else-if="updateStatus.success" class="badge badge-success">Completato</span>
            </div>
            <div class="card-body">
                <div class="log-output" ref="logOutput">
                    <div v-for="(line, idx) in updateStatus.log" :key="idx" class="log-line">
                        {{ line }}
                    </div>
                </div>
                <div v-if="updateStatus.error" class="error-message">
                    ❌ {{ updateStatus.error }}
                </div>
            </div>
        </div>

        <!-- Alternative: Script da terminale -->
        <div class="card terminal-card">
            <div class="card-header">
                <h3>💻 Aggiornamento da Terminale</h3>
            </div>
            <div class="card-body">
                <p>In alternativa, puoi eseguire l'aggiornamento direttamente dal terminale:</p>
                <div class="code-block">
                    <code>/opt/dapx-unified/update.sh</code>
                    <button class="btn-copy" @click="copyCommand" title="Copia">📋</button>
                </div>
            </div>
        </div>
    </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue';
import updatesService from '../../services/updates';
import type { UpdateCheckResult, UpdateStatus } from '../../services/updates';

const currentVersion = ref<string>('');
const updateInfo = ref<UpdateCheckResult | null>(null);
const updateStatus = ref<UpdateStatus | null>(null);
const checking = ref(false);
const logOutput = ref<HTMLElement | null>(null);

let statusInterval: number | null = null;

const checkForUpdates = async () => {
    checking.value = true;
    try {
        const res = await updatesService.checkForUpdates();
        updateInfo.value = res.data;
        currentVersion.value = res.data.current_version;
    } catch (error) {
        console.error('Errore verifica aggiornamenti:', error);
    } finally {
        checking.value = false;
    }
};

const startUpdate = async () => {
    try {
        await updatesService.startUpdate();
        // Avvia polling stato
        startStatusPolling();
    } catch (error) {
        console.error('Errore avvio aggiornamento:', error);
    }
};

const fetchStatus = async () => {
    try {
        const res = await updatesService.getStatus();
        updateStatus.value = res.data;
        
        // Scroll to bottom del log
        if (logOutput.value) {
            logOutput.value.scrollTop = logOutput.value.scrollHeight;
        }
        
        // Ferma polling se completato
        if (!res.data.in_progress && statusInterval) {
            stopStatusPolling();
            // Refresh versione
            checkForUpdates();
        }
    } catch (error) {
        console.error('Errore fetch status:', error);
    }
};

const startStatusPolling = () => {
    fetchStatus();
    statusInterval = window.setInterval(fetchStatus, 2000);
};

const stopStatusPolling = () => {
    if (statusInterval) {
        clearInterval(statusInterval);
        statusInterval = null;
    }
};

const formatDate = (dateStr: string) => {
    if (!dateStr) return '';
    try {
        return new Date(dateStr).toLocaleString('it-IT');
    } catch {
        return dateStr;
    }
};

const copyCommand = () => {
    navigator.clipboard.writeText('/opt/dapx-unified/update.sh');
};

onMounted(() => {
    checkForUpdates();
    fetchStatus();
});

onUnmounted(() => {
    stopStatusPolling();
});
</script>

<style scoped>
.updates-page {
    padding: 2rem;
    max-width: 900px;
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

.version-info {
    display: flex;
    flex-direction: column;
    gap: 1rem;
}

.version-current, .version-available {
    display: flex;
    align-items: center;
    gap: 1rem;
}

.label {
    color: var(--text-secondary);
    min-width: 140px;
}

.version-number {
    font-size: 1.5rem;
    font-weight: 600;
    font-family: monospace;
}

.has-update .version-number {
    color: var(--color-success);
}

.last-check {
    margin-top: 0.5rem;
    font-size: 0.85rem;
}

.changelog-content {
    background: var(--bg-secondary);
    padding: 1rem;
    border-radius: 4px;
    white-space: pre-wrap;
    font-family: monospace;
    font-size: 0.9rem;
    max-height: 300px;
    overflow: auto;
}

.release-date {
    margin-bottom: 1rem;
    color: var(--text-secondary);
}

.warning-box {
    background: rgba(255, 193, 7, 0.1);
    border: 1px solid rgba(255, 193, 7, 0.3);
    border-radius: 4px;
    padding: 1rem;
    margin-bottom: 1.5rem;
}

.warning-box ul {
    margin: 0.5rem 0 0 1.5rem;
    padding: 0;
}

.btn-lg {
    padding: 1rem 2rem;
    font-size: 1.1rem;
}

.log-output {
    background: var(--bg-dark, #1a1a2e);
    color: var(--text-primary);
    padding: 1rem;
    border-radius: 4px;
    font-family: monospace;
    font-size: 0.85rem;
    max-height: 400px;
    overflow: auto;
}

.log-line {
    padding: 2px 0;
}

.error-message {
    margin-top: 1rem;
    padding: 1rem;
    background: rgba(220, 53, 69, 0.1);
    border: 1px solid rgba(220, 53, 69, 0.3);
    border-radius: 4px;
    color: var(--color-error);
}

.code-block {
    display: flex;
    align-items: center;
    gap: 1rem;
    background: var(--bg-secondary);
    padding: 1rem;
    border-radius: 4px;
    margin-top: 1rem;
}

.code-block code {
    flex: 1;
    font-family: monospace;
    font-size: 1rem;
}

.btn-copy {
    background: none;
    border: none;
    cursor: pointer;
    padding: 0.5rem;
    font-size: 1.2rem;
}

.btn-copy:hover {
    opacity: 0.7;
}

.badge {
    padding: 0.25rem 0.75rem;
    border-radius: 4px;
    font-size: 0.85rem;
    font-weight: 500;
}

.badge-success {
    background: rgba(40, 167, 69, 0.2);
    color: var(--color-success);
}

.badge-secondary {
    background: rgba(108, 117, 125, 0.2);
    color: var(--text-secondary);
}

.badge-warning {
    background: rgba(255, 193, 7, 0.2);
    color: #ffc107;
}

.badge-danger {
    background: rgba(220, 53, 69, 0.2);
    color: var(--color-error);
}
</style>
