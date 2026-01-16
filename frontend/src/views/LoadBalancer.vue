
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
            :class="{ active: activeTab === 'health' }" 
            @click="activeTab = 'health'">
            💓 Node Health
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

        <!-- Node Health Tab -->
        <div v-if="activeTab === 'health'" class="health-panel">
            <div class="control-bar">
                <button class="btn btn-primary" @click="runAnalysis" :disabled="loading">
                    <span v-if="loading" class="spinner-sm"></span>
                    {{ loading ? 'Refreshing...' : '🔄 Refresh Data' }}
                </button>
                <span v-if="lastAnalysis" class="last-update">
                    Last update: {{ new Date().toLocaleTimeString() }}
                </span>
            </div>

            <div v-if="!lastAnalysis" class="empty-state">
                <p>📊 Click "Refresh Data" to load node metrics</p>
            </div>

            <div v-else class="nodes-health-grid">
                <div 
                    v-for="(node, nodeName) in lastAnalysis.nodes" 
                    :key="nodeName" 
                    class="node-health-card"
                    :class="getNodeHealthClass(node)"
                >
                    <div class="node-header">
                        <h3 class="node-name">🖥️ {{ nodeName }}</h3>
                        <span class="node-status" :class="getNodeStatusClass(node)">
                            {{ getNodeStatus(node) }}
                        </span>
                    </div>

                    <div class="metrics-grid">
                        <!-- CPU -->
                        <div class="metric-item">
                            <div class="metric-label">
                                <span>⚡ CPU</span>
                                <span class="metric-value">{{ formatPercentDirect(node.cpu_used_percent) }}</span>
                            </div>
                            <div class="progress-bar">
                                <div 
                                    class="progress-fill" 
                                    :class="getProgressClass(node.cpu_used_percent)"
                                    :style="{ width: (node.cpu_used_percent || 0) + '%' }"
                                ></div>
                            </div>
                        </div>

                        <!-- Memory -->
                        <div class="metric-item">
                            <div class="metric-label">
                                <span>🧠 Memory</span>
                                <span class="metric-value">{{ formatPercentDirect(node.memory_used_percent) }}</span>
                            </div>
                            <div class="progress-bar">
                                <div 
                                    class="progress-fill" 
                                    :class="getProgressClass(node.memory_used_percent)"
                                    :style="{ width: (node.memory_used_percent || 0) + '%' }"
                                ></div>
                            </div>
                            <div class="metric-detail">
                                {{ formatBytes(node.memory_used) }} / {{ formatBytes(node.memory_total) }}
                            </div>
                        </div>

                        <!-- Disk (if available) -->
                        <div class="metric-item" v-if="node.disk_used_percent">
                            <div class="metric-label">
                                <span>💾 Disk</span>
                                <span class="metric-value">{{ formatPercentDirect(node.disk_used_percent) }}</span>
                            </div>
                            <div class="progress-bar">
                                <div 
                                    class="progress-fill" 
                                    :class="getProgressClass(node.disk_used_percent)"
                                    :style="{ width: (node.disk_used_percent || 0) + '%' }"
                                ></div>
                            </div>
                        </div>
                    </div>

                    <div class="node-footer">
                        <div class="guest-counts">
                            <span class="guest-badge vm">{{ getGuestCount(nodeName, 'qemu') }} VMs</span>
                            <span class="guest-badge ct">{{ getGuestCount(nodeName, 'lxc') }} CTs</span>
                        </div>
                        <div class="node-pve-version" v-if="node.pve_version">
                            PVE {{ node.pve_version }}
                        </div>
                    </div>
                </div>
            </div>

            <!-- Cluster Summary -->
            <div v-if="lastAnalysis" class="cluster-summary">
                <h3>📈 Cluster Summary</h3>
                <div class="summary-grid">
                    <div class="summary-item">
                        <span class="summary-label">Total Nodes</span>
                        <span class="summary-value">{{ Object.keys(lastAnalysis.nodes || {}).length }}</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">Total VMs</span>
                        <span class="summary-value">{{ totalVMs }}</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">Total CTs</span>
                        <span class="summary-value">{{ totalCTs }}</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">Balance Score</span>
                        <span class="summary-value" :class="getScoreClass(balanciness)">{{ balanciness }}%</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Config Tab -->
        <div v-if="activeTab === 'config'" class="config-panel">
            <!-- Connection Section -->
            <div class="config-section">
                <h3 class="section-title">🔌 Connessione Cluster</h3>
                <div class="form-grid">
                    <div class="form-group">
                        <label>Host Proxmox</label>
                        <input type="text" v-model="config.proxmox_api.hosts" class="form-input" placeholder="es: 192.168.1.10, 192.168.1.11">
                        <span class="help-text">Separati da virgola. Lascia vuoto per usare i nodi registrati.</span>
                    </div>
                    <div class="form-group">
                        <label>Utente API</label>
                        <input type="text" v-model="config.proxmox_api.user" class="form-input" placeholder="root@pam">
                    </div>
                    <div class="form-group">
                        <label>Password</label>
                        <input type="password" v-model="config.proxmox_api.pass" class="form-input" placeholder="(usa credenziali DB se vuoto)">
                    </div>
                    <div class="form-group checkbox">
                        <label><input type="checkbox" v-model="config.proxmox_api.ssl_verification"> Verifica SSL</label>
                    </div>
                </div>
            </div>

            <!-- Balancing Parameters -->
            <div class="config-section">
                <h3 class="section-title">⚖️ Parametri Bilanciamento</h3>
                <div class="form-grid">
                    <div class="form-group checkbox">
                        <label><input type="checkbox" v-model="config.balancing.enable"> Abilita Bilanciamento Automatico</label>
                    </div>
                    <div class="form-group">
                        <label>Metrica principale</label>
                        <select v-model="config.balancing.method" class="form-input">
                            <option value="memory">Memoria</option>
                            <option value="cpu">CPU</option>
                            <option value="disk">Disco</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Modalità</label>
                        <select v-model="config.balancing.mode" class="form-input">
                            <option value="used">Risorse Usate</option>
                            <option value="assigned">Risorse Assegnate</option>
                            <option value="psi">PSI (Pressure)</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Soglia Sbilanciamento (%)</label>
                        <input type="range" v-model.number="config.balancing.balanciness" min="1" max="50" class="slider">
                        <span class="slider-value">{{ config.balancing.balanciness }}%</span>
                        <span class="help-text">Differenza massima tra nodi prima di triggerare il bilanciamento</span>
                    </div>
                    <div class="form-group">
                        <label>Soglia Memoria Critica (%)</label>
                        <input type="range" v-model.number="config.balancing.memory_threshold" min="50" max="95" class="slider">
                        <span class="slider-value">{{ config.balancing.memory_threshold }}%</span>
                    </div>
                    <div class="form-group checkbox-group">
                        <label>Tipi Guest:</label>
                        <label><input type="checkbox" :checked="config.balancing.balance_types?.includes('vm')" @change="toggleBalanceType('vm')"> VMs</label>
                        <label><input type="checkbox" :checked="config.balancing.balance_types?.includes('ct')" @change="toggleBalanceType('ct')"> Containers</label>
                    </div>
                    <div class="form-group checkbox">
                        <label><input type="checkbox" v-model="config.balancing.balance_larger_guests_first"> Migra prima guest più grandi</label>
                    </div>
                </div>
            </div>

            <!-- Migration Options -->
            <div class="config-section">
                <h3 class="section-title">🔄 Opzioni Migrazione</h3>
                <div class="form-grid">
                    <div class="form-group checkbox">
                        <label><input type="checkbox" v-model="config.balancing.live"> Migrazione Live (senza downtime)</label>
                    </div>
                    <div class="form-group checkbox">
                        <label><input type="checkbox" v-model="config.balancing.with_local_disks"> Migra guest con dischi locali</label>
                        <span class="help-text">Richiede storage condiviso</span>
                    </div>
                    <div class="form-group checkbox">
                        <label><input type="checkbox" v-model="config.balancing.with_conntrack_state"> Conserva stato connessioni (conntrack)</label>
                    </div>
                    <div class="form-group checkbox">
                        <label><input type="checkbox" v-model="config.balancing.parallel"> Migrazioni parallele</label>
                    </div>
                    <div class="form-group" v-if="config.balancing.parallel">
                        <label>Numero Job Paralleli</label>
                        <input type="number" v-model.number="config.balancing.parallel_jobs" class="form-input" min="1" max="10">
                    </div>
                    <div class="form-group">
                        <label>Timeout Validazione (sec)</label>
                        <input type="number" v-model.number="config.balancing.max_job_validation" class="form-input" min="60" max="7200">
                    </div>
                </div>
            </div>

            <!-- Affinity / Pinning -->
            <div class="config-section">
                <h3 class="section-title">🔗 Regole Affinità e Pinning</h3>
                <div class="form-grid">
                    <div class="form-group checkbox">
                        <label><input type="checkbox" v-model="config.balancing.enforce_affinity"> Forza regole di affinità</label>
                    </div>
                    <div class="form-group checkbox">
                        <label><input type="checkbox" v-model="config.balancing.enforce_pinning"> Forza pinning a nodi specifici</label>
                    </div>
                </div>
                <div class="info-box">
                    <strong>ℹ️ Tag supportati sui Guest (in Proxmox):</strong>
                    <ul>
                        <li><code>plb_affinity_&lt;nome&gt;</code> — Raggruppa guest sullo stesso nodo</li>
                        <li><code>plb_anti_affinity_&lt;nome&gt;</code> — Separa guest su nodi diversi</li>
                        <li><code>plb_pin_&lt;nodo&gt;</code> — Fissa guest su un nodo specifico</li>
                        <li><code>plb_ignore</code> — Ignora guest dal bilanciamento</li>
                    </ul>
                </div>
            </div>

            <!-- Node Management -->
            <div class="config-section">
                <h3 class="section-title">🖥️ Gestione Nodi</h3>
                
                <div class="subsection">
                    <h4>Nodi in Manutenzione</h4>
                    <p class="help-text">I guest verranno evacuati da questi nodi</p>
                    <div class="multi-select-grid" v-if="availableNodes.length > 0">
                        <label v-for="node in availableNodes" :key="'maint-'+node" class="checkbox-item">
                            <input type="checkbox" 
                                :checked="config.proxmox_cluster.maintenance_nodes.includes(node)"
                                @change="toggleNode('maintenance', node)">
                            <span class="node-name">{{ node }}</span>
                        </label>
                    </div>
                    <div v-else class="empty-hint">Esegui "Analyze Cluster" per caricare la lista nodi</div>
                </div>
                
                <div class="subsection">
                    <h4>Nodi da Ignorare</h4>
                    <p class="help-text">Questi nodi non parteciperanno al bilanciamento</p>
                    <div class="multi-select-grid" v-if="availableNodes.length > 0">
                        <label v-for="node in availableNodes" :key="'ignore-'+node" class="checkbox-item">
                            <input type="checkbox" 
                                :checked="config.proxmox_cluster.ignore_nodes.includes(node)"
                                @change="toggleNode('ignore', node)">
                            <span class="node-name">{{ node }}</span>
                        </label>
                    </div>
                    <div v-else class="empty-hint">Esegui "Analyze Cluster" per caricare la lista nodi</div>
                </div>
                
                <div class="form-group" style="margin-top: 16px;">
                    <label>Riserva Memoria Default (GB)</label>
                    <input type="number" v-model.number="defaultMemoryReserve" class="form-input" min="0" max="64" style="max-width: 120px;">
                </div>
            </div>

            <!-- Guest Management -->
            <div class="config-section">
                <h3 class="section-title">🖥️ Gestione Guest (VM/CT)</h3>
                
                <div class="guest-management-grid">
                    <!-- Migratable Guests -->
                    <div class="guest-list-panel">
                        <h4>✅ Guest Migrabili</h4>
                        <p class="help-text">Questi guest possono essere spostati tra i nodi</p>
                        <div class="guest-list" v-if="migratableGuests.length > 0">
                            <div v-for="guest in migratableGuests" :key="'mig-'+guest.id" class="guest-item">
                                <span class="guest-type" :class="guest.type">{{ guest.type.toUpperCase() }}</span>
                                <span class="guest-name">{{ guest.name || guest.id }}</span>
                                <span class="guest-node">@ {{ guest.node_current }}</span>
                                <button class="btn-sm btn-danger" @click="addToIgnoreList(guest)" title="Blocca migrazione">
                                    🚫
                                </button>
                            </div>
                        </div>
                        <div v-else class="empty-hint">Nessun guest migrabile trovato</div>
                    </div>
                    
                    <!-- Non-Migratable Guests -->
                    <div class="guest-list-panel">
                        <h4>🔒 Guest NON Migrabili</h4>
                        <p class="help-text">Questi guest sono esclusi dal bilanciamento</p>
                        <div class="guest-list" v-if="ignoredGuests.length > 0">
                            <div v-for="guest in ignoredGuests" :key="'ign-'+guest.id" class="guest-item ignored">
                                <span class="guest-type" :class="guest.type">{{ guest.type.toUpperCase() }}</span>
                                <span class="guest-name">{{ guest.name || guest.id }}</span>
                                <span class="guest-node">@ {{ guest.node_current }}</span>
                                <button class="btn-sm btn-success" @click="removeFromIgnoreList(guest)" title="Consenti migrazione">
                                    ✅
                                </button>
                            </div>
                        </div>
                        <div v-else class="empty-hint">Nessun guest escluso</div>
                    </div>
                </div>
                
                <div class="info-box" style="margin-top: 16px;">
                    <strong>💡 Suggerimento:</strong> I guest con tag <code>plb_ignore</code> in Proxmox verranno automaticamente esclusi.
                    Qui puoi aggiungere esclusioni aggiuntive senza modificare i tag su Proxmox.
                </div>
            </div>

            <!-- Scheduling -->
            <div class="config-section">
                <h3 class="section-title">⏰ Schedulazione Automatica</h3>
                <div class="form-grid">
                    <div class="form-group checkbox">
                        <label><input type="checkbox" v-model="config.service.daemon"> Esegui come Daemon</label>
                    </div>
                    <div class="form-group" v-if="config.service.daemon">
                        <label>Intervallo</label>
                        <div class="inline-inputs">
                            <input type="number" v-model.number="scheduleInterval" class="form-input small" min="1">
                            <select v-model="scheduleFormat" class="form-input small">
                                <option value="hours">Ore</option>
                                <option value="minutes">Minuti</option>
                            </select>
                        </div>
                    </div>
                    <div class="form-group">
                        <label>Log Level</label>
                        <select v-model="config.service.log_level" class="form-input">
                            <option value="DEBUG">DEBUG</option>
                            <option value="INFO">INFO</option>
                            <option value="WARNING">WARNING</option>
                            <option value="ERROR">ERROR</option>
                        </select>
                    </div>
                </div>
            </div>

            <!-- JSON Preview (collapsible) -->
            <div class="config-section">
                <h3 class="section-title collapsible" @click="showJsonPreview = !showJsonPreview">
                    {{ showJsonPreview ? '▼' : '▶' }} Anteprima JSON
                </h3>
                <div v-if="showJsonPreview" class="json-preview">
                    <pre>{{ JSON.stringify(configForDisplay, null, 2) }}</pre>
                </div>
            </div>
        </div>
    </div>
