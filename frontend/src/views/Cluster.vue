<template>
  <div class="cluster-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">🖥️ Cluster Management</h1>
        <p class="page-subtitle">Manage Proxmox Cluster, HA, and Configuration</p>
      </div>
      <div class="actions">
        <button class="btn btn-secondary btn-sm" @click="refreshAll" :disabled="loading">
            <span v-if="loading" class="spinner-sm"></span>
            {{ loading ? 'Updating...' : '🔄 Refresh All' }}
        </button>
      </div>
    </div>

    <!-- Tabs -->
    <div class="tabs">
      <button 
        class="tab-btn" 
        :class="{ active: activeTab === 'config' }" 
        @click="activeTab = 'config'">
        ⚙️ Config
      </button>
      <button 
        class="tab-btn" 
        :class="{ active: activeTab === 'monitor' }" 
        @click="activeTab = 'monitor'">
        🖥️ Cluster Monitor
      </button>
      <button 
        class="tab-btn" 
        :class="{ active: activeTab === 'ha' }" 
        @click="activeTab = 'ha'">
        🛡️ HA Manager
      </button>
      <button 
        class="tab-btn danger-tab" 
        :class="{ active: activeTab === 'dangerous' }" 
        @click="activeTab = 'dangerous'">
        ⚠️ Dangerous Ops
      </button>
    </div>

    <div class="tab-content">
      
      <!-- CONFIG TAB -->
      <div v-if="activeTab === 'config'" class="config-panel">
        
        <!-- Cluster Status Card -->
        <div class="card mb-4">
          <div class="flex justify-between items-center">
            <div>
              <h4>📊 Cluster Status</h4>
              <p class="help-text">Current cluster initialization and connection status.</p>
            </div>
            <div class="cluster-status-badge" :class="clusterStatusClass">
              {{ clusterStatusText }}
            </div>
          </div>
          <div v-if="store.clusterStatus" class="cluster-status-grid mt-4">
            <div class="status-item">
              <span class="label">Cluster Name</span>
              <strong>{{ store.clusterStatus.cluster_name || 'N/A' }}</strong>
            </div>
            <div class="status-item">
              <span class="label">Quorum</span>
              <strong :class="store.clusterStatus.quorum ? 'text-success' : 'text-danger'">
                {{ store.clusterStatus.quorum ? 'OK' : 'NO QUORUM' }}
              </strong>
            </div>
            <div class="status-item">
              <span class="label">Nodes</span>
              <strong>{{ store.clusterNodes?.length || 0 }}</strong>
            </div>
            <div class="status-item">
              <span class="label">Votes</span>
              <strong>{{ store.clusterStatus.total_votes || 0 }} / {{ store.clusterStatus.expected_votes || 0 }}</strong>
            </div>
          </div>
          <div v-else class="mt-4 text-secondary">
            <em>⚠️ No cluster data available. Configure entry point below and refresh.</em>
          </div>
        </div>
        
        <div class="card">
          <h4>🔌 Cluster Entry Point</h4>
          <p class="help-text mb-4">Define the primary entry point for cluster API access.</p>
          
          <div class="form-grid">
            <div class="form-group full-width">
              <label>Cluster Hosts / API URL</label>
              <input type="text" v-model="clusterConfig.hosts" class="form-input" placeholder="https://192.168.1.10:8006">
              <small class="text-secondary">Comma separated list of hosts or full API URL.</small>
            </div>
            <div class="form-grid-2">
                <div class="form-group">
                    <label>Username</label>
                    <input type="text" v-model="clusterConfig.user" class="form-input" placeholder="root@pam">
                </div>
                <div class="form-group">
                    <label>Token / Password</label>
                    <input type="password" v-model="clusterConfig.password" class="form-input" placeholder="Enter new password/token to update">
                </div>
            </div>
          </div>
          
          <div class="mt-4 flex justify-end">
              <button class="btn btn-primary" @click="saveClusterConfig">💾 Save Configuration</button>
          </div>
        </div>
      </div>

      <!-- CLUSTER MONITOR TAB -->
      <div v-if="activeTab === 'monitor'" class="monitor-panel">
         
         <div v-if="loading && !lastAnalysis" class="flex justify-center p-12">
             <span class="spinner-lg"></span>
         </div>
         
         <div v-else-if="lastAnalysis">
             <!-- Cluster Summary -->
             <div class="monitor-summary mb-6">
                 <div class="summary-card">
                     <span class="summary-label">Nodes</span>
                     <span class="summary-value">{{ Object.keys(lastAnalysis.nodes || {}).length }}</span>
                 </div>
                 <div class="summary-card">
                     <span class="summary-label">VMs</span>
                     <span class="summary-value">{{ totalVMs }}</span>
                 </div>
                 <div class="summary-card">
                     <span class="summary-label">CTs</span>
                     <span class="summary-value">{{ totalCTs }}</span>
                 </div>
                 <div class="summary-card" v-if="store.clusterStatus">
                     <span class="summary-label">Quorum</span>
                     <span class="summary-value" :class="store.clusterStatus.quorum ? 'text-success' : 'text-danger'">
                         {{ store.clusterStatus.quorum ? 'OK' : 'NO' }}
                     </span>
                 </div>
             </div>

             <!-- Nodes Grid -->
             <div class="nodes-grid">
                <div v-for="(node, nodeName) in lastAnalysis.nodes" :key="nodeName" class="node-card" :class="getNodeHealthClass(node)">
                    <div class="node-header">
                        <div class="node-title">
                            <h3>{{ nodeName }}</h3>
                            <span class="node-status" :class="getNodeStatusClass(node)">{{ getNodeStatus(node) }}</span>
                        </div>
                        <div class="node-score" :class="getScoreClass(node.pressure_score)">
                            Score: {{ node.pressure_score.toFixed(1) }}
                        </div>
                    </div>

                    <div class="metrics-grid">
                        <!-- CPU -->
                        <div class="metric-item">
                            <div class="metric-label">
                                <span>CPU</span>
                                <span class="metric-value">{{ formatPercentDirect(node.cpu_usage_percent) }}</span>
                            </div>
                            <div class="progress-bar">
                                <div class="progress-fill" :class="getProgressClass(node.cpu_usage_percent)" :style="{ width: node.cpu_usage_percent + '%' }"></div>
                            </div>
                        </div>
                        <!-- Memory -->
                        <div class="metric-item">
                            <div class="metric-label">
                                <span>RAM</span>
                                <span class="metric-value">{{ formatPercentDirect(node.memory_usage_percent) }}</span>
                            </div>
                            <div class="progress-bar">
                                <div class="progress-fill" :class="getProgressClass(node.memory_usage_percent)" :style="{ width: node.memory_usage_percent + '%' }"></div>
                            </div>
                            <div class="metric-subtext">{{ formatBytes(node.memory_used) }} / {{ formatBytes(node.memory_total) }}</div>
                        </div>
                        <!-- Network -->
                        <div class="metric-item">
                            <div class="metric-label">
                                <span>📉 Net In</span>
                                <span class="metric-value">{{ formatBytes(node.network_in || 0) }}/s</span>
                            </div>
                        </div>
                        <div class="metric-item">
                            <div class="metric-label">
                                <span>📈 Net Out</span>
                                <span class="metric-value">{{ formatBytes(node.network_out || 0) }}/s</span>
                            </div>
                        </div>
                    </div>

                    <!-- Guest Indicators (Running Guests) -->
                    <div class="guest-indicators">
                        <div class="guest-indicators-header">
                            <span class="indicator-title">Running Guests ({{ getGuestsForNode(nodeName).length }})</span>
                            <button class="btn-xs btn-text" @click="toggleTopology(nodeName)">
                                {{ showTopology[nodeName] ? 'Hide Topology' : 'Show Network Topology' }}
                            </button>
                        </div>
                        <div class="guest-chips-grid">
                            <div 
                                v-for="guest in getGuestsForNode(nodeName)" 
                                :key="guest.id"
                                class="guest-chip"
                                :class="guest.type"
                                :title="getGuestTooltip(guest)"
                            >
                                <span class="chip-icon">{{ guest.type === 'vm' ? '🖥' : '📦' }}</span>
                                <span class="chip-id">{{ guest.name || guest.id }}</span>
                            </div>
                        </div>
                    </div>

                    <!-- Network Topology View -->
                    <div v-if="showTopology[nodeName]" class="network-topology">
                        <h4>🔌 Network Topology</h4>
                        <div v-for="(bridge, bridgeName) in getNetworkTopology(nodeName)" :key="bridgeName" class="topology-bridge">
                            <div class="bridge-header">🌉 {{ bridgeName }}</div>
                            <div v-for="(vlan, vlanId) in bridge" :key="vlanId" class="topology-vlan">
                                <div class="vlan-header">🏷️ VLAN {{ vlanId === 'untagged' ? 'Untagged' : vlanId }}</div>
                                <div class="vlan-guests">
                                    <div v-for="guest in vlan" :key="guest.id" class="topology-guest" :class="guest.type">
                                        {{ guest.type === 'vm' ? '🖥' : '📦' }} <strong>{{ guest.name || guest.id }}</strong> ({{ guest.iface }})
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="node-footer">
                        <div class="guest-counts">
                            <span class="guest-badge vm">{{ getGuestCount(nodeName, 'qemu') }} VMs</span>
                            <span class="guest-badge ct">{{ getGuestCount(nodeName, 'lxc') }} CTs</span>
                        </div>
                    </div>
                </div>
             </div>
         </div>

         <!-- Add Node (Available if needed, or moved to Config) -->
         <div class="card mt-6">
            <h4>➕ Join Node to Cluster</h4>
            <div class="form-grid">
                <div class="form-group">
                    <label>New Node IP</label>
                    <input type="text" v-model="newNodeIP" class="form-input" placeholder="192.168.x.x">
                </div>
            </div>
            <div class="mt-3">
                <button class="btn btn-primary" @click="addNodeToCluster" :disabled="!newNodeIP || loading">
                    ➕ Add Node
                </button>
            </div>
        </div>
      </div>

      <!-- HA MANAGER TAB -->
      <div v-if="activeTab === 'ha'" class="ha-panel">
         <!-- Same content as HA Manager tab in LoadBalancer.vue -->
         
         <!-- HA Resources -->
         <div class="card mb-4">
            <h4>HA Managed Resources</h4>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>SID</th>
                        <th>Type</th>
                        <th>State</th>
                        <th>Group</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="res in store.haResources" :key="res.sid">
                        <td>{{ res.sid }}</td>
                        <td><span class="badge" :class="res.type === 'vm' ? 'badge-success' : 'badge-info'">{{ res.type }}</span></td>
                        <td><span :class="getHAStateClass(res.state)">{{ res.state }}</span></td>
                        <td>{{ res.group || '-' }}</td>
                        <td><button class="btn btn-xs btn-danger" @click="removeFromHA(res)">Remove</button></td>
                    </tr>
                    <tr v-if="store.haResources.length === 0"><td colspan="5" class="text-center p-4">No HA resources.</td></tr>
                </tbody>
            </table>
         </div>

         <!-- Available Guests -->
         <div class="card mb-4">
            <div class="flex justify-between">
                <h4>Available Guests</h4>
                <div class="flex gap-2">
                    <button class="btn btn-xs btn-secondary" @click="selectAllGuests">Select All</button>
                    <button class="btn btn-xs btn-secondary" @click="selectedGuestsForHA = []">Clear</button>
                </div>
            </div>
            <div class="table-scroll">
                <table class="data-table">
                    <thead><tr><th><input type="checkbox" :checked="allGuestsSelected" @change="toggleSelectAllGuests"></th><th>ID</th><th>Name</th><th>Node</th><th>Status</th></tr></thead>
                    <tbody>
                        <tr v-for="guest in store.availableGuests" :key="guest.vmid" :class="{'bg-highlight': selectedGuestsForHA.includes(guest.vmid), 'opacity-50': guest.in_ha}">
                            <td><input type="checkbox" :checked="selectedGuestsForHA.includes(guest.vmid)" @change="toggleGuestForHA(guest.vmid)" :disabled="guest.in_ha"></td>
                            <td>{{ guest.vmid }}</td>
                            <td>{{ guest.name }}</td>
                            <td>{{ guest.node }}</td>
                            <td>{{ guest.in_ha ? '✅ In HA' : guest.status }}</td>
                        </tr>
                    </tbody>
                </table>
            </div>
            
            <div v-if="selectedGuestsForHA.length > 0" class="mt-4 p-4 bg-dark-soft rounded border border-gray-700">
                <h5>Add {{ selectedGuestsForHA.length }} guests to HA</h5>
                <div class="grid grid-cols-3 gap-4 mt-2">
                    <select v-model="newHAResource.group" class="form-input">
                        <option value="">No Group</option>
                        <option v-for="g in store.haGroups" :key="g.group" :value="g.group">{{ g.group }}</option>
                    </select>
                    <select v-model="newHAResource.state" class="form-input">
                        <option value="started">Started</option>
                        <option value="stopped">Stopped</option>
                    </select>
                    <button class="btn btn-primary" @click="addSelectedGuestsToHA">Add to HA</button>
                </div>
            </div>
         </div>

         <!-- HA Groups -->
         <div class="card">
            <h4>HA Groups</h4>
            <div class="grid grid-cols-2 gap-6">
                <div>
                     <table class="data-table">
                        <thead><tr><th>Group</th><th>Nodes</th><th>Action</th></tr></thead>
                        <tbody>
                            <tr v-for="grp in store.haGroups" :key="grp.group">
                                <td>{{ grp.group }}</td>
                                <td>{{ grp.nodes }}</td>
                                <td><button class="btn btn-xs btn-danger" @click="deleteHAGroup(grp.group)">Delete</button></td>
                            </tr>
                        </tbody>
                     </table>
                </div>
                <div class="p-4 bg-dark-soft rounded">
                    <h5>Create Group</h5>
                    <div class="space-y-3 mt-2">
                        <input type="text" v-model="newHAGroup.name" class="form-input" placeholder="Group Name">
                        <div class="space-y-1 max-h-40 overflow-y-auto border border-gray-700 p-2 rounded">
                            <div v-for="node in store.clusterNodes" :key="node.name">
                                <label class="flex items-center gap-2">
                                    <input type="checkbox" :checked="selectedNodesForGroup.some(n => n.name === node.name)" @change="toggleNodeForGroup(node.name)"> 
                                    {{ node.name }}
                                </label>
                            </div>
                        </div>
                        <button class="btn btn-primary w-full" @click="createHAGroupFromSelection">Create Group</button>
                    </div>
                </div>
            </div>
         </div>
      </div>

      <!-- DANGEROUS OPS TAB -->
      <div v-if="activeTab === 'dangerous'" class="dangerous-panel">
          <div class="alert alert-danger mb-6 border-l-4 border-red-600">
              <h3 class="text-red-500 font-bold text-lg flex items-center gap-2">
                  ⚠️ DANGER ZONE
              </h3>
              <p class="mt-2 text-primary">
                  The operations in this section are <strong>destructive</strong>. 
                  Removing nodes incorrectly can break quorum and make your cluster read-only or inaccessible.
              </p>
              <p class="mt-2 font-bold">
                  🛡️ An automatic configuration backup will be triggered before any operation.
              </p>
          </div>

          <div class="card border-red-900/30">
              <h4 class="text-red-400">Manage Dead Nodes</h4>
              <p class="mb-4 text-sm text-secondary">
                  If a node is permanently dead or has been physically removed, you can remove it from the cluster configuration here.
              </p>
              
              <table class="data-table">
                 <thead>
                    <tr>
                        <th>Node Name</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                 </thead>
                 <tbody>
                     <tr v-for="node in store.clusterNodes" :key="node.name">
                         <td class="font-bold">{{ node.name }}</td>
                         <td>
                             <span :class="node.status === 'online' ? 'badge-success' : 'badge-danger'">
                                 {{ node.status?.toUpperCase() }}
                             </span>
                         </td>
                         <td>
                            <div class="flex gap-2">
                                 <button class="btn btn-xs btn-warning" @click="cleanNodeReferences(node.name)" title="Remove leftover config">
                                     🧹 Clean Refs
                                 </button>
                                 <button class="btn btn-xs btn-danger" 
                                     @click="removeNodeFromCluster(node.name)" 
                                     :disabled="node.is_local || node.status === 'online'"
                                     title="Remove from quorum (Must be offline)">
                                     💣 Force Remove
                                 </button>
                            </div>
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
import { ref, reactive, onMounted, computed, watch } from 'vue';
import { useHAStore } from '../stores/ha_store';
import loadBalancerService from '../services/loadBalancer';

