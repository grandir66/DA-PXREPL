<template>
  <div class="cluster-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">🖥️ Cluster Management</h1>
        <p class="page-subtitle">Manage Proxmox Cluster, HA, and Configuration</p>
      </div>
      <div class="actions">
        <!-- Cluster Selector -->
        <div class="cluster-selector mr-3" v-if="clusters.length > 0">
             <select 
                :value="selectedClusterId" 
                @change="selectCluster(Number(($event.target as HTMLSelectElement).value))" 
                class="form-select text-sm"
                style="min-width: 200px;"
            >
                <option v-for="c in clusters" :key="c.id" :value="c.id">
                    {{ c.name }} {{ c.is_default ? '(Default)' : '' }}
                </option>
            </select>
        </div>

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
        class="tab-btn" 
        :class="{ active: activeTab === 'topology' }" 
        @click="activeTab = 'topology'">
        🌐 Topology
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
        
        <!-- Multi-Cluster List View -->
        <div class="card" v-if="!isEditingCluster">
          <div class="flex justify-between items-center mb-4">
               <div>
                  <h4>🔌 Cluster Connections</h4>
                  <p class="help-text">Manage connecting to one or more Proxmox clusters. These connections are used for Monitoring, HA, and Load Balancing.</p>
               </div>
               <button class="btn btn-primary btn-sm" @click="startEditCluster()">➕ Add Cluster</button>
          </div>
          
          <div v-if="clusters.length === 0" class="text-center p-8 bg-custom-gray rounded text-secondary border border-dashed border-gray-600">
               No clusters configured. Click "Add Cluster" to connect.
          </div>

          <div v-else class="cluster-list">
               <div v-for="cluster in clusters" :key="cluster.id" class="cluster-item p-4 border border-gray-700 rounded mb-2 flex justify-between items-center hover:bg-opacity-50 hover:bg-gray-800 transition-colors" :class="{'ring-2 ring-blue-500 bg-gray-800': selectedClusterId === cluster.id}">
                   <div class="flex items-center gap-3 cursor-pointer flex-grow" @click="selectCluster(cluster.id)">
                       <span class="text-2xl">{{ selectedClusterId === cluster.id ? '🟢' : '⚪' }}</span>
                       <div>
                           <div class="font-bold flex items-center gap-2 text-lg">
                               {{ cluster.name || `Cluster (${cluster.hosts.split(',')[0]})` }}
                               <span v-if="cluster.is_default" class="px-2 py-0.5 text-xs bg-blue-900 text-blue-200 rounded">Default</span>
                               <span v-if="cluster.is_initialized" class="px-2 py-0.5 text-xs bg-green-900 text-green-200 rounded">Online</span>
                               <span v-else class="px-2 py-0.5 text-xs bg-yellow-900 text-yellow-200 rounded">Offline</span>
                           </div>
                           <div class="text-xs text-secondary mt-1 font-mono">
                               {{ cluster.hosts }} • {{ cluster.api_user || 'Token' }}
                           </div>
                       </div>
                   </div>
                   <div class="flex gap-2">
                       <button class="btn btn-sm btn-secondary" @click.stop="startEditCluster(cluster)">✏️ Edit</button>
                       <button class="btn btn-sm btn-danger" @click.stop="deleteCluster(cluster.id)">🗑️ Delete</button>
                   </div>
               </div>
          </div>
        </div>

        <!-- Add/Edit Cluster Form -->
        <div class="card" v-if="isEditingCluster">
           <h4 class="mb-6 pb-2 border-b border-gray-700">{{ editingClusterId ? 'Edit Cluster' : 'New Cluster Connection' }}</h4>
           
           <div class="form-grid">
             <div class="form-group">
               <label>Friendly Name</label>
               <input type="text" v-model="clusterConfig.name" class="form-input" placeholder="e.g. Production Cluster">
               <small class="text-secondary">Name used to identify this cluster in menus.</small>
             </div>
             <div class="form-group">
               <label>Cluster Hosts / IPs</label>
               <input type="text" v-model="clusterConfig.hosts" class="form-input" placeholder="192.168.1.10, 192.168.1.11">
               <small class="text-secondary">Comma separated list of Proxmox node IPs.</small>
             </div>
             <div class="form-group">
                 <label>Username</label>
                 <input type="text" v-model="clusterConfig.user" class="form-input" placeholder="root@pam">
             </div>
             <div class="form-group">
                 <label>API Token / Password</label>
                 <input type="password" v-model="clusterConfig.password" class="form-input" placeholder="Enter only to change">
             </div>
             <div class="form-group checkbox col-span-2 mt-2">
                  <label class="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox" v-model="clusterConfig.verify_ssl">
                      Verify SSL Certificate (Disable for self-signed)
                  </label>
             </div>
             <div class="form-group checkbox col-span-2">
                  <label class="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox" v-model="clusterConfig.is_default">
                      Set as Default Cluster
                  </label>
             </div>
           </div>
           
           <div class="mt-8 flex justify-end gap-2 border-t border-gray-700 pt-4">
               <button class="btn btn-secondary" @click="cancelEditCluster">Cancel</button>
               <button class="btn btn-primary" @click="saveCluster">💾 {{ editingClusterId ? 'Update Connection' : 'Create Connection' }}</button>
           </div>
        </div>
      </div>

      <!-- TOPOLOGY TAB -->
      <div v-if="activeTab === 'topology'" class="topology-panel" style="animation: fadeIn 0.3s ease;">
          <div v-if="loadingTopology" style="display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 80px 20px;">
             <div class="spinner-sm" style="width: 40px; height: 40px; border-width: 3px; margin-bottom: 16px;"></div>
             <h3 style="margin: 0 0 8px 0; font-size: 1.25rem;">Analyzing Network Topology...</h3>
             <p class="text-secondary" style="margin: 0;">Connecting to nodes and retrieving configuration</p>
          </div>
          
          <div v-else-if="topologyData">
              <!-- Corosync Status -->
              <div class="card" style="margin-bottom: 24px;">
                  <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--border-color);">
                       <span style="font-size: 1.5rem;">🔗</span>
                       <h4 style="margin: 0; font-size: 1.1rem;">Corosync Cluster Status</h4>
                  </div>
                  <div class="table-container">
                      <table class="data-table">
                          <thead>
                              <tr>
                                  <th>Node</th>
                                  <th v-for="i in [0, 1]" :key="i" style="text-align: center;">Ring {{ i }}</th>
                                  <th style="text-align: right;">Quorum Votes</th>
                              </tr>
                          </thead>
                          <tbody>
                              <tr v-for="(ringNode, name) in (topologyData.corosync?.rings || {})" :key="name">
                                  <td style="font-weight: 600;">{{ name }}</td>
                                  <td style="text-align: center;">
                                      <span v-if="ringNode.ring0_addr" class="badge badge-success">
                                          {{ ringNode.ring0_addr }}
                                      </span>
                                      <span v-else class="text-secondary">-</span>
                                  </td>
                                  <td style="text-align: center;">
                                      <span v-if="ringNode.ring1_addr" class="badge badge-success">
                                          {{ ringNode.ring1_addr }}
                                      </span>
                                      <span v-else class="text-secondary">-</span>
                                  </td>
                                  <td style="text-align: right; font-family: monospace;">{{ ringNode.quorum_votes || 1 }}</td>
                              </tr>
                          </tbody>
                      </table>
                  </div>
              </div>

              <!-- Network Map -->
              <div>
                  <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 16px;">
                      <span style="font-size: 1.5rem;">🕸️</span>
                      <h4 style="margin: 0; font-size: 1.1rem;">Network Map</h4>
                  </div>
                  
                  <div class="topology-grid">
                      <!-- CARD PER OGNI NODO -->
                      <div v-for="(nodeData, nodeName) in topologyData.nodes" :key="nodeName" class="topology-node-card">
                          <!-- Header Host -->
                          <div class="topology-node-header">
                              <div style="display: flex; align-items: center; gap: 12px;">
                                  <div class="topology-node-icon">🖥️</div>
                                  <div>
                                      <h3 style="margin: 0; font-size: 1.1rem; cursor: pointer; color: var(--accent);" 
                                          @click="navigateToNode(String(nodeName))"
                                          title="Click to view node details">{{ nodeName }}</h3>
                                      <span class="text-xs text-secondary">Proxmox Node</span>
                                  </div>
                              </div>
                              <span class="badge badge-success">Online</span>
                          </div>
                          
                          <div class="topology-node-content">
                              <!-- Physical Ports -->
                              <div class="topology-section">
                                  <h5 class="topology-section-title">🔌 Physical Interfaces</h5>
                                  <div class="topology-iface-list">
                                      <div v-for="iface in (nodeData || []).filter((i: any) => i.type === 'eth' || i.type === 'bond')" 
                                           :key="iface.iface" 
                                           class="topology-iface-chip"
                                           :class="{ active: iface.active }">
                                          <span class="iface-dot" :class="{ active: iface.active }"></span>
                                          {{ iface.iface }}
                                      </div>
                                  </div>
                              </div>

                              <!-- Bridges -->
                              <div class="topology-section">
                                  <h5 class="topology-section-title">🌉 Bridges & Virtual Machines</h5>
                                  <div class="topology-bridges-list">
                                      <div v-for="bridge in (nodeData || []).filter((i: any) => i.type === 'bridge')" 
                                           :key="bridge.iface" 
                                           class="topology-bridge-box">
                                          
                                          <!-- Bridge Header -->
                                          <div class="topology-bridge-header">
                                              <span class="bridge-name">{{ bridge.iface }}</span>
                                              <span class="bridge-cidr">{{ bridge.cidr || 'L2 Switch' }}</span>
                                          </div>
                                          
                                          <!-- Bridge Ports (Physical NICs) -->
                                          <div v-if="bridge.bridge_ports" class="bridge-ports-info">
                                              <span class="bridge-ports-label">Uplink:</span>
                                              <div class="bridge-ports-list">
                                                  <template v-for="port in bridge.bridge_ports.split(' ').filter((p: string) => p)" :key="port">
                                                      <div class="bridge-port-group">
                                                          <span class="bridge-port-chip" :class="{ bond: port.startsWith('bond') }">
                                                              {{ port }}
                                                              <span v-if="getBondMode(nodeData, port)" class="bond-mode-badge">
                                                                  {{ getBondMode(nodeData, port) }}
                                                              </span>
                                                          </span>
                                                          <!-- Show bond slaves if this is a bond -->
                                                          <div v-if="getBondSlaves(nodeData, port)" class="bond-slaves">
                                                              <span class="slaves-arrow">→</span>
                                                              <span v-for="slave in getBondSlaves(nodeData, port)" :key="slave" class="slave-nic">
                                                                  {{ slave }}
                                                              </span>
                                                          </div>
                                                      </div>
                                                  </template>
                                              </div>
                                          </div>

                                          <!-- Guests connected -->
                                          <div class="topology-guests">
                                              <div v-for="guest in getGuestsOnBridge(String(nodeName), bridge.iface)" 
                                                   :key="(guest as any).id" 
                                                   class="topology-guest-item clickable-guest"
                                                   :class="{ vm: (guest as any).type === 'vm', ct: (guest as any).type === 'ct' }"
                                                   @click="navigateToVM(guest)"
                                                   title="Click to view VM details">
                                                  <span class="guest-icon">{{ (guest as any).type === 'vm' ? '💻' : '📦' }}</span>
                                                  <div class="guest-info">
                                                      <strong style="color: var(--accent);">{{ (guest as any).name || (guest as any).id }}</strong>
                                                      <span class="guest-id">ID: {{ (guest as any).id }}</span>
                                                  </div>
                                                  <!-- VLAN tag -->
                                                  <span v-if="getGuestVlanOnBridge(guest, bridge.iface)" class="badge badge-purple" style="margin-left: auto; font-size: 0.7rem;">
                                                      VLAN {{ getGuestVlanOnBridge(guest, bridge.iface) }}
                                                  </span>
                                              </div>
                                              
                                              <div v-if="getGuestsOnBridge(String(nodeName), bridge.iface).length === 0" class="no-guests">
                                                  No guests connected
                                              </div>
                                          </div>
                                      </div>
                                  </div>
                              </div>
                          </div>
                      </div>
                  </div>
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
                            <h3 @click="navigateToNode(String(nodeName))" 
                                style="cursor: pointer; color: var(--accent);" 
                                title="Click to view node details">{{ nodeName }}</h3>
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
                                class="guest-chip clickable-guest"
                                :class="guest.type"
                                :title="getGuestTooltip(guest)"
                                @click="navigateToVM(guest)"
                                style="cursor: pointer;"
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
import { useRouter } from 'vue-router';
import { useHAStore } from '../stores/ha_store';
import loadBalancerService from '../services/loadBalancer';
import axios from 'axios';

