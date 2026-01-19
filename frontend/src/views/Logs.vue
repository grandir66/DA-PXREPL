<template>
  <div class="logs-page">
    <div class="page-header">
        <h1 class="page-title">📜 Logs</h1>
        <p class="page-subtitle">Registro eventi, backup e sistema</p>
        
        <div class="tabs-header">
            <button 
                class="tab-btn" 
                :class="{ active: activeTab === 'jobs' }" 
                @click="activeTab = 'jobs'">
                🔄 Job History
            </button>
            <button 
                class="tab-btn" 
                :class="{ active: activeTab === 'system' }" 
                @click="activeTab = 'system'; loadSystemFiles()">
                🖥️ System Logs
            </button>
        </div>
    </div>

    <!-- JOB LOGS TAB -->
    <div v-if="activeTab === 'jobs'" class="tab-content">
        <div class="controls-bar">
            <button class="btn btn-secondary btn-sm" @click="loadLogs(1)" :disabled="loading">
                <span v-if="loading" class="spinner-sm"></span>
                <span v-else>🔄 Aggiorna</span>
            </button>
            <button class="btn btn-danger btn-sm" @click="clearLogs">
                🗑️ Pulisci Log
            </button>
            <select v-model="filterLevel" @change="loadLogs(1)" class="form-input" style="width: auto;">
                <option value="">Tutti gli stati</option>
                <option value="success">Success</option>
                <option value="failed">Failed</option>
                <option value="running">Running</option>
            </select>
        </div>

        <div class="card">
            <div class="table-container">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Timestamp</th>
                            <th>Job Type</th>
                            <th>Stato</th>
                            <th>Job Info</th>
                            <th>Messaggio</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="log in logs" :key="log.id">
                            <td class="text-sm font-mono whitespace-nowrap">
                                {{ formatDate(log.started_at) }}
                            </td>
                            <td>
                                <span class="badge badge-secondary">{{ log.job_type }}</span>
                            </td>
                            <td>
                                <span class="badge" :class="getStatusClass(log.status)">
                                    {{ log.status }}
                                </span>
                            </td>
                            <td class="text-sm">
                                <div v-if="log.node_name || log.dataset" class="font-bold">{{ log.node_name }} / {{ log.dataset }}</div>
                                <div v-if="log.job_id" class="text-xs text-secondary">Job #{{ log.job_id }}</div>
                            </td>
                            <td class="text-sm">
                                {{ log.message }}
                                <div v-if="log.error" class="text-xs text-danger mt-1 font-mono bg-dark p-1 rounded">
                                    {{ log.error }}
                                </div>
                            </td>
                        </tr>
                        <tr v-if="logs.length === 0 && !loading">
                            <td colspan="5" class="empty-state-cell">Nessun log trovato</td>
                        </tr>
                    </tbody>
                </table>
            </div>
            
            <div class="pagination" v-if="pages > 1">
                <button class="btn btn-secondary btn-sm" :disabled="page <= 1" @click="loadLogs(page - 1)">← Prev</button>
                <span class="page-info">Pagina {{ page }} di {{ pages }}</span>
                <button class="btn btn-secondary btn-sm" :disabled="page >= pages" @click="loadLogs(page + 1)">Next →</button>
            </div>
        </div>
    </div>

    <!-- SYSTEM LOGS TAB -->
    <div v-else class="tab-content">
        <div class="controls-bar">
            <button class="btn btn-secondary btn-sm" @click="loadSystemLogs" :disabled="sysLoading">
                <span v-if="sysLoading" class="spinner-sm"></span>
                <span v-else>🔄 Aggiorna</span>
            </button>
            
            <select v-model="selectedFile" @change="loadSystemLogs" class="form-input" style="width: auto; min-width: 200px;">
                <option v-for="f in logFiles" :key="f.name" :value="f.name">
                    {{ f.name }} ({{ f.size_human }})
                </option>
            </select>

            <select v-model="sysLines" @change="loadSystemLogs" class="form-input" style="width: auto;">
                <option :value="100">100 righe</option>
                <option :value="500">500 righe</option>
                <option :value="1000">1000 righe</option>
                <option :value="2000">2000 righe</option>
            </select>

            <input 
                type="text" 
                v-model="sysSearch" 
                @keyup.enter="loadSystemLogs"
                placeholder="Cerca..." 
                class="form-input" 
                style="width: 200px;"
            >
        </div>

        <div class="card system-logs-card">
            <div class="log-viewer">
                <div v-if="sysLoading" class="loading-overlay">
                    <div class="spinner"></div>
                </div>
                <div v-if="systemLogs.length === 0 && !sysLoading" class="empty-logs">
                    Nessun log trovato nel file {{ selectedFile }}
                </div>
                <div v-for="(line, idx) in systemLogs" :key="idx" class="log-line">
                    <span class="log-ts">{{ extractTime(line.timestamp) }}</span>
                    <span class="log-level" :class="'level-' + (line.level || 'INFO').toLowerCase()">
                        {{ line.level || 'INFO' }}
                    </span>
                    <span class="log-module" v-if="line.module">{{ line.module }}</span>
                    <span class="log-msg">{{ line.message }}</span>
                </div>
            </div>
        </div>
        <div class="text-xs text-secondary mt-2">
            Visualizzazione ultimi {{ systemLogs.length }} eventi da {{ selectedFile }}.
        </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import logsService, { type LogEntry } from '../services/logs';

const activeTab = ref('jobs');

// JOBS DATA
const logs = ref<LogEntry[]>([]);
const loading = ref(false);
const page = ref(1);
const pages = ref(1);
const filterLevel = ref('');

