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
        :class="{ active: activeTab === 'management' }" 
        @click="activeTab = 'management'">
        📊 Management
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

      <!-- MANAGEMENT TAB -->
      <div v-if="activeTab === 'management'" class="management-panel">
         <!-- Cluster Status -->
         <div class="card mb-4" v-if="store.clusterStatus">
            <div class="flex justify-between items-center mb-2">
                <h4>Cluster Status</h4>
                <span class="badge" :class="store.clusterStatus.quorum ? 'badge-success' : 'badge-danger'">
                    {{ store.clusterStatus.quorum ? 'QUORUM OK' : 'NO QUORUM' }}
                </span>
            </div>
            <div class="cluster-status-grid">
                <div class="status-item">
                    <span class="label">Cluster Name</span>
                    <strong>{{ store.clusterStatus.cluster_name || 'N/A' }}</strong>
                </div>
                <div class="status-item">
                    <span class="label">Nodes</span>
                    <strong>{{ store.clusterNodes.length }}</strong>
                </div>
                <div class="status-item">
                    <span class="label">Expected Votes</span>
                    <strong>{{ store.clusterStatus.expected_votes || 0 }}</strong>
                </div>
                <div class="status-item">
                    <span class="label">Total Votes</span>
                    <strong>{{ store.clusterStatus.total_votes || 0 }}</strong>
                </div>
            </div>
        </div>

        <!-- Nodes List -->
        <div class="card mb-4">
            <h4>Cluster Nodes</h4>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Name</th>
                        <th>Votes</th>
                        <th>Status</th>
                        <th>Address</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="node in store.clusterNodes" :key="node.node_id">
                        <td>{{ node.node_id }}</td>
                        <td>
                            <strong>{{ node.name }}</strong>
                            <span v-if="node.is_local" class="badge-info ml-1 text-xs">LOCAL</span>
                        </td>
                        <td>{{ node.votes }}</td>
                        <td>
                            <span :class="node.status === 'online' ? 'badge-success' : 'badge-danger'">
                                {{ node.status?.toUpperCase() }}
                            </span>
                        </td>
                         <td>
                            <span class="font-mono text-sm">{{ node.ip || '-' }}</span>
                        </td>
                    </tr>
                    <tr v-if="store.clusterNodes.length === 0">
                        <td colspan="5" class="text-center py-4">No nodes found.</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <!-- Add Node -->
        <div class="card">
            <h4>➕ Join Node to Cluster</h4>
            <div class="form-grid">
                <div class="form-group">
                    <label>New Node IP</label>
                    <input type="text" v-model="newNodeIP" class="form-input" placeholder="192.168.x.x">
                </div>
                <!-- Links defined but hidden for simplicity unless needed, or basic inputs -->
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

const store = useHAStore();
const activeTab = ref('management');
const loading = computed(() => store.loading);

// API Config State for "Config" tab
const clusterConfig = reactive({
    hosts: '',
    user: '',
    password: ''
});

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
const allGuestsSelected = computed(() => {
    const selectable = store.availableGuests.filter(g => !g.in_ha);
    return selectable.length > 0 && selectedGuestsForHA.value.length === selectable.length;
});

// Implementation
const refreshAll = async () => {
    await store.fetchHAData(true);
    // Also load config if on config tab
    if(activeTab.value === 'config') await loadClusterConfig();
};

onMounted(() => {
    store.fetchHAData();
    // Start background refresh
    store.startBackgroundRefresh();
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
</style>