const store = useHAStore();
const activeTab = ref('monitor'); // Start on Monitor
const loading = computed(() => store.loading);

// API Config State for "Config" tab
const clusterConfig = reactive({
    hosts: '',
    user: '',
    password: ''
});

// Monitor State
const showTopology = ref<Record<string, boolean>>({});

// New Node State
const newNodeIP = ref('');

// HA Form State
const newHAResource = reactive({
    group: '',
    state: 'started',
    max_restart: 1,
    max_relocate: 1
});
const selectedGuestsForHA = ref<number[]>([]);
const newHAGroup = reactive({
    name: '',
    restricted: false,
    nofailback: false
});
const selectedNodesForGroup = ref<{name: string, priority: number}[]>([]);

// Computed
// Computed
const lastAnalysis = computed(() => store.lastAnalysis);

const totalVMs = computed(() => {
    if (!lastAnalysis.value || !lastAnalysis.value.guests) return 0;
    return Object.values(lastAnalysis.value.guests).filter((g: any) => g.type === 'vm' || g.type === 'qemu').length;
});

const totalCTs = computed(() => {
    if (!lastAnalysis.value || !lastAnalysis.value.guests) return 0;
    return Object.values(lastAnalysis.value.guests).filter((g: any) => g.type === 'ct' || g.type === 'lxc').length;
});

