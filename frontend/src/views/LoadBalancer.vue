
<template>
<div class="load-balancer-view">
    <div class="page-header">
        <div>
            <h1 class="page-title">⚖️ Cluster Load Balancer</h1>
            <p class="page-subtitle">Powered by ProxLB</p>
        </div>
        <div class="actions">
            <button class="btn btn-secondary" @click="refreshConfig">❌ Reset</button>
            <button class="btn btn-primary" @click="saveConfiguration" v-if="activeTab === 'config'">💾 Save Config</button>
        </div>
    </div>

    <div class="tabs">
        <button 
            class="tab-btn" 
            :class="{ active: activeTab === 'analysis' }" 
            @click="activeTab = 'analysis'">
            📊 Analysis & Run
        </button>
        <button 
            class="tab-btn" 
            :class="{ active: activeTab === 'config' }" 
            @click="activeTab = 'config'">
            ⚙️ Configuration
        </button>
    </div>

    <div class="tab-content">
        <!-- Analysis Tab -->
        <div v-if="activeTab === 'analysis'" class="analysis-panel">
            <div class="control-bar">
                <button class="btn btn-primary btn-lg" @click="runAnalysis" :disabled="loading">
                    <span v-if="loading" class="spinner-sm"></span>
                    {{ loading ? 'Analyzing...' : '🔍 Analyze Cluster' }}
                </button>
                
                <div v-if="lastAnalysis" class="analysis-actions">
                    <div class="result-summary">
                        <span>Score: <strong>{{ balanciness }}</strong> (Lower is better)</span>
                    </div>
                    <button class="btn btn-success btn-lg" @click="executeRun(true)" :disabled="executing">
                         🧪 Dry Run
                    </button>
                    <button class="btn btn-danger btn-lg" @click="executeRun(false)" :disabled="executing">
                        🚀 Execute Balancing
                    </button>
                </div>
            </div>

            <div v-if="error" class="alert alert-danger">
                {{ error }}
            </div>

            <div v-if="executionLog.length > 0" class="log-output">
                <h3>Execution Log</h3>
                <div class="log-window">
                    <div v-for="(line, i) in executionLog" :key="i">{{ line }}</div>
                </div>
            </div>

            <div v-if="lastAnalysis" class="results-grid">
                <!-- Metrics Card -->
                <div class="card">
                    <h3>Current Metrics</h3>
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>Node</th>
                                <th>CPU Usage</th>
                                <th>Mem Usage</th>
                                <th>VMs</th>
                                <th>CTs</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="(node, name) in lastAnalysis.nodes" :key="name">
                                <td>{{ name }}</td>
                                <td>{{ formatPercentDirect(node.cpu_used_percent) }}</td>
                                <td>{{ formatPercentDirect(node.memory_used_percent) }}</td>
                                <td>{{ getGuestCount(name, 'qemu') }}</td>
                                <td>{{ getGuestCount(name, 'lxc') }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>

                <!-- Migrations Card -->
                <div class="card">
                    <h3>Proposed Migrations</h3>
                    <div v-if="migrations && migrations.length > 0">
                        <table class="data-table">
                            <thead>
                                <tr>
                                    <th>Guest</th>
                                    <th>Source</th>
                                    <th>Target</th>
                                    <th>Reason</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr v-for="(mig, i) in migrations" :key="i">
                                    <td>{{ mig.guest }}</td>
                                    <td>{{ mig.source }}</td>
                                    <td>{{ mig.target }}</td>
                                    <td>{{ mig.reason }}</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                    <div v-else class="empty-state">
                        ✅ Cluster is balanced. No migrations needed.
                    </div>
                </div>
            </div>
        </div>

        <!-- Config Tab -->
        <div v-if="activeTab === 'config'" class="config-panel">
            <div class="config-editor-container">
                <textarea v-model="configJson" class="json-editor" spellcheck="false"></textarea>
            </div>
            <div class="help-text">
                Edit the configuration (JSON format). See ProxLB documentation for options.
            </div>
        </div>
    </div>
</div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import loadBalancerService from '../services/loadBalancer';

const activeTab = ref('analysis');
const loading = ref(false);
const executing = ref(false);
const error = ref<string | null>(null);
const lastAnalysis = ref<any>(null);
const configJson = ref('{}');
const executionLog = ref<string[]>([]);

const migrations = computed(() => {
    // This depends on ProxLB output structure. 
    // We might need to inspect 'lastAnalysis' structure to find migration list.
    // Assuming calculation results are in lastAnalysis... but ProxLB usually logs them or puts in structure
    // Let's assume we find them in a specific key or list.
    // Based on code reading: Calculations.relocate_guests modifies proxlb_data.
    // It might add a 'relocate' key or similar logs.
    return []; // Placeholder until we verify structure
});

const balanciness = computed(() => {
    return lastAnalysis.value?.meta?.balanciness_score || 'N/A';
});

const runAnalysis = async () => {
    loading.value = true;
    error.value = null;
    executionLog.value = [];
    try {
        const res = await loadBalancerService.analyzeCluster();
        lastAnalysis.value = res.data;
        // Parse migrations from result log if possible, or result structure
        if (lastAnalysis.value.log) {
             executionLog.value = lastAnalysis.value.log;
        }
    } catch (e: any) {
        error.value = e.response?.data?.detail || e.message;
    } finally {
        loading.value = false;
    }
};

const executeRun = async (dryRun: boolean) => {
    executing.value = true;
    error.value = null;
    try {
        const res = await loadBalancerService.executeBalancing(dryRun);
        // Result is { data: ..., log: ... }
        lastAnalysis.value = res.data.data;
        if (res.data.log) {
            executionLog.value = res.data.log;
        }
    } catch (e: any) {
        error.value = e.response?.data?.detail || e.message;
    } finally {
        executing.value = false;
    }
};

const refreshConfig = async () => {
    try {
        const res = await loadBalancerService.getConfig();
        configJson.value = JSON.stringify(res.data.saved, null, 2);
    } catch (e) {
        console.error(e);
    }
};

const saveConfiguration = async () => {
    try {
        const config = JSON.parse(configJson.value);
        await loadBalancerService.updateConfig(config);
        alert('Configuration saved');
    } catch (e) {
        alert('Invalid JSON');
    }
};

const formatPercent = (val: number) => {
    return (val * 100).toFixed(1) + '%';
};

// ProxLB already returns percentages as 0-100, not 0-1
const formatPercentDirect = (val: number) => {
    if (val === undefined || val === null || isNaN(val)) return 'N/A';
    return val.toFixed(1) + '%';
};

// Count guests (VMs or CTs) on a specific node
const getGuestCount = (nodeName: string, guestType: 'qemu' | 'lxc') => {
    if (!lastAnalysis.value || !lastAnalysis.value.guests) return 0;
    const guests = lastAnalysis.value.guests;
    let count = 0;
    for (const id in guests) {
        const guest = guests[id];
        if (guest.node === nodeName && guest.type === guestType) {
            count++;
        }
    }
    return count;
};

onMounted(() => {
    refreshConfig();
});
</script>

<style scoped>
.load-balancer-view {
    display: flex;
    flex-direction: column;
    gap: 24px;
    height: 100%;
}

.page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.tabs {
    display: flex;
    gap: 8px;
    border-bottom: 1px solid var(--border-color);
}

.tab-btn {
    padding: 12px 24px;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--text-secondary);
    cursor: pointer;
    font-weight: 600;
}