const store = useHAStore();
const router = useRouter();
const activeTab = ref('monitor'); // Start on Monitor
const loading = computed(() => store.loading);

// --- Cluster Management State ---
interface ProxmoxCluster {
    id: number;
    name: string;
    hosts: string;
    api_user?: string;
    verify_ssl: boolean;
    is_default: boolean;
    is_initialized: boolean;
    cluster_name?: string;
    node_count?: number;
    quorum_ok?: boolean;
}

const clusters = ref<ProxmoxCluster[]>([]);
const selectedClusterId = ref<number | null>(null);
const isEditingCluster = ref(false);
const editingClusterId = ref<number | null>(null);

// Computed for current cluster (if managed via new API)
const currentCluster = computed(() => {
    return clusters.value.find(c => c.id === selectedClusterId.value);
});

// API Config State for "Config" tab (legacy + new form)
const clusterConfig = reactive({
    name: '',
    hosts: '',
    user: '',
    password: '',
    verify_ssl: false,
    is_default: false
});

// --- Existing Monitor State ---
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

// --- Topology State ---
const topologyData = ref<any>(null);
const loadingTopology = ref(false);

const loadTopology = async () => {
    loadingTopology.value = true;
    try {
        const nodeId = await getFirstPVENodeId();
        if(!nodeId) return;
        
        const token = localStorage.getItem('access_token');
        const res = await fetch(`/api/ha/node/${nodeId}/topology`, { 
            headers: { 'Authorization': `Bearer ${token}` } 
        });
        
        if (res.ok) {
            topologyData.value = await res.json();
        }
    } catch (e) {
        console.error("Topology load failed", e);
    } finally {
        loadingTopology.value = false;
    }
};