// Cluster status computed properties
const clusterStatusText = computed(() => {
    if (!store.clusterStatus) return 'Not Configured';
    if (store.clusterStatus.quorum) return 'Initialized';
    return 'No Quorum';
});

const clusterStatusClass = computed(() => {
    if (!store.clusterStatus) return 'status-not-configured';
    if (store.clusterStatus.quorum) return 'status-initialized';
    return 'status-warning';
});

const allGuestsSelected = computed(() => {
    const selectable = store.availableGuests.filter(g => !g.in_ha);
    return selectable.length > 0 && selectedGuestsForHA.value.length === selectable.length;
});

// Implementation
const loadMonitorData = async () => {
    // If analysis data is stale (>60s) or missing, fetch it
    // Or just always fetch for now on refresh
    try {
        // OLD: const res = await loadBalancerService.analyzeCluster();
        // NEW: Use lightweight independent monitor
        const nodeId = await getFirstPVENodeId();
        if(!nodeId) return;

        const token = localStorage.getItem('access_token');
        const res = await fetch(`/api/ha/node/${nodeId}/monitor`, { 
            headers: { 'Authorization': `Bearer ${token}` } 
        });
        
        if(!res.ok) throw new Error("Monitor API failed");
        
        const data = await res.json();
        
        // Format matches what store expects enough to render?
        // Store expects { nodes: {...}, guests: {...}, ... }
        // Our new API returns exactly that structure.
        store.setAnalysisResult(data);
    } catch(e) { console.error('Error loading monitor data', e); }
};