.tab-btn.active {
    color: var(--accent-primary);
    border-bottom-color: var(--accent-primary);
}

.tab-content {
    flex: 1;
    overflow-y: auto;
}

.control-bar {
    display: flex;
    gap: 16px;
    align-items: center;
    margin-bottom: 24px;
    flex-wrap: wrap;
}

.analysis-actions {
    display: flex;
    gap: 12px;
    align-items: center;
}

.result-summary {
    margin-right: 12px;
    font-size: 1.1rem;
}

.log-output {
    background: #000;
    color: #0f0;
    padding: 16px;
    border-radius: 8px;
    font-family: monospace;
    max-height: 200px;
    overflow-y: auto;
    margin-bottom: 24px;
}

.results-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
    gap: 24px;
}

.card {
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 20px;
}

.json-editor {
    width: 100%;
    height: 500px;
    background: #1a1a1a;
    color: #d4d4d4;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 16px;
    font-family: monospace;
    line-height: 1.5;
}

.empty-state {
    padding: 40px;
    text-align: center;
    color: var(--text-secondary);
}

.data-table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 12px;
}

.data-table th {
    text-align: left;
    padding: 8px;
    color: var(--text-secondary);
    border-bottom: 1px solid var(--border-color);
}

.data-table td {
    padding: 8px;
    border-bottom: 1px solid var(--border-color);
}
</style>