</div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, reactive, watch } from 'vue';
import loadBalancerService from '../services/loadBalancer';

const activeTab = ref('analysis');
const loading = ref(false);
const executing = ref(false);
const error = ref<string | null>(null);
const lastAnalysis = ref<any>(null);
const configJson = ref('{}');
const executionLog = ref<string[]>([]);
const showJsonPreview = ref(false);

// Reactive configuration object with defaults
const config = reactive({
    proxmox_api: {
        hosts: '',
        user: 'root@pam',
        pass: '',
        ssl_verification: false
    },
    proxmox_cluster: {
        maintenance_nodes: [] as string[],
        ignore_nodes: [] as string[],
        overprovisioning: true
    },
    balancing: {
        enable: false,
        enforce_affinity: false,
        enforce_pinning: false,
        parallel: false,
        parallel_jobs: 1,
        live: true,
        with_local_disks: false,
        with_conntrack_state: true,
        balance_types: ['vm', 'ct'] as string[],
        max_job_validation: 1800,
        memory_threshold: 75,
        balanciness: 5,
        method: 'memory',
        mode: 'used',
        balance_larger_guests_first: false,
        node_resource_reserve: {
            defaults: { memory: 2 }
        }
    },
    service: {
        daemon: false,
        log_level: 'INFO',
        schedule: {
            interval: 12,
            format: 'hours'
        }
    }
});