const refreshAll = async () => {
    await store.fetchHAData(true);
    // Also load config if on config tab
    if(activeTab.value === 'config') await loadClusterConfig();
    if(activeTab.value === 'monitor') await loadMonitorData();
};

onMounted(() => {
    store.fetchHAData();
    // Default tab is monitor, so load data
    loadMonitorData();
    // Start background refresh
    store.startBackgroundRefresh();
});

watch(activeTab, (val) => {
    if(val === 'config') loadClusterConfig();
    if(val === 'monitor') loadMonitorData();
});

// Helper to get node ID
const getFirstPVENodeId = async () => {
    // We can get this from store.clusterNodes if populated, else fetch
    // But store.clusterNodes comes from complete-data which needs a node ID first!
    // Circular dependency? ha_store handles it by fetching /nodes/ first internally.
    // So we can assume if store.clusterNodes has data, we can use one.
    // If not, we might need to fetch /api/nodes ourselves.
    // Let's rely on store or fetch manual
    const token = localStorage.getItem('access_token');
    try {
        const nodesRes = await fetch('/api/nodes/', { headers: { 'Authorization': `Bearer ${token}` } });
        const nodes = await nodesRes.json();
        if (nodes.length > 0) return nodes[0].id;
    } catch(e) { console.error(e); }
    return null;
};