watch(activeTab, (val) => {
    if (val === 'topology' && (!topologyData.value || clusters.value.length > 0)) { // Reload if switching
        loadTopology();
    }
});

// Helper to get guests for a bridge on a specific node
const getGuestsOnBridge = (nodeName: string, bridge: string) => {
    if (!topologyData.value || !topologyData.value.guests) return [];
    
    // Normalize bridge name
    const targetBridge = bridge ? bridge.trim() : '';
    
    return Object.values(topologyData.value.guests).filter((g: any) => {
        if (!g.networks) return false;
        return g.node === nodeName && g.networks.some((n: any) => (n.bridge && n.bridge.trim()) === targetBridge);
    });
};

// Helper to get VLAN tag for a guest on a specific bridge
const getGuestVlanOnBridge = (guest: any, bridge: string) => {
    if (!guest || !guest.networks) return null;
    const targetBridge = bridge ? bridge.trim() : '';
    const netEntry = guest.networks.find((n: any) => n.bridge && n.bridge.trim() === targetBridge);
    return netEntry?.tag || null;
};

// Navigation: Click on node name -> open Node Info modal
const navigateToNode = (nodeName: string) => {
    router.push({ path: '/nodes', query: { openInfo: nodeName } });
};

// Navigation: Click on VM/CT -> open VM details modal
const navigateToVM = (guest: any) => {
    if (!guest) return;
    const vmid = guest.id || guest.vmid;
    const vmType = guest.type === 'ct' || guest.type === 'lxc' ? 'lxc' : 'qemu';
    router.push({ path: '/vms', query: { openVm: String(vmid), type: vmType } });
};

