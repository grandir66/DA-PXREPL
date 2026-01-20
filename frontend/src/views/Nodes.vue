<template>
  <div class="nodes-page">
    <div class="page-header">
        <h1 class="page-title">🖥️ Nodi Proxmox</h1>
        <p class="page-subtitle">Gestione e monitoraggio nodi del cluster</p>
        <div style="display: flex; align-items: center; gap: 12px; margin-top: 12px;">
            <button class="btn btn-primary btn-sm" @click="openModal">
                + Nuovo Nodo
            </button>
            <button class="btn btn-secondary btn-sm" @click="loadNodes" :disabled="loading">
                <span v-if="loading" class="spinner-sm"></span>
                <span v-else>🔄 Aggiorna</span>
            </button>
        </div>
    </div>

    <div class="card">
        <div class="table-container">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Nome</th>
                        <th>Hostname</th>
                        <th>Stato</th>
                        <th>CPU</th>
                        <th>RAM</th>
                        <th>Storage</th>
                        <th>VM</th>
                        <th>Temp</th>
                        <th>Ver</th>
                        <th>Sanoid</th>
                        <th>Azioni</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="node in nodes" :key="node.id">
                        <td><strong>{{ node.name }}</strong></td>
                        <td>{{ node.hostname }}</td>
                        <td>
                            <span class="badge" :class="node.is_online ? 'badge-success' : 'badge-danger'">
                                <span class="status-dot"></span>
                                {{ node.is_online ? 'Online' : 'Offline' }}
                            </span>
                        </td>
                        <td>
                            <span v-if="node.cpu?.cores">{{ node.cpu.cores }} cores</span>
                            <span v-else class="text-secondary">N/A</span>
                        </td>
                        <td>
                            <div v-if="node.memory?.total_gb">
                                <div>{{ formatSize(node.memory.total_gb * 1024 * 1024 * 1024) }}</div>
                                <div class="text-sm text-secondary">
                                    Usata: {{ formatSize((node.memory.used_gb || 0) * 1024 * 1024 * 1024) }}
                                </div>
                            </div>
                            <span v-else class="text-secondary">N/A</span>
                        </td>
                        <td>
                            <div v-if="node.storage_total_gb && node.storage_total_gb > 0">
                                <div>{{ formatSize(node.storage_total_gb * 1024 * 1024 * 1024) }}</div>
                                <div class="text-sm text-secondary">
                                    Usato: {{ formatSize((node.storage_used_gb || 0) * 1024 * 1024 * 1024) }}
                                </div>
                            </div>
                            <span v-else class="text-secondary">N/A</span>
                        </td>
                        <td>
                            <router-link :to="'/vms?search=' + node.name" class="no-underline hover:text-accent transition-colors" title="Vedi VM di questo nodo">
                                <span v-if="node.vm_count !== undefined">
                                    {{ node.vm_count }} 
                                    <span v-if="node.running_vm_count && node.running_vm_count > 0" style="color: var(--accent-primary);">
                                        ({{ node.running_vm_count }} running)
                                    </span>
                                </span>
                                <span v-else class="text-secondary">-</span>
                            </router-link>
                        </td>
                        <td>
                            <span v-if="node.temperature_highest_c">
                                {{ node.temperature_highest_c }}°C
                            </span>
                            <span v-else class="text-secondary">N/A</span>
                        </td>
                        <td>
                            <span v-if="node.proxmox_version">{{ node.proxmox_version }}</span>
                            <span v-else class="text-secondary">-</span>
                        </td>
                        <td>
                             <div v-if="node.node_type === 'pve'">
                                <span v-if="node.sanoid_installed" class="badge badge-success" title="Sanoid Installato">
                                    ✅ {{ node.sanoid_version || 'OK' }}
                                    <button class="btn-icon-sm" @click.stop="updateSanoid(node)" title="Aggiorna Sanoid">⬆️</button>
                                </span>
                                <button v-else class="btn btn-warning btn-xs" @click="installSanoid(node)" title="Installa Sanoid">⚠️ Installa</button>
                             </div>
                             <span v-else class="text-secondary">-</span>
                        </td>
                        <td>
                            <div class="btn-group">
                                <button class="btn btn-secondary btn-sm" @click="showNodeDetails(node)" title="Dettagli">📊 Info</button>
                                <button class="btn btn-secondary btn-sm" @click="testNode(node)" title="Test Connessione">🔌 Test</button>
                                <button class="btn btn-primary btn-sm" @click="editNode(node)" title="Modifica">✏️ Modifica</button>
                                <button class="btn btn-danger btn-sm" @click="deleteNode(node)" title="Elimina">🗑️</button>
                            </div>
                        </td>
                    </tr>
                    <tr v-if="nodes.length === 0 && !loading">
                         <td colspan="10" class="empty-state-cell">Nessun nodo trovato</td>
                    </tr>
                    <tr v-if="loading && nodes.length === 0">
                        <td colspan="10" class="empty-state-cell">⏳ Caricamento nodi...</td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>

    <!-- Host Details Modal -->
    <div v-if="showDetailsModal && selectedNode" class="modal-overlay" @click.self="closeDetailsModal">
        <div class="modal-content large">
            <div class="modal-header">
                <h3>📊 Dettagli Nodo: {{ selectedNode.name }}</h3>
                <div class="header-actions" style="display:flex; gap:10px;">
                    <button class="btn btn-warning btn-sm" @click="runDiagnosticStart" :disabled="diagnosticLoading">
                        {{ diagnosticLoading ? '⏳ Esecuzione...' : '🩺 Diagnostic' }}
                    </button>
                    <button class="close-btn" @click="closeDetailsModal">&times;</button>
                </div>
            </div>
            <div class="modal-body">
                <div v-if="refreshing" class="text-center p-6">
                    <div class="spinner-lg mb-4"></div>
                    <p>Aggiornamento dati dai nodi in corso...</p>
                    <p class="text-secondary text-sm">Potrebbe richiedere alcuni secondi.</p>
                </div>
                <div v-else-if="!selectedNode.host_info" class="text-center p-4">
                    <p class="text-secondary">Nessun dato dettagliato disponibile.</p>
                    <button class="btn btn-primary mt-2" @click="refreshData">Aggiorna Dati Ora</button>
                </div>
                <div v-else class="details-grid">
                    <!-- CPU -->
                    <div class="detail-card">
                        <h4>🔲 CPU</h4>
                        <div class="kpi-row">
                            <div class="kpi">
                                <span class="val">{{ selectedNode.cpu?.cores || '-' }}</span>
                                <span class="lbl">Cores</span>
                            </div>
                            <div class="kpi">
                                <span class="val">{{ selectedNode.host_info.cpu?.threads || '-' }}</span>
                                <span class="lbl">Threads</span>
                            </div>
                            <div class="kpi">
                                <span class="val">{{ selectedNode.host_info.cpu?.sockets || '-' }}</span>
                                <span class="lbl">Sockets</span>
                            </div>
                        </div>
                        <div class="kpi-row mt-2">
                            <div class="kpi small">
                                <span class="val">{{ selectedNode.host_info.cpu?.load_1m?.toFixed(2) || '0' }}</span>
                                <span class="lbl">Load 1m</span>
                            </div>
                            <div class="kpi small">
                                <span class="val">{{ selectedNode.host_info.cpu?.load_5m?.toFixed(2) || '0' }}</span>
                                <span class="lbl">Load 5m</span>
                            </div>
                            <div class="kpi small">
                                <span class="val">{{ selectedNode.host_info.cpu?.load_15m?.toFixed(2) || '0' }}</span>
                                <span class="lbl">Load 15m</span>
                            </div>
                        </div>
                        <div class="list-info mt-2">
                            <div class="text-sm text-secondary">{{ selectedNode.cpu?.model || 'N/A' }}</div>
                        </div>
                    </div>

                    <!-- RAM -->
                    <div class="detail-card">
                        <h4>🧠 Memoria</h4>
                        <div class="progress-bar-container" v-if="selectedNode.memory">
                            <div class="progress-bar" :style="{width: ((selectedNode.memory.used_gb / selectedNode.memory.total_gb) * 100) + '%'}"></div>
                        </div>
                        <div class="kpi-row mt-2">
                            <div class="kpi small">
                                <span class="val">{{ selectedNode.memory?.used_gb?.toFixed(1) || '-' }}</span>
                                <span class="lbl">Used GB</span>
                            </div>
                            <div class="kpi small">
                                <span class="val">{{ selectedNode.memory?.total_gb?.toFixed(1) || '-' }}</span>
                                <span class="lbl">Total GB</span>
                            </div>
                            <div class="kpi small">
                                <span class="val">{{ selectedNode.host_info.memory?.available_gb?.toFixed(1) || '-' }}</span>
                                <span class="lbl">Avail GB</span>
                            </div>
                        </div>
                        <div class="stats-row text-xs mt-2" v-if="selectedNode.host_info.memory?.swap_total_gb">
                             <span>Swap: {{ selectedNode.host_info.memory.swap_used_gb?.toFixed(1) || 0 }} / {{ selectedNode.host_info.memory.swap_total_gb?.toFixed(1) || 0 }} GB</span>
                        </div>
                    </div>

                    <!-- System Info -->
                    <div class="detail-card">
                        <h4>🖥️ Sistema</h4>
                        <table class="simple-table">
                            <tr><td>Proxmox:</td><td><strong>{{ selectedNode.host_info.proxmox_version || selectedNode.proxmox_version || '-' }}</strong></td></tr>
                            <tr><td>Kernel:</td><td>{{ selectedNode.host_info.kernel_version || '-' }}</td></tr>
                            <tr><td>Uptime:</td><td>{{ formatUptime(selectedNode.host_info.uptime_seconds || 0) }}</td></tr>
                            <tr><td>Node Name:</td><td>{{ selectedNode.host_info.node_name || selectedNode.name }}</td></tr>
                        </table>
                    </div>

                    <!-- Hardware -->
                    <div class="detail-card">
                        <h4>🔧 Hardware</h4>
                        <table class="simple-table">
                            <tr><td>Produttore:</td><td>{{ selectedNode.host_info.hardware?.manufacturer || '-' }}</td></tr>
                            <tr><td>Modello:</td><td>{{ selectedNode.host_info.hardware?.model || '-' }}</td></tr>
                            <tr><td>Serial:</td><td class="text-xs">{{ selectedNode.host_info.hardware?.serial || '-' }}</td></tr>
                            <tr><td>BIOS:</td><td>{{ selectedNode.host_info.hardware?.bios_vendor || '-' }} {{ selectedNode.host_info.hardware?.bios_version || '' }}</td></tr>
                            <tr><td>Board:</td><td>{{ selectedNode.host_info.hardware?.board || '-' }}</td></tr>
                        </table>
                    </div>

                    <!-- Temperature -->
                    <div class="detail-card" v-if="selectedNode.temperature_highest_c || selectedNode.host_info.temperature?.highest">
                        <h4>🌡️ Temperatura</h4>
                        <div class="kpi-row">
                            <div class="kpi">
                                <span class="val" :class="{'text-danger': (selectedNode.temperature_highest_c || selectedNode.host_info.temperature?.highest) > 80}">
                                    {{ selectedNode.temperature_highest_c || selectedNode.host_info.temperature?.highest || '-' }}°C
                                </span>
                                <span class="lbl">Max</span>
                            </div>
                        </div>
                    </div>

                    <!-- License -->
                    <div class="detail-card" v-if="selectedNode.host_info.license">
                        <h4>📜 Licenza</h4>
                        <table class="simple-table">
                            <tr><td>Stato:</td><td>
                                <span :class="selectedNode.host_info.license.status === 'active' ? 'text-success' : 'text-warning'">
                                    {{ selectedNode.host_info.license.status || 'N/A' }}
                                </span>
                            </td></tr>
                            <tr v-if="selectedNode.host_info.license.subscription"><td>Subscription:</td><td class="text-xs">{{ selectedNode.host_info.license.subscription }}</td></tr>
                        </table>
                    </div>

                    <!-- Storage (full width) -->
                    <div class="detail-card full-width">
                        <h4>💽 Storage / Datastores ({{ (selectedNode.host_info.storage || []).length }})</h4>
                        <div class="storage-list" v-if="selectedNode.host_info.storage?.length">
                             <div v-for="store in selectedNode.host_info.storage" :key="store.name" class="pool-item">
                                <div class="pool-header">
                                    <strong>{{ store.name }}</strong>
                                    <span class="text-xs text-secondary">{{ store.type }}</span>
                                    <span :class="store.status === 'active' || store.status === 'available' ? 'text-success' : 'text-secondary'" class="text-xs">{{ store.status }}</span>
                                    <span v-if="store.shared" class="badge badge-info text-xs">Shared</span>
                                </div>
                                <div class="pool-stats">
                                    <div class="progress-bar-container" style="height:6px; margin:4px 0;">
                                         <div class="progress-bar" :style="{width: (store.used_percent || 0) + '%', background: (store.used_percent > 90 ? 'var(--failure)' : store.used_percent > 75 ? 'var(--warning)' : 'var(--accent-primary)')}"></div>
                                    </div>
                                    <span class="text-sm">{{ store.used_gb?.toFixed(1) || 0 }} / {{ store.total_gb?.toFixed(1) || 0 }} GB ({{ store.used_percent?.toFixed(1) || 0 }}%)</span>
                                    <span v-if="store.content" class="text-xs text-secondary ml-2">{{ store.content }}</span>
                                </div>
                             </div>
                        </div>
                        <div v-else class="text-secondary text-sm">Nessun storage rilevato</div>
                    </div>

                    <!-- Network Topology -->
                    <div class="detail-card full-width" v-if="selectedNode.host_info?.network?.length">
                        <h4>🕸️ Network Topology</h4>
                        
                        <!-- Bridges -->
                        <div class="topology-bridges-list">
                            <div v-for="bridge in getBridges(selectedNode.host_info.network)" 
                                 :key="bridge.name" 
                                 class="topology-bridge-box">
                                
                                <!-- Bridge Header -->
                                <div class="topology-bridge-header">
                                    <span class="bridge-name">{{ bridge.name }}</span>
                                    <span class="bridge-cidr">{{ bridge.ip || 'L2 Switch' }}</span>
                                </div>
                                
                                <!-- Bridge Ports (Physical NICs) -->
                                <div v-if="bridge.bridge_ports" class="bridge-ports-info">
                                    <span class="bridge-ports-label">Uplink:</span>
                                    <div class="bridge-ports-list">
                                        <template v-for="port in bridge.bridge_ports.split(' ').filter((p: string) => p)" :key="port">
                                            <div class="bridge-port-group">
                                                <span class="bridge-port-chip" :class="{ bond: port.startsWith('bond') }">
                                                    {{ port }}
                                                    <span v-if="getBondMode(selectedNode.host_info.network, port)" class="bond-mode-badge">
                                                        {{ getBondMode(selectedNode.host_info.network, port) }}
                                                    </span>
                                                </span>
                                                <!-- Show bond slaves -->
                                                <div v-if="getBondSlaves(selectedNode.host_info.network, port)" class="bond-slaves">
                                                    <span class="slaves-arrow">→</span>
                                                    <span v-for="slave in getBondSlaves(selectedNode.host_info.network, port)" :key="slave" class="slave-nic">
                                                        {{ slave }}
                                                    </span>
                                                </div>
                                            </div>
                                        </template>
                                    </div>
                                </div>

                                <!-- Guests connected to this bridge -->
                                <div class="topology-guests" v-if="selectedNode.host_info.guests?.length">
                                    <div v-for="guest in getGuestsOnBridge(selectedNode.host_info.guests, bridge.name)" 
                                         :key="guest.id" 
                                         class="topology-guest-item"
                                         :class="{ vm: guest.type === 'vm', ct: guest.type === 'ct' }">
                                        <span class="guest-icon">{{ guest.type === 'vm' ? '💻' : '📦' }}</span>
                                        <div class="guest-info">
                                            <strong>{{ guest.name || guest.id }}</strong>
                                            <span class="guest-id">ID: {{ guest.id }} - {{ guest.status }}</span>
                                        </div>
                                        <!-- VLAN tag -->
                                        <span v-if="getGuestVlanOnBridge(guest, bridge.name)" class="badge badge-purple" style="margin-left: auto; font-size: 0.7rem;">
                                            VLAN {{ getGuestVlanOnBridge(guest, bridge.name) }}
                                        </span>
                                    </div>
                                    
                                    <div v-if="getGuestsOnBridge(selectedNode.host_info.guests, bridge.name).length === 0" class="no-guests">
                                        No guests connected
                                    </div>
                                </div>
                            </div>
                        </div>
                        
                        <!-- Other Interfaces (non-bridge) -->
                        <details v-if="getNonBridgeInterfaces(selectedNode.host_info.network).length > 0" class="mt-3">
                            <summary class="cursor-pointer text-secondary text-sm">📋 Other Interfaces ({{ getNonBridgeInterfaces(selectedNode.host_info.network).length }})</summary>
                            <div class="storage-list mt-2">
                                <div v-for="iface in getNonBridgeInterfaces(selectedNode.host_info.network)" :key="iface.name" class="pool-item">
                                    <div class="pool-header">
                                        <strong>{{ iface.name }}</strong>
                                        <span class="text-xs text-secondary">{{ iface.type }}</span>
                                        <span :class="iface.status === 'UP' ? 'text-success' : 'text-secondary'" class="text-xs">{{ iface.status }}</span>
                                    </div>
                                    <div class="pool-stats text-sm">
                                        <span v-if="iface.ip">IP: {{ iface.ip }}</span>
                                        <span v-if="iface.mac" class="text-xs text-secondary ml-2">MAC: {{ iface.mac }}</span>
                                    </div>
                                </div>
                            </div>
                        </details>
                    </div>

                    <!-- Raw Data Toggle -->
                    <div class="detail-card full-width">
                        <details>
                            <summary class="cursor-pointer text-secondary">📋 Mostra dati raw JSON</summary>
                            <pre class="text-xs mt-2" style="max-height: 300px; overflow: auto; background: var(--bg-secondary); padding: 8px; border-radius: 4px;">{{ JSON.stringify(selectedNode.host_info, null, 2) }}</pre>
                        </details>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <div v-if="showModal" class="modal-overlay">
        <div class="modal-content">
            <div class="modal-header">
                <h3>{{ editingNodeId ? 'Modifica Nodo' : 'Aggiungi Nuovo Nodo' }}</h3>
                <button class="close-btn" @click="closeModal">&times;</button>
            </div>
            <div class="modal-body">
                <div class="form-group">
                    <label>Nome Nodo</label>
                    <input type="text" v-model="form.name" class="form-input" placeholder="pve-01">
                </div>
                <!-- ... rest of form ... -->
                <div class="form-group">
                    <label>Hostname / IP</label>
                    <input type="text" v-model="form.hostname" class="form-input" placeholder="192.168.1.10">
                </div>
                <div class="grid-2">
                    <div class="form-group">
                        <label>Utente SSH</label>
                        <input type="text" v-model="form.ssh_user" class="form-input" placeholder="root">
                    </div>
                    <div class="form-group">
                        <label>Porta SSH</label>
                        <input type="number" v-model.number="form.ssh_port" class="form-input">
                    </div>
                </div>
                <div class="form-group">
                    <label>Tipo Nodo</label>
                    <select v-model="form.node_type" class="form-input">
                        <option value="pve">Proxmox VE</option>
                        <option value="pbs">Proxmox Backup Server</option>
                    </select>
                </div>
                 <div class="form-group" v-if="form.node_type === 'pve'">
                    <label>Tipo Storage</label>
                    <select v-model="form.storage_type" class="form-input">
                        <option value="zfs">ZFS</option>
                        <option value="btrfs">BTRFS</option>
                    </select>
                </div>
                 <!-- PBS Specific Fields -->
                 <div v-if="form.node_type === 'pbs'" class="pbs-fields">
                     <div class="form-group">
                         <label>Datastore PBS</label>
                         <input type="text" v-model="form.pbs_datastore" class="form-input" placeholder="datastore1">
                         <small class="text-secondary">Nome del datastore su cui salvare i backup</small>
                     </div>
                     <div class="grid-2">
                         <div class="form-group">
                             <label>Utente PBS</label>
                             <input type="text" v-model="form.pbs_username" class="form-input" placeholder="root@pam">
                         </div>
                         <div class="form-group">
                             <label>Password PBS</label>
                             <input type="password" v-model="form.pbs_password" class="form-input" placeholder="Password API">
                         </div>
                     </div>
                     <div class="form-group">
                         <label>Fingerprint SSL (opzionale)</label>
                         <input type="text" v-model="form.pbs_fingerprint" class="form-input" placeholder="xx:xx:xx:...">
                         <small class="text-secondary">Fingerprint per verifica SSL. Lascia vuoto per auto-rilevamento.</small>
                     </div>
                 </div>
                 <div class="form-group">
                     <label>Password Root (per setup SSH iniziale)</label>
                     <input type="password" v-model="form.ssh_password" class="form-input" placeholder="Opzionale se chiave già presente">
                     <small class="text-secondary">Usata solo per copiare la chiave pubblica, non salvata.</small>
                 </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" @click="closeModal">Annulla</button>
                <button class="btn btn-primary" @click="saveNode" :disabled="creating">
                    {{ creating ? 'Salvataggio...' : (editingNodeId ? 'Salva Modifiche' : 'Crea Nodo') }}
                </button>
            </div>
        </div>
    </div>

    <!-- Diagnostic Output Modal -->
    <div v-if="showDiagnosticModal" class="modal-overlay" style="z-index: 1005;" @click.self="showDiagnosticModal = false">
        <div class="modal-content large" style="max-width: 800px;">
            <div class="modal-header">
                <h3>🩺 Risultati Diagnostica: {{ selectedNode?.name }}</h3>
                <button class="close-btn" @click="showDiagnosticModal = false">&times;</button>
            </div>
            <div class="modal-body">
                <div class="terminal-output" style="background: #1e1e1e; color: #f0f0f0; padding: 16px; border-radius: 6px; font-family: monospace; white-space: pre-wrap; max-height: 500px; overflow-y: auto;">
                    {{ diagnosticOutput }}
                </div>
                <div v-if="diagnosticExitCode !== 0" class="mt-4 text-danger font-bold">
                    ⚠️ Script terminato con codice errore: {{ diagnosticExitCode }}
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" @click="showDiagnosticModal = false">Chiudi</button>
            </div>
        </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import nodesService, { type Node } from '../services/nodes';