// --- CONFIG ACTIONS ---
const loadClusterConfig = async () => {
    // This would fetch from /api/load-balancer/config basically
    // For now we mock or use existing
    try {
        const token = localStorage.getItem('access_token');
        const res = await fetch('/api/load-balancer/config', { headers: { 'Authorization': `Bearer ${token}` } });
        const data = await res.json();
        if(data.proxmox_api) {
            clusterConfig.hosts = data.proxmox_api.hosts || '';
            clusterConfig.user = data.proxmox_api.user || '';
            // Pass not returned
        }
    } catch(e) {}
};

const saveClusterConfig = async () => {
     try {
        const token = localStorage.getItem('access_token');
        // Retrieve current config first to merge
        const res = await fetch('/api/load-balancer/config', { headers: { 'Authorization': `Bearer ${token}` } });
        const currentMox = await res.json();
        
        const payload = {
            ...currentMox,
            proxmox_api: {
                ...currentMox.proxmox_api,
                hosts: clusterConfig.hosts,
                user: clusterConfig.user
            }
        };
        if(clusterConfig.password) {
            payload.proxmox_api.pass = clusterConfig.password;
        }

        await fetch('/api/load-balancer/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify(payload)
        });
        alert('Configuration saved!');
     } catch(e) { alert('Error: ' + e); }
};

// --- CLUSTER MGMT ACTIONS ---
const addNodeToCluster = async () => {
   if(!confirm(`Add ${newNodeIP.value} to cluster?`)) return;
   const nodeId = await getFirstPVENodeId();
   if (!nodeId) return;
   
   // Reuse logic
   const token = localStorage.getItem('access_token');
   try {
       const res = await fetch(`/api/ha/node/${nodeId}/cluster/nodes`, {
           method: 'POST',
           headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
           body: JSON.stringify({ new_node_ip: newNodeIP.value })
       });
       const d = await res.json();
       if(d.success) { alert('Node added!'); refreshAll(); }
       else alert('Error: ' + d.message);
   } catch(e) { alert('Error: ' + e); }
};

// --- HA ACTIONS ---
const getHAStateClass = (state: string) => {
    if(state === 'started') return 'badge-success';
    if(state === 'stopped') return 'badge-secondary';
    return 'badge-warning';
};

const removeFromHA = async (res: any) => {
    if(!confirm('Remove resource?')) return;
    const nodeId = await getFirstPVENodeId();
    if (!nodeId) return;
    try {
        const token = localStorage.getItem('access_token');
        await fetch(`/api/ha/node/${nodeId}/resources/${res.sid}?vm_type=${res.type}`, {
            method: 'DELETE', headers: { 'Authorization': `Bearer ${token}` }
        });
        refreshAll();
    } catch(e) { alert('Error: ' + e); }
};

const deleteHAGroup = async (groupName: string) => {
     if(!confirm('Delete Group?')) return;
     const nodeId = await getFirstPVENodeId();
     if (!nodeId) return;
     try {
         const token = localStorage.getItem('access_token');
         await fetch(`/api/ha/node/${nodeId}/groups/${groupName}`, {
             method: 'DELETE', headers: { 'Authorization': `Bearer ${token}` }
         });
         refreshAll();
     } catch(e) { alert('Error: ' + e); }
};

const toggleGuestForHA = (vmid: number) => {
    const idx = selectedGuestsForHA.value.indexOf(vmid);
    if(idx === -1) selectedGuestsForHA.value.push(vmid);
    else selectedGuestsForHA.value.splice(idx,1);
};

const toggleSelectAllGuests = () => {
    if(allGuestsSelected.value) selectedGuestsForHA.value = [];
    else selectedGuestsForHA.value = store.availableGuests.filter(g => !g.in_ha).map(g => g.vmid);
};

const selectAllGuests = () => toggleSelectAllGuests();

const addSelectedGuestsToHA = async () => {
    const nodeId = await getFirstPVENodeId();
    const token = localStorage.getItem('access_token');
    
    for(const vmid of selectedGuestsForHA.value) {
        const guest = store.availableGuests.find(g => g.vmid === vmid);
        if(!guest) continue;
        
        await fetch(`/api/ha/node/${nodeId}/resources`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({
                vmid, vm_type: guest.type,
                group: newHAResource.group || null,
                state: newHAResource.state,
                max_restart: 1, max_relocate: 1
            })
        });
    }
    selectedGuestsForHA.value = [];
    refreshAll();
};