// Helper to get bond mode for a port (if it's a bond interface)
const getBondMode = (nodeInterfaces: any[], portName: string) => {
    if (!nodeInterfaces || !portName.startsWith('bond')) return null;
    
    const bondIface = nodeInterfaces.find((i: any) => i.iface === portName && i.type === 'bond');
    if (!bondIface || !bondIface.bond_mode) return null;
    
    // Map bond mode to human-readable name
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

// Helper to get bond slave interfaces
const getBondSlaves = (nodeInterfaces: any[], portName: string): string[] | null => {
    if (!nodeInterfaces || !portName.startsWith('bond')) return null;
    
    const bondIface = nodeInterfaces.find((i: any) => i.iface === portName && i.type === 'bond');
    if (!bondIface) return null;
    
    // Proxmox uses 'slaves' field for bond interfaces
    if (bondIface.slaves) {
        return bondIface.slaves.split(' ').filter((s: string) => s.trim());
    }
    
    // Alternative: bond_slaves or bond-slaves
    if (bondIface.bond_slaves) {
        return bondIface.bond_slaves.split(' ').filter((s: string) => s.trim());
    }
    
    return null;
};

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

// --- Cluster Management Functions ---

const fetchClusters = async () => {
    try {
        const res = await axios.get('/api/clusters');
        clusters.value = res.data;
        
        // Auto-select logic
        if (clusters.value.length > 0) {
            // Check if current selection is still valid
            const exists = selectedClusterId.value && clusters.value.find(c => c.id === selectedClusterId.value);
            
            if (!exists) {
                // Select default or first
                const def = clusters.value.find(c => c.is_default);
                selectedClusterId.value = def ? def.id : clusters.value[0].id;
            }
        } else {
            selectedClusterId.value = null;
        }
    } catch (e) {
        console.error("Failed to fetch clusters", e);
    }
};

const selectCluster = (id: number) => {
    selectedClusterId.value = id;
    // Tell store to use this cluster context
    // We assume the store has been updated to accept cluster ID, or we pass it
    // For now, we set a property on the store instance if possible, or just rely on backend using default if not passed
    // Ideally: store.setClusterId(id);
    refreshAll();
};

const startEditCluster = (cluster?: ProxmoxCluster) => {
    if (cluster) {
        editingClusterId.value = cluster.id;
        clusterConfig.name = cluster.name;
        clusterConfig.hosts = cluster.hosts;
        clusterConfig.user = cluster.api_user || '';
        clusterConfig.password = ''; // Don't show password
        clusterConfig.verify_ssl = cluster.verify_ssl;
        clusterConfig.is_default = cluster.is_default;
        isEditingCluster.value = true;
    } else {
        editingClusterId.value = null;
        clusterConfig.name = '';
        clusterConfig.hosts = '';
        clusterConfig.user = 'root@pam';
        clusterConfig.password = '';
        clusterConfig.verify_ssl = false;
        clusterConfig.is_default = clusters.value.length === 0;
        isEditingCluster.value = true;
    }
};

const cancelEditCluster = () => {
    isEditingCluster.value = false;
    editingClusterId.value = null;
};

const saveCluster = async () => {
    const payload: any = {
        name: clusterConfig.name,
        hosts: clusterConfig.hosts,
        api_user: clusterConfig.user,
        verify_ssl: clusterConfig.verify_ssl,
        is_default: clusterConfig.is_default
    };
    
    if (clusterConfig.password) {
        payload.api_password = clusterConfig.password;
    }
    
    try {
        if (editingClusterId.value) {
            await axios.put(`/api/clusters/${editingClusterId.value}`, payload);
        } else {
            await axios.post('/api/clusters', payload);
        }
        await fetchClusters();
        isEditingCluster.value = false;
        editingClusterId.value = null;
    } catch (e: any) {
        console.error("Failed to save cluster", e);
        const msg = e.response?.data?.detail || e.message;
        alert("Failed to save cluster: " + msg);
    }
};

const deleteCluster = async (id: number) => {
    if (!confirm("Sei sicuro di voler eliminare questa configurazione cluster?\n\nI nodi Proxmox e le sincronizzazioni NON verranno toccati.\nVerrà rimossa solo la connessione per il monitoraggio e HA.")) return;
    try {
        await axios.delete(`/api/clusters/${id}`);
        await fetchClusters();
    } catch (e) {
        console.error("Failed to delete cluster", e);
    }
};

// --- CONFIG ACTIONS REPLACED BY MULTI-CLUSTER ---
// Old loadClusterConfig/saveClusterConfig removed.

const refreshAll = async () => {
    // If we have selected cluster, we might want to pass it
    await store.fetchHAData(true);
    if(activeTab.value === 'config') {
        await fetchClusters();
    }
    if(activeTab.value === 'monitor') await loadMonitorData();
};

onMounted(async () => {
    await fetchClusters();
    store.fetchHAData();
    loadMonitorData();
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

/* Network Topology - New Styles */
.topology-panel { padding: 16px; }

.topology-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 20px;
}

.topology-node-card {
    background: var(--bg-surface);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
}

.topology-node-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border-color);
}