// SYSTEM DATA
const systemLogs = ref<any[]>([]);
const logFiles = ref<any[]>([]);
const selectedFile = ref('dapx.log');
const sysLoading = ref(false);
const sysLines = ref(200);
const sysSearch = ref('');

onMounted(() => {
    loadLogs();
    // Preload system log files silently
    loadSystemFiles();
});

// === JOB LOGS LOGIC ===
const loadLogs = async (p = 1) => {
    loading.value = true;
    try {
        const res = await logsService.getLogs({ 
            limit: 100, 
            offset: (p - 1) * 100,
            status: filterLevel.value ? filterLevel.value : undefined
        });
        
        if (Array.isArray(res.data)) {
            logs.value = res.data;
            pages.value = res.data.length === 100 ? p + 1 : p;
            page.value = p;
        } else if ((res.data as any).items) {
             logs.value = (res.data as any).items;
             page.value = (res.data as any).page;
             pages.value = (res.data as any).pages;
        }
    } catch (e) {
        console.error('Error loading logs', e);
    } finally {
        loading.value = false;
    }
};

const clearLogs = async () => {
    if (!confirm('Eliminare tutti i log?')) return;
    try {
        await logsService.clearLogs();
        loadLogs();
    } catch (e) {
        alert('Errore pulizia log');
    }
};

const formatDate = (dateStr: string) => new Date(dateStr).toLocaleString();

const getStatusClass = (status: string) => {
    switch (status?.toLowerCase()) {
        case 'failed': return 'badge-danger';
        case 'error': return 'badge-danger';
        case 'warning': return 'badge-warning';
        case 'success': return 'badge-success';
        case 'running': return 'badge-info';
        default: return 'badge-secondary';
    }
};

// === SYSTEM LOGS LOGIC ===
const loadSystemFiles = async () => {
    try {
        const res = await logsService.getSystemLogFiles();
        if (res.data && res.data.files) {
            logFiles.value = res.data.files;
            // Select dapx.log by default if present
            if (logFiles.value.find((f: any) => f.name === 'dapx.log')) {
                selectedFile.value = 'dapx.log';
            }
        }
    } catch (e) {
        console.error("Error loading system files", e);
    }
};

const loadSystemLogs = async () => {
    sysLoading.value = true;
    try {
        const res = await logsService.getSystemLogs({
            file: selectedFile.value,
            lines: sysLines.value,
            search: sysSearch.value
        });
        
        if (res.data && res.data.logs) {
            systemLogs.value = res.data.logs;
        }
    } catch (e) {
        console.error("Error loading system logs", e);
    } finally {
        sysLoading.value = false;
    }
};

const extractTime = (ts: string) => {
    if (!ts) return '';
    return ts.split(' ')[1] || ts;
};
</script>

<style scoped>
.page-header { margin-bottom: 20px; }
.tabs-header { display: flex; gap: 10px; margin-top: 20px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 5px; }
.tab-btn {
    background: transparent;
    border: none;
    color: var(--text-secondary);
    padding: 10px 20px;
    cursor: pointer;
    font-size: 1rem;
    font-weight: 500;
    border-bottom: 2px solid transparent;
    transition: all 0.2s;
}
.tab-btn:hover { color: var(--text-primary); }
.tab-btn.active { color: var(--primary-color); border-bottom-color: var(--primary-color); }

.controls-bar { display: flex; gap: 12px; margin-bottom: 15px; flex-wrap: wrap; align-items: center; }
.system-logs-card { padding: 0; background: #1e1e1e; border: 1px solid #333; overflow: hidden; }
.log-viewer {
    height: 600px;
    overflow-y: auto;
    font-family: 'Fira Code', monospace;
    font-size: 0.85rem;
    padding: 10px;
    background: #0d0d0d;
    color: #d4d4d4;
}

.log-line { display: flex; gap: 10px; padding: 2px 0; border-bottom: 1px solid #1a1a1a; }
.log-line:hover { background: #1a1a1a; }
.log-ts { color: #569cd6; min-width: 80px; }
.log-level { font-weight: bold; min-width: 60px; }
.level-info { color: #4ec9b0; }
.level-warning { color: #cca700; }
.level-error { color: #f44747; }
.level-debug { color: #808080; }
.log-module { color: #ce9178; min-width: 120px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.log-msg { color: #d4d4d4; white-space: pre-wrap; word-break: break-all; }

/* Utils */
.text-xs { font-size: 0.75em; }
.mt-1 { margin-top: 4px; }
.text-sm { font-size: 0.85em; }
.mt-2 { margin-top: 8px; }
.font-mono { font-family: monospace; }
.font-bold { font-weight: 600; }
.whitespace-nowrap { white-space: nowrap; }
.bg-dark { background: rgba(0,0,0,0.2); }
.p-1 { padding: 4px; }
.rounded { border-radius: 4px; }

/* Badges */
.badge-info { background: rgba(0, 212, 255, 0.15); color: #00d4ff; }
.badge-danger { background: rgba(255, 82, 82, 0.15); color: #ff5252; }
.badge-warning { background: rgba(255, 179, 0, 0.15); color: #ffb300; }
.badge-secondary { background: rgba(255, 255, 255, 0.1); color: var(--text-secondary); }

.empty-state-cell { text-align: center; padding: 40px; color: var(--text-secondary); }
.empty-logs { text-align: center; padding: 40px; color: #666; }
.spinner-sm {
    display: inline-block;
    width: 12px; height: 12px;
    border: 2px solid currentColor;
    border-top-color: transparent;
    border-radius: 50%;
    animation: spin 1s linear infinite;
}
.pagination { display: flex; justify-content: center; align-items: center; gap: 16px; margin-top: 20px; padding: 10px; }
.page-info { color: var(--text-secondary); font-size: 0.9em; }

@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
</style>