const nodes = ref<Node[]>([]);
const loading = ref(false);
const refreshing = ref(false);
const showModal = ref(false);
const showDetailsModal = ref(false);
const selectedNode = ref<Node | null>(null);
const creating = ref(false);
const editingNodeId = ref<number | null>(null);

// Diagnostic State
const showDiagnosticModal = ref(false);
const diagnosticLoading = ref(false);
const diagnosticOutput = ref('');
const diagnosticExitCode = ref(0);

const form = reactive({
    name: '',
    hostname: '',
    ssh_user: 'root',
    ssh_port: 22,
    node_type: 'pve',
    storage_type: 'zfs',
    ssh_password: '',
    auto_distribute_key: true,
    // PBS specific
    pbs_datastore: '',
    pbs_username: 'root@pam',
    pbs_password: '',
    pbs_fingerprint: ''
});

const route = useRoute();

onMounted(async () => {
    await loadNodes();
    
    // Check for query param to auto-open node info modal
    const openInfo = route.query.openInfo as string;
    if (openInfo) {
        // Find node by name and open info modal
        const node = nodes.value.find(n => n.name === openInfo || String(n.id) === openInfo);
        if (node) {
            openModal('info', node);
        }
    }
});

const loadNodes = async () => {
    loading.value = true;
    try {
        const res = await nodesService.getNodes();
        nodes.value = res.data;
    } catch (e) {
        console.error('Error loading nodes', e);
    } finally {
        loading.value = false;
    }
};