.topology-node-icon {
    width: 40px;
    height: 40px;
    border-radius: 8px;
    background: rgba(59, 130, 246, 0.15);
    border: 1px solid rgba(59, 130, 246, 0.2);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.25rem;
}

.topology-node-content {
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 20px;
}

.topology-section {}

.topology-section-title {
    font-size: 0.75rem;
    text-transform: uppercase;
    color: var(--text-secondary);
    font-weight: 600;
    margin: 0 0 12px 0;
    letter-spacing: 0.05em;
}

.topology-iface-list {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}

.topology-iface-chip {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    font-size: 0.8rem;
    font-family: var(--font-mono);
}

.topology-iface-chip.active {
    background: rgba(16, 185, 129, 0.1);
    border-color: rgba(16, 185, 129, 0.3);
    color: #34d399;
}

.iface-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--text-tertiary);
}

.iface-dot.active {
    background: #10b981;
    box-shadow: 0 0 6px #10b981;
}

.topology-bridges-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.topology-bridge-box {
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    overflow: hidden;
}

.topology-bridge-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 12px;
    background: rgba(0,0,0,0.2);
    border-bottom: 1px solid var(--border-color);
}

.bridge-name {
    font-family: var(--font-mono);
    font-weight: 600;
    font-size: 0.9rem;
    color: #fbbf24;
}