// Helper refs for string-based inputs
const maintenanceNodesStr = ref('');
const ignoreNodesStr = ref('');
const defaultMemoryReserve = ref(2);
const scheduleInterval = ref(12);
const scheduleFormat = ref('hours');

// Sync helpers with config
watch(maintenanceNodesStr, (val) => {
    config.proxmox_cluster.maintenance_nodes = val.split(',').map(s => s.trim()).filter(s => s);
});
watch(ignoreNodesStr, (val) => {
    config.proxmox_cluster.ignore_nodes = val.split(',').map(s => s.trim()).filter(s => s);
});
watch(defaultMemoryReserve, (val) => {
    config.balancing.node_resource_reserve.defaults.memory = val;
});
watch([scheduleInterval, scheduleFormat], () => {
    config.service.schedule = { interval: scheduleInterval.value, format: scheduleFormat.value };
});

const toggleBalanceType = (type: string) => {
    const idx = config.balancing.balance_types.indexOf(type);
    if (idx >= 0) {
        config.balancing.balance_types.splice(idx, 1);
    } else {
        config.balancing.balance_types.push(type);
    }
};

// Nodes and Guests lists
const availableNodes = ref<string[]>([]);
const allGuests = ref<any[]>([]);
const ignoredGuestIds = ref<string[]>([]); // IDs of guests to ignore