const refreshData = async () => {
    if (refreshing.value) return;
    refreshing.value = true;
    // Feedback immediato
    const originalText = "Aggiorna Dati Ora";
    
    try {
        await nodesService.refreshAllCache();
        
        // Polling per 5 tentativi (max 10s) per vedere se i dati arrivano
        let attempts = 0;
        const maxAttempts = 5;
        
        const poll = setInterval(async () => {
            attempts++;
            await loadNodes();
            
            // Aggiorna selectedNode con i nuovi dati
            if (selectedNode.value) {
                const updatedNode = nodes.value.find(n => n.id === selectedNode.value?.id);
                if (updatedNode) {
                    selectedNode.value = updatedNode;
                    // Se abbiamo host_info, possiamo fermarci? 
                    // No, magari sta ancora finendo, ma se abbiamo i dati mostriamoli
                    if (updatedNode.host_info) {
                        clearInterval(poll);
                        refreshing.value = false;
                    }
                }
            }
            
            if (attempts >= maxAttempts) {
                clearInterval(poll);
                refreshing.value = false;
            }
        }, 2000); // Ogni 2s
        
    } catch (e) {
        console.error("Errore refresh dati", e);
        alert("Errore durante l'aggiornamento dati");
        refreshing.value = false;
    }
};

const showNodeDetails = (node: Node) => {
    selectedNode.value = node;
    showDetailsModal.value = true;
};