const toggleNodeForGroup = (name: string) => {
    const idx = selectedNodesForGroup.value.findIndex(n => n.name === name);
    if(idx === -1) selectedNodesForGroup.value.push({name, priority: 1});
    else selectedNodesForGroup.value.splice(idx, 1);
};

const createHAGroupFromSelection = async () => {
    if(!newHAGroup.name) return;
    const nodeId = await getFirstPVENodeId();
    const token = localStorage.getItem('access_token');
    
    const nodes = selectedNodesForGroup.value.map(n => n.name); // Simple list for now, ignoring priority for brevity or implementing simple
    
    await fetch(`/api/ha/node/${nodeId}/groups`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({
            name: newHAGroup.name,
            nodes: nodes,
            restricted: false, nofailback: false
        })
    });
    newHAGroup.name = '';
    selectedNodesForGroup.value = [];
    refreshAll();
};

// --- DANGEROUS OPS ---
const triggerClusterBackup = async () => {
    // Phase 4: Call backend backup endpoint
    // For now, check if implementation exists in backend. 
    // Since we are writing frontend code first, we assume endpoint will look like this
    // or we print a console log
    console.log("Triggering auto-backup...");
    try {
        const token = localStorage.getItem('access_token');
        await fetch('/api/load-balancer/cluster/backup-config', { method: 'POST', headers: { 'Authorization': `Bearer ${token}` } });
    } catch(e) {
        console.warn("Backup endpoint error", e);
    }
};

const removeNodeFromCluster = async (name: string) => {
    if(!confirm(`DANGER: Remove ${name}? Node must be OFFLINE.`)) return;
    if(!confirm(`Are you really sure? This can break quorum.`)) return;
    
    await triggerClusterBackup();

    const nodeId = await getFirstPVENodeId();
    const token = localStorage.getItem('access_token');
    try {
        const res = await fetch(`/api/ha/node/${nodeId}/cluster/nodes/${name}`, {
             method: 'DELETE', headers: { 'Authorization': `Bearer ${token}` }
        });
        const d = await res.json();
        if(d.success) { alert('Removed.'); refreshAll(); }
        else alert('Error: ' + d.message);
    } catch(e) { alert('Error: ' + e); }
};

const cleanNodeReferences = async (name: string) => {
    if(!confirm(`Clean references for ${name}?`)) return;
    
    await triggerClusterBackup();

    const nodeId = await getFirstPVENodeId();
    const token = localStorage.getItem('access_token');
    try {
        const res = await fetch(`/api/ha/node/${nodeId}/cluster/nodes/${name}/clean`, {
             method: 'POST', headers: { 'Authorization': `Bearer ${token}` }
        });
        alert('Cleaned.');
    } catch(e) { alert('Error: ' + e); }
};

watch(activeTab, (val) => {
    if(val === 'config') loadClusterConfig();
});
// --- HELPER FUNCTIONS ---

const formatBytes = (bytes: number) => {
    if (!bytes || isNaN(bytes)) return 'N/A';
    const gb = bytes / (1024 * 1024 * 1024);
    if (gb >= 1) return gb.toFixed(1) + ' GB';
    const mb = bytes / (1024 * 1024);
    return mb.toFixed(0) + ' MB';
};

const formatPercentDirect = (val: number) => {
    if (val === undefined || val === null || isNaN(val)) return 'N/A';
    return val.toFixed(1) + '%';
};

const getGuestsForNode = (nodeName: string) => {
    if (!lastAnalysis.value || !lastAnalysis.value.guests) return [];
    const guests = lastAnalysis.value.guests;
    const nodeGuests = [];
    for (const id in guests) {
        const guest = guests[id];
        if (guest.node_current === nodeName) {
            nodeGuests.push({ ...guest, id });
        }
    }
    return nodeGuests.sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));
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

const getNodeStatus = (node: any) => {
    if (node.pressure_score > 50) return 'Critical';
    if (node.pressure_score > 20) return 'Warning';
    return 'Healthy';
};

const getNodeStatusClass = (node: any) => {
    if (node.pressure_score > 50) return 'status-critical';
    if (node.pressure_score > 20) return 'status-warning';
    return 'status-healthy';
};

const getScoreClass = (score: number) => {
    if (score > 50) return 'score-critical';
    if (score > 20) return 'score-warning';
    return 'score-healthy';
};

const getNodeHealthClass = (node: any) => {
   return getNodeStatusClass(node);
};

const getProgressClass = (percent: number) => {
    if (percent > 80) return 'bg-danger';
    if (percent > 60) return 'bg-warning';
    return 'bg-success';
};

const getGuestTooltip = (guest: any) => {
    const name = guest.name || guest.id;
    const type = guest.type === 'vm' ? 'VM' : 'Container';
    const cpu = guest.cpu_used ? (guest.cpu_used * 100).toFixed(1) + '%' : 'N/A';
    const mem = guest.memory_used ? formatBytes(guest.memory_used) : 'N/A';
    const disk = guest.disk_used ? formatBytes(guest.disk_used) : 'N/A';
    const netIn = guest.network_in ? formatBytes(guest.network_in) : '0 B';
    const netOut = guest.network_out ? formatBytes(guest.network_out) : '0 B';
    return `${type}: ${name} (ID: ${guest.id})\nCPU: ${cpu}\nMem: ${mem}\nDisk: ${disk}\nNet In: ${netIn}/s\nNet Out: ${netOut}/s`;
};