// Toggle node in maintenance or ignore list
const toggleNode = (listType: 'maintenance' | 'ignore', nodeName: string) => {
    const list = listType === 'maintenance' 
        ? config.proxmox_cluster.maintenance_nodes 
        : config.proxmox_cluster.ignore_nodes;
    const idx = list.indexOf(nodeName);
    if (idx >= 0) {
        list.splice(idx, 1);
    } else {
        list.push(nodeName);
    }
};

// Computed: guests that can be migrated (not in ignore list)
const migratableGuests = computed(() => {
    return allGuests.value.filter(g => !ignoredGuestIds.value.includes(String(g.id)));
});

// Computed: guests that are ignored
const ignoredGuests = computed(() => {
    return allGuests.value.filter(g => ignoredGuestIds.value.includes(String(g.id)));
});

// Add guest to ignore list
const addToIgnoreList = (guest: any) => {
    const id = String(guest.id);
    if (!ignoredGuestIds.value.includes(id)) {
        ignoredGuestIds.value.push(id);
    }
};

// Remove guest from ignore list
const removeFromIgnoreList = (guest: any) => {
    const id = String(guest.id);
    const idx = ignoredGuestIds.value.indexOf(id);
    if (idx >= 0) {
        ignoredGuestIds.value.splice(idx, 1);
    }
};