const closeDetailsModal = () => {
    showDetailsModal.value = false;
    selectedNode.value = null;
};

const formatUptime = (seconds: number) => {
    const d = Math.floor(seconds / (3600*24));
    const h = Math.floor(seconds % (3600*24) / 3600);
    const m = Math.floor(seconds % 3600 / 60);
    return `${d}d ${h}h ${m}m`;
};

const openModal = () => {
    editingNodeId.value = null;
    form.name = '';
    form.hostname = '';
    form.ssh_user = 'root';
    form.ssh_port = 22;
    form.node_type = 'pve';
    form.storage_type = 'zfs';
    form.ssh_password = '';
    form.pbs_datastore = '';
    form.pbs_username = 'root@pam';
    form.pbs_password = '';
    form.pbs_fingerprint = '';
    showModal.value = true;
};

const editNode = (node: Node) => {
    console.log("Editing node data:", JSON.parse(JSON.stringify(node)));
    editingNodeId.value = node.id;
    form.name = node.name || '';
    form.hostname = node.hostname || '';
    form.ssh_user = 'root'; // Not returned by backend for security
    form.ssh_port = 22;
    form.node_type = node.node_type || 'pve';
    form.storage_type = node.storage_type || 'zfs';
    form.ssh_password = '';
    form.pbs_datastore = node.pbs_datastore || '';
    form.pbs_username = node.pbs_username || 'root@pam';
    form.pbs_password = '';
    form.pbs_fingerprint = node.pbs_fingerprint || '';
    showModal.value = true;
};