const toggleTopology = (nodeName: string) => {
    showTopology.value[nodeName] = !showTopology.value[nodeName];
};

const getNetworkTopology = (nodeName: string) => {
    const topology: Record<string, Record<string, any[]>> = {};
    const guests = getGuestsForNode(nodeName);
    
    guests.forEach(g => {
        const networks = g.networks || [];
        if (networks.length === 0) return;

        networks.forEach((net: any) => {
            const bridge = net.bridge || 'Unknown';
            const vlan = net.tag || 'untagged';
            
            if (!topology[bridge]) topology[bridge] = {};
            if (!topology[bridge][vlan]) topology[bridge][vlan] = [];
            
            topology[bridge][vlan].push({
                id: g.id,
                type: g.type,
                iface: net.id || net.ifname || 'net?'
            });
        });
    });
    
    // Sort keys
    const sortedTopology: Record<string, any> = {};
    Object.keys(topology).sort().forEach(bridge => {
        sortedTopology[bridge] = {};
        Object.keys(topology[bridge]).sort((a, b) => {
            if (a === 'untagged') return -1;
            if (b === 'untagged') return 1;
            return parseInt(a) - parseInt(b);
        }).forEach(vlan => {
            sortedTopology[bridge][vlan] = topology[bridge][vlan];
        });
    });
    
    return sortedTopology;
};
</script>