// Computed: config for display (password masked)
const configForDisplay = computed(() => {
    const cfg = JSON.parse(JSON.stringify(config));
    if (cfg.proxmox_api && cfg.proxmox_api.pass) {
        cfg.proxmox_api.pass = '********';
    }
    return cfg;
});

const migrations = computed(() => {
    return []; // Placeholder until we verify structure
});

const balanciness = computed(() => {
    if (!lastAnalysis.value || !lastAnalysis.value.nodes) return 'N/A';
    const nodes = Object.values(lastAnalysis.value.nodes) as any[];
    if (nodes.length === 0) return 'N/A';
    
    const memValues = nodes.map(n => n.memory_used_percent || 0);
    const highest = Math.max(...memValues);
    const lowest = Math.min(...memValues);
    const spread = highest - lowest;
    
    return spread.toFixed(1);
});

const runAnalysis = async () => {
    loading.value = true;
    error.value = null;
    executionLog.value = [];
    try {
        const res = await loadBalancerService.analyzeCluster();
        lastAnalysis.value = res.data;
        if (lastAnalysis.value.log) {
             executionLog.value = lastAnalysis.value.log;
        }
        
        // Populate available nodes from analysis
        if (lastAnalysis.value.nodes) {
            availableNodes.value = Object.keys(lastAnalysis.value.nodes);
        }
        
        // Populate guests list from analysis
        if (lastAnalysis.value.guests) {
            allGuests.value = Object.values(lastAnalysis.value.guests);
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
        const saved = res.data.saved || {};
        
        // Merge saved config into reactive config
        if (saved.proxmox_api) {
            // Don't overwrite password if it's masked or empty in saved
            const savedPass = saved.proxmox_api.pass;
            Object.assign(config.proxmox_api, saved.proxmox_api);
            if (!savedPass || savedPass === '********') {
                config.proxmox_api.pass = '';
            }
        }
        if (saved.proxmox_cluster) Object.assign(config.proxmox_cluster, saved.proxmox_cluster);
        if (saved.balancing) Object.assign(config.balancing, saved.balancing);
        if (saved.service) Object.assign(config.service, saved.service);
        
        // Load ignored guests list
        if (saved.ignored_guests && Array.isArray(saved.ignored_guests)) {
            ignoredGuestIds.value = saved.ignored_guests;
        }
        
        // Update helper refs
        maintenanceNodesStr.value = (config.proxmox_cluster.maintenance_nodes || []).join(', ');
        ignoreNodesStr.value = (config.proxmox_cluster.ignore_nodes || []).join(', ');
        defaultMemoryReserve.value = config.balancing.node_resource_reserve?.defaults?.memory || 2;
        scheduleInterval.value = config.service.schedule?.interval || 12;
        scheduleFormat.value = config.service.schedule?.format || 'hours';
        
        configJson.value = JSON.stringify(saved, null, 2);
    } catch (e) {
        console.error(e);
    }
};

const saveConfiguration = async () => {
    try {
        // Build full config object from reactive state
        const fullConfig: any = {
            proxmox_api: { ...config.proxmox_api },
            proxmox_cluster: { ...config.proxmox_cluster },
            balancing: { ...config.balancing },
            service: { ...config.service },
            ignored_guests: ignoredGuestIds.value // List of guest IDs to ignore
        };
        
        // Clean up hosts if it's a string
        if (typeof fullConfig.proxmox_api.hosts === 'string') {
            fullConfig.proxmox_api.hosts = (fullConfig.proxmox_api.hosts as string)
                .split(',').map(s => s.trim()).filter(s => s);
        }
        
        // Don't save the password in plain text if it wasn't changed
        // (backend should handle encryption)
        if (fullConfig.proxmox_api.pass === '') {
            delete fullConfig.proxmox_api.pass;
        }
        
        await loadBalancerService.updateConfig(fullConfig);
        alert('Configurazione salvata!');
    } catch (e) {
        alert('Errore nel salvataggio della configurazione');
        console.error(e);
    }
};

const formatPercent = (val: number) => {
    return (val * 100).toFixed(1) + '%';
};

const formatPercentDirect = (val: number) => {
    if (val === undefined || val === null || isNaN(val)) return 'N/A';
    return val.toFixed(1) + '%';
};

const getGuestCount = (nodeName: string, guestType: 'qemu' | 'lxc') => {
    if (!lastAnalysis.value || !lastAnalysis.value.guests) return 0;
    const guests = lastAnalysis.value.guests;
    let count = 0;
    const proxlbType = guestType === 'qemu' ? 'vm' : 'ct';
    for (const id in guests) {
        const guest = guests[id];
        if (guest.node_current === nodeName && guest.type === proxlbType) {
            count++;
        }
    }
    return count;
};

// Format bytes to human readable
const formatBytes = (bytes: number) => {
    if (!bytes || isNaN(bytes)) return 'N/A';
    const gb = bytes / (1024 * 1024 * 1024);
    if (gb >= 1) return gb.toFixed(1) + ' GB';
    const mb = bytes / (1024 * 1024);
    return mb.toFixed(0) + ' MB';
};

// Get CSS class for progress bar based on percentage
const getProgressClass = (percent: number) => {
    if (!percent || isNaN(percent)) return 'low';
    if (percent >= 85) return 'critical';
    if (percent >= 70) return 'warning';
    return 'normal';
};

// Get overall node health class
const getNodeHealthClass = (node: any) => {
    const mem = node.memory_used_percent || 0;
    const cpu = node.cpu_used_percent || 0;
    if (mem >= 85 || cpu >= 85) return 'health-critical';
    if (mem >= 70 || cpu >= 70) return 'health-warning';
    return 'health-good';
};

// Get node status text
const getNodeStatus = (node: any) => {
    const mem = node.memory_used_percent || 0;
    if (mem >= 85) return '⚠️ Critical';
    if (mem >= 70) return '⚡ High Load';
    return '✅ Healthy';
};

// Get node status CSS class
const getNodeStatusClass = (node: any) => {
    const mem = node.memory_used_percent || 0;
    if (mem >= 85) return 'status-critical';
    if (mem >= 70) return 'status-warning';
    return 'status-healthy';
};

// Get score CSS class
const getScoreClass = (score: string | number) => {
    const val = typeof score === 'string' ? parseFloat(score) : score;
    if (isNaN(val)) return '';
    if (val <= 5) return 'score-good';
    if (val <= 15) return 'score-ok';
    return 'score-bad';
};

// Total VMs across all nodes
const totalVMs = computed(() => {
    if (!lastAnalysis.value || !lastAnalysis.value.guests) return 0;
    return Object.values(lastAnalysis.value.guests as any).filter((g: any) => g.type === 'vm').length;
});

// Total CTs across all nodes
const totalCTs = computed(() => {
    if (!lastAnalysis.value || !lastAnalysis.value.guests) return 0;
    return Object.values(lastAnalysis.value.guests as any).filter((g: any) => g.type === 'ct').length;
});

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

/* Configuration Panel Styles */
.config-panel {
    display: flex;
    flex-direction: column;
    gap: 24px;
    padding-bottom: 40px;
}

.config-section {
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 20px;
}

.section-title {
    font-size: 1.1rem;
    font-weight: 600;
    margin-bottom: 16px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border-color);
}

