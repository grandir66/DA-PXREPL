<template>
  <div class="logs-page">
    <div class="page-header">
        <h1 class="page-title">📜 System Logs</h1>
        <p class="page-subtitle">Registro eventi di sistema e operazioni</p>
        <div style="display: flex; align-items: center; gap: 12px; margin-top: 12px;">
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
                         <td colspan="4" class="empty-state-cell">Nessun log trovato</td>
                    </tr>
                </tbody>
            </table>
        </div>
        
        <!-- Pagination -->
        <div class="pagination" v-if="pages > 1">
            <button class="btn btn-secondary btn-sm" :disabled="page <= 1" @click="loadLogs(page - 1)">← Prev</button>
            <span class="page-info">Pagina {{ page }} di {{ pages }}</span>
            <button class="btn btn-secondary btn-sm" :disabled="page >= pages" @click="loadLogs(page + 1)">Next →</button>
        </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import logsService, { type LogEntry } from '../services/logs';

const logs = ref<LogEntry[]>([]);
const loading = ref(false);
const page = ref(1);
const pages = ref(1);
const filterLevel = ref('');

onMounted(() => {
    loadLogs();
});

const loadLogs = async (p = 1) => {
    loading.value = true;
    try {
        const res = await logsService.getLogs({ 
            limit: 100, 
            offset: (p - 1) * 100,
            status: filterLevel.value ? undefined : undefined // mapping to be precise if needed
        });
        
        // Backend returns simple list [ ... ]
        if (Array.isArray(res.data)) {
            logs.value = res.data;
            // Fake pagination logic since backend is offset-based list
            // If we got full limit, assume there is a next page
            pages.value = res.data.length === 100 ? p + 1 : p;
            page.value = p;
        } else if ((res.data as any).items) { // Fallback if API changes
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

const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString();
};

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
</script>

<style scoped>
.text-xs { font-size: 0.75em; }
.mt-1 { margin-top: 4px; }
.text-sm { font-size: 0.85em; }
.font-mono { font-family: monospace; }
.font-bold { font-weight: 600; }
.whitespace-nowrap { white-space: nowrap; }
.bg-dark { background: rgba(0,0,0,0.2); }
.p-1 { padding: 4px; }
.rounded { border-radius: 4px; }

.badge-info { background: rgba(0, 212, 255, 0.15); color: #00d4ff; }
.badge-danger { background: rgba(255, 82, 82, 0.15); color: #ff5252; }
.badge-warning { background: rgba(255, 179, 0, 0.15); color: #ffb300; }
.badge-secondary { background: rgba(255, 255, 255, 0.1); color: var(--text-secondary); }

.empty-state-cell { text-align: center; padding: 40px; color: var(--text-secondary); }
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
</style>
