<template>
  <div class="dashboard-page">
    <div class="page-header">
        <h1 class="page-title">📊 Dashboard Principale</h1>
        <p class="page-subtitle">Riepilogo job di replica, backup, metriche nodi e log</p>
        <div style="display: flex; align-items: center; gap: 12px; margin-top: 12px;">
            <button class="btn btn-secondary btn-sm" @click="refreshData()" :disabled="loading">
                <span v-if="loading" class="spinner-sm"></span>
                <span v-else>🔄 Aggiorna Dati</span>
            </button>
        </div>
    </div>

    <!-- Summary Stats - Job per Tipo -->
    <div v-if="jobStats" class="stats-grid">
        <div class="stat-card">
            <div class="stat-label">Replica ZFS</div>
            <div class="stat-value">{{ jobStats.replica_zfs || 0 }}</div>
            <div class="stat-detail">Job attivi</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Replica BTRFS</div>
            <div class="stat-value">{{ jobStats.replica_btrfs || 0 }}</div>
            <div class="stat-detail">Job attivi</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Backup PBS</div>
            <div class="stat-value">{{ jobStats.backup_pbs || 0 }}</div>
            <div class="stat-detail">Job attivi</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Replica PBS</div>
            <div class="stat-value">{{ jobStats.replica_pbs || 0 }}</div>
            <div class="stat-detail">Job attivi</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Migrazione</div>
            <div class="stat-value">{{ jobStats.migration || 0 }}</div>
            <div class="stat-detail">Job attivi</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Totale Job</div>
            <div class="stat-value">{{ jobStats.total || 0 }}</div>
            <div class="stat-detail">
                <router-link :to="{ name: 'dashboard' }" style="color: var(--accent-primary);">Vai a Proxmox →</router-link>
            </div>
        </div>
    </div>

    <!-- Metriche Nodi -->
    <div class="card" style="margin-top: 24px;">
        <div class="card-header">
            <h3 class="card-title">📊 Metriche Performance Nodi</h3>
            <button class="btn btn-sm btn-secondary" @click="loadNodesMetrics" :disabled="loadingMetrics">🔄 Aggiorna</button>
        </div>
        <div class="card-body">
            <div v-if="nodesMetrics.length === 0 && !loadingMetrics" style="color: var(--text-secondary); text-align: center; padding: 20px;">
                Nessun nodo online o metriche non disponibili
            </div>
            <div v-else-if="loadingMetrics && nodesMetrics.length === 0" style="text-align: center; padding: 20px; color: var(--text-secondary);">
                ⏳ Caricamento metriche...
            </div>
            <div v-else class="table-container">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Nodo</th>
                            <th>CPU Usage</th>
                            <th>RAM Usage</th>
                            <th>Load Average</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="metrics in nodesMetrics" :key="metrics.node_id">
                            <td><strong>{{ metrics.node_name }}</strong></td>
                            <td>
                                <div style="display: flex; align-items: center; gap: 8px;">
                                    <div class="progress-bar-bg">
                                        <div class="progress-bar-fill" :style="getProgressStyle(metrics.cpu?.usage_percent || 0)"></div>
                                    </div>
                                    <span style="min-width: 50px; text-align: right;">{{ (metrics.cpu?.usage_percent || 0).toFixed(1) }}%</span>
                                </div>
                            </td>
                            <td>
                                <div style="display: flex; align-items: center; gap: 8px;">
                                    <div class="progress-bar-bg">
                                        <div class="progress-bar-fill" :style="getProgressStyle(metrics.memory?.usage_percent || 0, 90, 75)"></div>
                                    </div>
                                    <span style="min-width: 50px; text-align: right;">{{ (metrics.memory?.usage_percent || 0).toFixed(1) }}%</span>
                                </div>
                                <div style="font-size: 0.85em; color: var(--text-secondary); margin-top: 4px;">
                                    {{ (metrics.memory?.used_gb || 0).toFixed(1) }} / {{ (metrics.memory?.total_gb || 0).toFixed(1) }} GB
                                </div>
                            </td>
                            <td>
                                <span style="font-family: monospace; font-size: 0.9em;">
                                    {{ (metrics.cpu?.load_1min || 0).toFixed(2) }} / {{ (metrics.cpu?.load_5min || 0).toFixed(2) }} / {{ (metrics.cpu?.load_15min || 0).toFixed(2) }}
                                </span>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import dashboardService, { type JobStats, type NodeMetrics } from '../services/dashboard';

const loading = ref(false);
const loadingMetrics = ref(false);
const jobStats = ref<JobStats | null>(null);
const nodesMetrics = ref<NodeMetrics[]>([]);

onMounted(() => {
    refreshData();
});

const refreshData = async () => {
    loading.value = true;
    try {
        await Promise.all([
            loadJobStats(),
            loadNodesMetrics()
        ]);
    } finally {
        loading.value = false;
    }
};

const loadJobStats = async () => {
    try {
        const res = await dashboardService.getJobStats();
        jobStats.value = res.data;
    } catch (e) {
        console.error('Error loading job stats', e);
    }
};

const loadNodesMetrics = async () => {
    loadingMetrics.value = true;
    try {
        const res = await dashboardService.getNodesMetrics();
        nodesMetrics.value = res.data;
    } catch (e) {
        console.error('Error loading metrics', e);
    } finally {
        loadingMetrics.value = false;
    }
};

const getProgressStyle = (val: number, danger = 80, warning = 60) => {
    let color = 'var(--accent-primary)';
    if (val > danger) color = 'var(--accent-danger)';
    else if (val > warning) color = 'var(--accent-warning)';
    
    return {
        width: `${val}%`,
        background: color,
        height: '100%',
        transition: 'width 0.3s'
    };
};
</script>

<style scoped>
.progress-bar-bg {
    flex: 1; 
    background: var(--bg-secondary); 
    border-radius: 4px; 
    height: 20px; 
    position: relative; 
    overflow: hidden;
}

.spinner-sm {
    display: inline-block;
    width: 12px; height: 12px;
    border: 2px solid currentColor;
    border-top-color: transparent;
    border-radius: 50%;
    animation: spin 1s linear infinite;
}

@keyframes spin { 100% { transform: rotate(360deg); } }

/* Stats Grid */
.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
}

.stat-card {
    background: var(--bg-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: 20px;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    box-shadow: var(--shadow-sm);
}

.stat-label {
    font-size: 0.9em;
    color: var(--text-secondary);
    margin-bottom: 8px;
    font-weight: 500;
}

.stat-value {
    font-size: 2em;
    font-weight: 700;
    color: var(--text-primary);
    line-height: 1.2;
}

.stat-detail {
    font-size: 0.85em;
    color: var(--text-tertiary);
    margin-top: 4px;
}
</style>