.section-title.collapsible {
    cursor: pointer;
    user-select: none;
}

.section-title.collapsible:hover {
    color: var(--accent-primary);
}

.form-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 16px;
}

.form-group {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.form-group label {
    font-weight: 500;
    font-size: 0.9rem;
    color: var(--text-secondary);
}

.form-group.checkbox {
    flex-direction: row;
    align-items: center;
    gap: 8px;
}

.form-group.checkbox label {
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
}

.form-group.checkbox-group {
    flex-direction: row;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
}

.form-group.checkbox-group label {
    display: flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
}

.form-input {
    padding: 10px 12px;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.95rem;
}

.form-input:focus {
    outline: none;
    border-color: var(--accent-primary);
}

.form-input.small {
    width: 100px;
}

.inline-inputs {
    display: flex;
    gap: 8px;
    align-items: center;
}

.slider {
    -webkit-appearance: none;
    width: 100%;
    height: 6px;
    background: var(--border-color);
    border-radius: 3px;
    outline: none;
}

.slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 18px;
    height: 18px;
    background: var(--accent-primary);
    border-radius: 50%;
    cursor: pointer;
}

.slider::-moz-range-thumb {
    width: 18px;
    height: 18px;
    background: var(--accent-primary);
    border-radius: 50%;
    cursor: pointer;
    border: none;
}