<style scoped>
.cluster-page { padding: 20px; max-width: 1600px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; margin-bottom: 24px; }
.page-title { font-size: 1.8rem; font-weight: bold; margin: 0; }
.page-subtitle { color: var(--text-secondary); margin: 4px 0 0 0; }
.tabs { display: flex; gap: 8px; margin-bottom: 24px; border-bottom: 1px solid var(--border-color); padding-bottom: 1px; }
.tab-btn { background: none; border: none; padding: 10px 20px; color: var(--text-secondary); cursor: pointer; border-bottom: 2px solid transparent; transition: all 0.2s; }
.tab-btn:hover { color: var(--text-primary); }
.tab-btn.active { color: var(--accent-primary); border-bottom-color: var(--accent-primary); }
.tab-btn.danger-tab:hover { color: #fe4242; }
.tab-btn.danger-tab.active { color: #fe4242; border-bottom-color: #fe4242; }

.card { background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 8px; padding: 20px; margin-bottom: 20px; }
.form-grid { display: grid; gap: 16px; max-width: 600px; }
.form-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.full-width { grid-column: 1 / -1; }
.form-input { width: 100%; background: var(--bg-secondary); border: 1px solid var(--border-color); color: var(--text-primary); padding: 8px 12px; border-radius: 6px; }
.form-group label { display: block; margin-bottom: 6px; color: var(--text-secondary); font-size: 0.9rem; }
.btn { padding: 8px 16px; border-radius: 6px; font-weight: 500; cursor: pointer; border: none; }
.btn-primary { background: var(--accent-primary); color: #000; }
.btn-secondary { background: var(--bg-secondary); color: var(--text-primary); border: 1px solid var(--border-color); }
.btn-danger { background: rgba(239,68,68,0.2); color: #f87171; }
.btn-warning { background: rgba(245,158,11,0.2); color: #fbbf24; }
.badge { padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }
.badge-success { background: rgba(16, 185, 129, 0.2); color: #34d399; }
.badge-danger { background: rgba(239, 68, 68, 0.2); color: #f87171; }
.badge-info { background: rgba(59, 130, 246, 0.2); color: #60a5fa; }

/* Cluster Status Badge */
.cluster-status-badge { padding: 6px 16px; border-radius: 20px; font-size: 0.85rem; font-weight: 600; text-transform: uppercase; }
.cluster-status-badge.status-initialized { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
.cluster-status-badge.status-warning { background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
.cluster-status-badge.status-not-configured { background: rgba(100, 116, 139, 0.2); color: #94a3b8; border: 1px solid rgba(100, 116, 139, 0.3); }
.data-table { width: 100%; border-collapse: collapse; }
.data-table th { text-align: left; padding: 12px; color: var(--text-secondary); border-bottom: 2px solid var(--border-color); font-size: 0.85rem; }
.data-table td { padding: 12px; border-bottom: 1px solid var(--border-color); vertical-align: middle; }
.cluster-status-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-top: 16px; }
.status-item { display: flex; flex-direction: column; background: var(--bg-secondary); padding: 12px; border-radius: 6px; }
.status-item .label { font-size: 0.75rem; color: var(--text-secondary); text-transform: uppercase; }
.status-item strong { font-size: 1.2rem; margin-top: 4px; }
.spinner-sm { display: inline-block; width: 12px; height: 12px; border: 2px solid currentColor; border-top-color: transparent; border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
.text-xs { font-size: 0.75rem; }
.text-sm { font-size: 0.875rem; }
.font-mono { font-family: monospace; }
/* Monitor Styles */
.monitor-panel { animation: fadeIn 0.3s ease; }
.monitor-summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px; }
.summary-card { background: var(--bg-surface); border: 1px solid var(--border-color); padding: 16px; border-radius: 8px; display: flex; flex-direction: column; align-items: center; }
.summary-label { font-size: 0.8rem; text-transform: uppercase; color: var(--text-secondary); margin-bottom: 4px; }
.summary-value { font-size: 1.8rem; font-weight: bold; }
.text-success { color: #34d399; }
.text-danger { color: #f87171; }

.nodes-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr)); gap: 20px; }
.node-card { background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 8px; padding: 16px; transition: transform 0.2s, box-shadow 0.2s; }
.node-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.2); }
.node-card.status-critical { border-color: #f87171; box-shadow: 0 0 0 1px #f87171 inset; }
.node-card.status-warning { border-color: #fbbf24; }

.node-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--border-color); }
.node-title h3 { margin: 0 0 4px 0; font-size: 1.1rem; }
.node-status { font-size: 0.75rem; padding: 2px 6px; border-radius: 4px; font-weight: 600; text-transform: uppercase; }
.node-status.status-healthy { background: rgba(16, 185, 129, 0.1); color: #34d399; }
.node-status.status-warning { background: rgba(245, 158, 11, 0.1); color: #fbbf24; }
.node-status.status-critical { background: rgba(239, 68, 68, 0.1); color: #f87171; }

.node-score { font-size: 0.8rem; font-weight: bold; padding: 4px 8px; border-radius: 4px; background: rgba(255,255,255,0.05); }
.score-healthy { color: #34d399; }
.score-warning { color: #fbbf24; }
.score-critical { color: #f87171; }

.metrics-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.metric-item { background: var(--bg-secondary); padding: 8px 12px; border-radius: 6px; }
.metric-label { display: flex; justify-content: space-between; font-size: 0.8rem; color: var(--text-secondary); margin-bottom: 4px; }
.metric-value { color: var(--text-primary); font-weight: 600; }
.progress-bar { height: 4px; background: rgba(255,255,255,0.1); border-radius: 2px; overflow: hidden; margin-top: 4px; }
.progress-fill { height: 100%; border-radius: 2px; transition: width 0.3s ease; background: #3b82f6; }
.bg-success { background: #34d399; }
.bg-warning { background: #fbbf24; }
.bg-danger { background: #f87171; }
.metric-subtext { font-size: 0.7rem; color: var(--text-disabled); margin-top: 2px; text-align: right; }

/* Guest Indicators */
.guest-indicators { margin-top: 16px; background: var(--bg-secondary); padding: 10px; border-radius: 8px; }
.guest-indicators-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.indicator-title { font-size: 0.8rem; font-weight: 600; color: var(--text-secondary); }
.guest-chips-grid { display: flex; flex-wrap: wrap; gap: 4px; }
.guest-chip { display: flex; align-items: center; gap: 4px; padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; cursor: help; border: 1px solid transparent; }
.guest-chip.vm { background: rgba(59, 130, 246, 0.15); color: #3b82f6; border-color: rgba(59, 130, 246, 0.2); }
.guest-chip.ct { background: rgba(168, 85, 247, 0.15); color: #a855f7; border-color: rgba(168, 85, 247, 0.2); }
.guest-chip:hover { filter: brightness(1.1); }
.btn-text { background: none; border: none; padding: 0; color: var(--accent-primary); cursor: pointer; font-size: 0.75rem; text-decoration: underline; }

/* Network Topology */
.network-topology { margin-top: 12px; padding: 12px; background: #0f172a; border-radius: 8px; border: 1px solid var(--border-color); }
.network-topology h4 { margin: 0 0 10px 0; font-size: 0.9rem; color: var(--accent-primary); }
.topology-bridge { margin-bottom: 12px; padding-left: 8px; border-left: 2px solid var(--border-color); }
.bridge-header { font-weight: 600; font-size: 0.9rem; margin-bottom: 6px; color: var(--text-primary); }
.topology-vlan { margin-left: 16px; margin-bottom: 8px; }
.vlan-header { font-size: 0.8rem; color: var(--text-secondary); margin-bottom: 4px; font-family: monospace; }
.vlan-guests { display: flex; flex-wrap: wrap; gap: 6px; margin-left: 8px; }
.topology-guest { font-size: 0.75rem; padding: 2px 6px; background: rgba(255, 255, 255, 0.05); border-radius: 4px; color: var(--text-muted); }
.topology-guest.vm strong { color: #3b82f6; }
.topology-guest.ct strong { color: #a855f7; }

.node-footer { margin-top: 12px; border-top: 1px solid var(--border-color); padding-top: 12px; display: flex; justify-content: space-between; align-items: center; font-size: 0.8rem; color: var(--text-secondary); }
.guest-counts { display: flex; gap: 8px; }
.guest-badge { padding: 2px 6px; border-radius: 4px; background: var(--bg-secondary); border: 1px solid var(--border-color); }
.guest-badge.vm { color: #3b82f6; }
.guest-badge.ct { color: #a855f7; }
</style>