const closeModal = () => {
    showModal.value = false;
};

const saveNode = async () => {
    if(!form.name || !form.hostname) {
        alert("Nome e Hostname richiesti");
        return;
    }
    creating.value = true;
    try {
        // Sanitize payload
        const payload: Record<string, any> = {
            ...form,
            ssh_password: form.ssh_password || null,
            ssh_port: parseInt(String(form.ssh_port)) || 22
        };
        
        // Only include pbs_password if user actually entered something
        // (to avoid overwriting existing password with null during edits)
        if (form.pbs_password && form.pbs_password.trim()) {
            payload.pbs_password = form.pbs_password;
        } else if (!editingNodeId.value) {
            // For new nodes, include it even if empty
            payload.pbs_password = null;
        } else {
            // For edits, don't include it if empty (preserve existing)
            delete payload.pbs_password;
        }
        
        if (editingNodeId.value) {
            await nodesService.updateNode(editingNodeId.value, payload);
        } else {
            await nodesService.createNode(payload);
        }
        showModal.value = false;
        loadNodes();
    } catch (e: any) {
        console.error('Error saving node', e);
        const errorMsg = e.response?.data?.detail || e.message;
        alert('Errore salvataggio nodo: ' + errorMsg);
    } finally {
        creating.value = false;
    }
};