.slider-value {
    font-weight: 600;
    color: var(--accent-primary);
    min-width: 50px;
}

.help-text {
    font-size: 0.8rem;
    color: var(--text-muted);
}

.info-box {
    background: rgba(59, 130, 246, 0.1);
    border: 1px solid rgba(59, 130, 246, 0.3);
    border-radius: 8px;
    padding: 16px;
    margin-top: 16px;
}

.info-box ul {
    margin: 8px 0 0 20px;
    padding: 0;
}

.info-box li {
    margin: 4px 0;
}

.info-box code {
    background: rgba(0, 0, 0, 0.3);
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 0.85rem;
}

.json-preview {
    background: #1a1a1a;
    border-radius: 8px;
    padding: 16px;
    overflow-x: auto;
    margin-top: 12px;
}

.json-preview pre {
    margin: 0;
    color: #d4d4d4;
    font-size: 0.85rem;
    line-height: 1.5;
}

/* Multi-select and subsections */
.subsection {
    margin-bottom: 20px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--border-color);
}

.subsection:last-child {
    border-bottom: none;
    margin-bottom: 0;
}

.subsection h4 {
    margin: 0 0 4px 0;
    font-size: 0.95rem;
    font-weight: 600;
}

.multi-select-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    margin-top: 10px;
}

.checkbox-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 14px;
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s;
}

.checkbox-item:hover {
    border-color: var(--accent-primary);
}

.checkbox-item input:checked + .node-name {
    color: var(--accent-primary);
    font-weight: 600;
}

.node-name {
    font-size: 0.9rem;
}

.empty-hint {
    padding: 12px;
    color: var(--text-muted);
    font-style: italic;
    font-size: 0.85rem;
}

/* Guest Management */
.guest-management-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
}

@media (max-width: 900px) {
    .guest-management-grid {
        grid-template-columns: 1fr;
    }
}

.guest-list-panel {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 16px;
}

.guest-list-panel h4 {
    margin: 0 0 8px 0;
    font-size: 1rem;
}

.guest-list {
    max-height: 300px;
    overflow-y: auto;
}

.guest-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px;
    border-bottom: 1px solid var(--border-color);
    font-size: 0.9rem;
}

.guest-item:last-child {
    border-bottom: none;
}

.guest-item.ignored {
    opacity: 0.7;
    background: rgba(239, 68, 68, 0.1);
}

.guest-type {
    font-size: 0.7rem;
    font-weight: 700;
    padding: 2px 6px;
    border-radius: 4px;
    min-width: 28px;
    text-align: center;
}