.bridge-cidr {
    font-size: 0.7rem;
    padding: 2px 6px;
    background: var(--bg-body);
    border-radius: 4px;
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
}

.bridge-ports-info {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: rgba(0,0,0,0.15);
    border-bottom: 1px solid var(--border-color);
    flex-wrap: wrap;
}

.bridge-ports-label {
    font-size: 0.7rem;
    color: var(--text-tertiary);
    text-transform: uppercase;
    font-weight: 600;
}

.bridge-ports-list {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}

.bridge-port-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 8px;
    font-size: 0.75rem;
    font-family: var(--font-mono);
    background: var(--bg-body);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    color: var(--text-secondary);
}

.bridge-port-chip.bond {
    background: rgba(59, 130, 246, 0.1);
    border-color: rgba(59, 130, 246, 0.3);
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

.bridge-port-group {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 4px;
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
    margin: 0 2px;
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
    transition: border-color 0.2s;
}

.topology-guest-item:hover {
    border-color: var(--accent-primary);
}

.topology-guest-item.vm { border-left: 3px solid #3b82f6; }
.topology-guest-item.ct { border-left: 3px solid #a855f7; }

.guest-icon {
    font-size: 1rem;
    opacity: 0.8;
}

.guest-info {
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex: 1;
    min-width: 0;
}

.guest-info strong {
    font-size: 0.85rem;
    color: var(--text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.guest-id {
    font-size: 0.7rem;
    color: var(--text-tertiary);
}

.no-guests {
    font-size: 0.8rem;
    color: var(--text-tertiary);
    text-align: center;
    padding: 12px;
    font-style: italic;
}

.node-footer { margin-top: 12px; border-top: 1px solid var(--border-color); padding-top: 12px; display: flex; justify-content: space-between; align-items: center; font-size: 0.8rem; color: var(--text-secondary); }
.guest-counts { display: flex; gap: 8px; }
.guest-badge { padding: 2px 6px; border-radius: 4px; background: var(--bg-secondary); border: 1px solid var(--border-color); }
.guest-badge.vm { color: #3b82f6; }
.guest-badge.ct { color: #a855f7; }
</style>