const runDiagnosticStart = async () => {
    if (!selectedNode.value) return;
    
    diagnosticLoading.value = true;
    diagnosticOutput.value = '';
    
    try {
        const res = await nodesService.runDiagnostic(selectedNode.value.id);
        diagnosticOutput.value = res.data.output || res.data.error || 'Nessun output restituito.';
        diagnosticExitCode.value = res.data.exit_code;
        
        // Show modal only when done
        showDiagnosticModal.value = true;
    } catch (e: any) {
        console.error("Diagnostic error:", e);
        diagnosticOutput.value = `Errore esecuzione diagnostica:\n${e.response?.data?.detail || e.message}`;
        diagnosticExitCode.value = 1;
        showDiagnosticModal.value = true;
    } finally {
        diagnosticLoading.value = false;
    }
};

const deleteNode = async (node: Node) => {
    if(!confirm(`Sei sicuro di voler eliminare il nodo ${node.name}?`)) return;
    try {
        await nodesService.deleteNode(node.id);
        loadNodes();
    } catch (e: any) {
        alert('Errore eliminazione: ' + (e.response?.data?.detail || e.message));
    }
};

const testNode = async (node: Node) => {
    try {
        await nodesService.testNode(node.id);
        alert(`Test connessione avviato per ${node.name}. Ricarica la pagina tra poco per vedere lo stato aggiornato.`);
        loadNodes();
    } catch (e: any) {
        alert('Errore test connessione: ' + (e.response?.data?.detail || e.message));
    }
};