.guest-type.vm {
    background: rgba(59, 130, 246, 0.2);
    color: #3b82f6;
}

.guest-type.ct {
    background: rgba(34, 197, 94, 0.2);
    color: #22c55e;
}

.guest-name {
    flex: 1;
    font-weight: 500;
}

.guest-node {
    color: var(--text-muted);
    font-size: 0.8rem;
}

.btn-sm {
    padding: 4px 8px;
    font-size: 0.8rem;
    border: none;
    border-radius: 4px;
    cursor: pointer;
}

.btn-sm.btn-danger {
    background: rgba(239, 68, 68, 0.2);
    color: #ef4444;
}

.btn-sm.btn-success {
    background: rgba(34, 197, 94, 0.2);
    color: #22c55e;
}

.btn-sm:hover {
    opacity: 0.8;
}

/* Node Health Dashboard */
.health-panel {
    padding-bottom: 40px;
}

.last-update {
    color: var(--text-muted);
    font-size: 0.85rem;
    margin-left: 16px;
}

.nodes-health-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 20px;
    margin-bottom: 24px;
}

.node-health-card {
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 20px;
    transition: all 0.3s ease;
}

.node-health-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
}

.node-health-card.health-good {
    border-left: 4px solid #22c55e;
}

.node-health-card.health-warning {
    border-left: 4px solid #f59e0b;
}

.node-health-card.health-critical {
    border-left: 4px solid #ef4444;
    animation: pulse-critical 2s ease-in-out infinite;
}

@keyframes pulse-critical {
    0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.2); }
    50% { box-shadow: 0 0 0 8px rgba(239, 68, 68, 0); }
}

.node-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
}

.node-name {
    margin: 0;
    font-size: 1.1rem;
    font-weight: 600;
}

.node-status {
    font-size: 0.8rem;
    font-weight: 600;
    padding: 4px 10px;
    border-radius: 12px;
}

.node-status.status-healthy {
    background: rgba(34, 197, 94, 0.2);
    color: #22c55e;
}

.node-status.status-warning {
    background: rgba(245, 158, 11, 0.2);
    color: #f59e0b;
}

.node-status.status-critical {
    background: rgba(239, 68, 68, 0.2);
    color: #ef4444;
}

.metrics-grid {
    display: flex;
    flex-direction: column;
    gap: 14px;
}

.metric-item {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.metric-label {
    display: flex;
    justify-content: space-between;
    font-size: 0.9rem;
}

.metric-value {
    font-weight: 600;
}

.progress-bar {
    height: 8px;
    background: var(--border-color);
    border-radius: 4px;
    overflow: hidden;
}

.progress-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.5s ease;
}

.progress-fill.normal {
    background: linear-gradient(90deg, #22c55e, #4ade80);
}

.progress-fill.warning {
    background: linear-gradient(90deg, #f59e0b, #fbbf24);
}

.progress-fill.critical {
    background: linear-gradient(90deg, #ef4444, #f87171);
}

.progress-fill.low {
    background: var(--text-muted);
}

.metric-detail {
    font-size: 0.75rem;
    color: var(--text-muted);
}

.node-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 16px;
    padding-top: 12px;
    border-top: 1px solid var(--border-color);
}

.guest-counts {
    display: flex;
    gap: 8px;
}

.guest-badge {
    font-size: 0.75rem;
    font-weight: 600;
    padding: 4px 8px;
    border-radius: 6px;
}

.guest-badge.vm {
    background: rgba(59, 130, 246, 0.15);
    color: #3b82f6;
}

.guest-badge.ct {
    background: rgba(168, 85, 247, 0.15);
    color: #a855f7;
}

.node-pve-version {
    font-size: 0.75rem;
    color: var(--text-muted);
}

/* Cluster Summary */
.cluster-summary {
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 20px;
}

.cluster-summary h3 {
    margin: 0 0 16px 0;
    font-size: 1rem;
}

.summary-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 16px;
}

.summary-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 16px;
    background: var(--bg-primary);
    border-radius: 8px;
}

.summary-label {
    font-size: 0.8rem;
    color: var(--text-muted);
    margin-bottom: 4px;
}

.summary-value {
    font-size: 1.5rem;
    font-weight: 700;
}

.summary-value.score-good {
    color: #22c55e;
}

.summary-value.score-ok {
    color: #f59e0b;
}

.summary-value.score-bad {
    color: #ef4444;
}
</style>