const installSanoid = async (node: Node) => {
    if(!confirm(`Installare Sanoid/Syncoid sul nodo ${node.name}? Questo richiederà alcuni secondi.`)) return;
    try {
        alert(`Installazione avviata su ${node.name}...`);
        await nodesService.installSanoid(node.id);
        alert('Installazione completata con successo!');
        loadNodes();
    } catch (e: any) {
        alert('Errore installazione Sanoid: ' + (e.response?.data?.detail || e.message));
    }
};

const formatSize = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
};

const updateSanoid = async (node: Node) => {
    if(!confirm(`Aggiornare Sanoid sul nodo ${node.name}? L'operazione potrebbe richiedere alcuni minuti.`)) return;
    try {
        alert(`Aggiornamento Sanoid avviato su ${node.name}...`);
        await nodesService.updateSanoid(node.id);
        alert('Aggiornamento completato con successo!');
        loadNodes();
    } catch (e: any) {
        alert('Errore aggiornamento Sanoid: ' + (e.response?.data?.detail || e.message));
    }
};

// ===== Network Topology Helpers =====

// Filter to get only bridge interfaces
const getBridges = (interfaces: any[]): any[] => {
    if (!interfaces) return [];
    return interfaces.filter((i: any) => i.type === 'bridge');
};

// Filter to get non-bridge interfaces (for the collapsed section)
const getNonBridgeInterfaces = (interfaces: any[]): any[] => {
    if (!interfaces) return [];
    return interfaces.filter((i: any) => i.type !== 'bridge');
};

// Get bond mode in human-readable format
const getBondMode = (interfaces: any[], portName: string): string | null => {
    if (!interfaces || !portName.startsWith('bond')) return null;
    
    const bondIface = interfaces.find((i: any) => i.name === portName && i.type === 'bond');
    if (!bondIface || !bondIface.bond_mode) return null;
    
    const modeMap: Record<string, string> = {
        'balance-rr': 'RR',
        'active-backup': 'Active-Backup',
        'balance-xor': 'XOR',
        'broadcast': 'Broadcast',
        '802.3ad': 'LACP',
        'balance-tlb': 'TLB',
        'balance-alb': 'ALB'
    };
    
    return modeMap[bondIface.bond_mode] || bondIface.bond_mode;
};

// Get bond slave interfaces
const getBondSlaves = (interfaces: any[], portName: string): string[] | null => {
    if (!interfaces || !portName.startsWith('bond')) return null;
    
    const bondIface = interfaces.find((i: any) => i.name === portName && i.type === 'bond');
    if (!bondIface) return null;
    
    if (bondIface.slaves) {
        return bondIface.slaves.split(' ').filter((s: string) => s.trim());
    }
    
    return null;
};

// Get guests connected to a specific bridge
const getGuestsOnBridge = (guests: any[], bridgeName: string): any[] => {
    if (!guests) return [];
    return guests.filter((g: any) => {
        if (!g.networks) return false;
        return g.networks.some((n: any) => n.bridge === bridgeName);
    });
};

// Get VLAN tag for a guest on a specific bridge
const getGuestVlanOnBridge = (guest: any, bridgeName: string): string | null => {
    if (!guest.networks) return null;
    const net = guest.networks.find((n: any) => n.bridge === bridgeName);
    return net?.tag || null;
};
</script>

<style scoped>
.text-secondary { color: var(--text-secondary); }
.text-sm { font-size: 0.85em; }
.empty-state-cell { text-align: center; padding: 30px; color: var(--text-secondary); }
.spinner-sm {
    display: inline-block;
    width: 12px; height: 12px;
    border: 2px solid currentColor;
    border-top-color: transparent;
    border-radius: 50%;
    animation: spin 1s linear infinite;
}
.spinner-lg {
    display: inline-block;
    width: 40px; height: 40px;
    border: 4px solid var(--accent-primary);
    border-top-color: transparent;
    border-radius: 50%;
    animation: spin 1s linear infinite;
    margin: 0 auto;
}
/* Modal Styles */
.modal-overlay {
    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.5);
    display: flex; align-items: center; justify-content: center;
    z-index: 1000;
}
.modal-content {
    background: var(--bg-surface);
    padding: 24px;
    border-radius: 8px;
    width: 500px;
    max-width: 90%;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
}
.modal-header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 20px;
}
.close-btn { background: none; border: none; font-size: 24px; color: var(--text-secondary); cursor: pointer; }
.form-group { margin-bottom: 16px; }
.form-group label { display: block; margin-bottom: 6px; color: var(--text-secondary); font-size: 0.9em; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.modal-footer {
    display: flex; justify-content: flex-end; gap: 12px; margin-top: 24px;
}
.btn-icon-sm {
    background: none; border: none; cursor: pointer; font-size: 0.9em; padding: 0 4px; opacity: 0.7;
}
.btn-icon-sm:hover { opacity: 1; transform: scale(1.1); }

/* Details Modal Styles */
.modal-content.large {
    width: 800px;
    max-width: 95vw;
    max-height: 90vh;
    display: flex;
    flex-direction: column;
}
.modal-content.large .modal-body {
    overflow-y: auto;
    flex: 1;
    max-height: calc(90vh - 100px);
    padding-right: 8px;
}
.details-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
}
.full-width { grid-column: 1 / -1; }
.detail-card {
    background: var(--bg-hover);
    padding: 16px;
    border-radius: 8px;
    border: 1px solid var(--border-color);
}
.detail-card h4 {
    margin: 0 0 12px 0;
    color: var(--text-secondary);
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-bottom: 1px solid var(--border-color);
    padding-bottom: 8px;
}
.kpi-row { display: flex; gap: 24px; margin-bottom: 12px; }
.kpi { display: flex; flex-direction: column; }
.kpi .val { font-size: 1.5rem; font-weight: bold; color: white; }
.kpi .lbl { font-size: 0.75rem; color: var(--text-secondary); }

.list-info { font-size: 0.9rem; color: var(--text-primary); }

.progress-bar-container {
    height: 8px; background: rgba(255,255,255,0.1); border-radius: 4px; overflow: hidden; margin-bottom: 8px;
}
.progress-bar { height: 100%; background: var(--success); transition: width 0.3s; }

.stats-row { display: flex; justify-content: space-between; font-size: 0.85rem; color: var(--text-secondary); }
.text-success { color: var(--success); }
.text-danger { color: var(--failure); }

.simple-table { width: 100%; font-size: 0.9rem; }
.simple-table td { padding: 4px 0; border-bottom: 1px solid var(--border-color); }
.simple-table td:first-child { color: var(--text-secondary); width: 40%; }

.pool-item { display: flex; flex-direction: column; gap: 4px; padding: 8px 0; border-bottom: 1px solid var(--border-color); }
.pool-header { display: flex; justify-content: space-between; }
.pool-stats { font-size: 0.85rem; color: var(--text-secondary); }

/* Network Topology Styles */
.topology-bridges-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.topology-bridge-box {
    background: var(--bg-hover);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    overflow: hidden;
}

.topology-bridge-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 14px;
    background: rgba(234, 179, 8, 0.1);
    border-bottom: 1px solid var(--border-color);
}

.bridge-name {
    font-weight: 600;
    font-family: var(--font-mono);
    color: #fbbf24;
}

.bridge-cidr {
    font-size: 0.85rem;
    color: var(--text-secondary);
}

.bridge-ports-info {
    padding: 8px 14px;
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    background: rgba(0, 0, 0, 0.2);
    border-bottom: 1px solid var(--border-color);
}

.bridge-ports-label {
    font-size: 0.75rem;
    color: var(--text-secondary);
    text-transform: uppercase;
}

.bridge-ports-list {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
}

.bridge-port-group {
    display: flex;
    align-items: center;
    gap: 4px;
    flex-wrap: wrap;
}

.bridge-port-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 0.75rem;
    font-family: var(--font-mono);
    padding: 2px 8px;
    background: rgba(96, 165, 250, 0.1);
    border: 1px solid rgba(96, 165, 250, 0.3);
    border-radius: 4px;
    color: #60a5fa;
}

.bridge-port-chip.bond {
    background: rgba(96, 165, 250, 0.2);
    color: #60a5fa;
}

.bond-mode-badge {
    font-size: 0.65rem;
    padding: 1px 4px;
    background: rgba(16, 185, 129, 0.2);
    color: #34d399;
    border-radius: 3px;
    font-weight: 600;
    text-transform: uppercase;
}

.bond-slaves {
    display: flex;
    align-items: center;
    gap: 4px;
    flex-wrap: wrap;
}

.slaves-arrow {
    color: var(--text-tertiary);
    font-size: 0.8rem;
}

.slave-nic {
    font-size: 0.7rem;
    font-family: var(--font-mono);
    padding: 1px 6px;
    background: rgba(139, 92, 246, 0.1);
    border: 1px solid rgba(139, 92, 246, 0.3);
    border-radius: 3px;
    color: #a78bfa;
}

.topology-guests {
    padding: 8px;
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.topology-guest-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px;
    background: var(--bg-body);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    font-size: 0.8rem;
}

.topology-guest-item:hover {
    border-color: var(--accent-primary);
}

.guest-icon {
    font-size: 1.2rem;
}

.guest-info {
    display: flex;
    flex-direction: column;
    gap: 2px;
}

.guest-id {
    font-size: 0.7rem;
    color: var(--text-secondary);
}

.no-guests {
    padding: 12px;
    text-align: center;
    color: var(--text-tertiary);
    font-size: 0.8rem;
}

.badge-purple {
    background: rgba(139, 92, 246, 0.2);
    color: #a78bfa;
    padding: 2px 6px;
    border-radius: 4px;
}

.mt-3 { margin-top: 12px; }
.mt-2 { margin-top: 8px; }
.ml-2 { margin-left: 8px; }
.text-xs { font-size: 0.75rem; }

</style>
