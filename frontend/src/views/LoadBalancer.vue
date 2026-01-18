
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
            :class="{ active: activeTab === 'history' }" 
            @click="activeTab = 'history'; loadMigrationHistory()">
            📜 History
        </button>
        <button 
            class="tab-btn" 
            :class="{ active: activeTab === 'map' }" 
            @click="activeTab = 'map'">
            🗺️ Cluster Map
        </button>
        <button 
            class="tab-btn" 
            :class="{ active: activeTab === 'guests' }" 
            @click="activeTab = 'guests'">
            🧠 VM/CT Manager
        </button>
        <button 
            class="tab-btn" 
            :class="{ active: activeTab === 'ha' }" 
            @click="activeTab = 'ha'; loadHAData()">
            🛡️ HA Manager
        </button>
        <button 
            class="tab-btn" 
            :class="{ active: activeTab === 'cluster' }" 
            @click="activeTab = 'cluster'; loadClusterData()">
            🖥️ Cluster
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
                
                <!-- Auto-refresh controls -->
                <div class="auto-refresh-controls">
                    <label class="toggle-label">
                        <input type="checkbox" v-model="autoRefreshEnabled" @change="toggleAutoRefresh">
                        <span class="toggle-switch"></span>
                        Auto-refresh
                    </label>
                    <select v-model="autoRefreshInterval" class="interval-select" :disabled="!autoRefreshEnabled">
                        <option :value="10">10s</option>
                        <option :value="30">30s</option>
                        <option :value="60">60s</option>
                        <option :value="120">2m</option>
                    </select>
                    <span v-if="autoRefreshEnabled && countdown > 0" class="countdown">
                        ⏱️ {{ countdown }}s
                    </span>
                </div>
                
                <span v-if="lastAnalysis" class="last-update">
                    Last update: {{ lastUpdateTime }}
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

        <!-- History Tab -->
        <div v-if="activeTab === 'history'" class="history-panel">
            <div class="control-bar">
                <button class="btn btn-primary" @click="loadMigrationHistory" :disabled="historyLoading">
                    <span v-if="historyLoading" class="spinner-sm"></span>
                    {{ historyLoading ? 'Loading...' : '🔄 Refresh' }}
                </button>
                <span class="history-count" v-if="migrationHistory.length > 0">
                    {{ migrationHistory.length }} migrations
                </span>
            </div>

            <div v-if="migrationHistory.length === 0 && !historyLoading" class="empty-state">
                <p>📜 No migration history yet. Migrations performed via ProxLB will appear here.</p>
            </div>

            <div v-else class="history-table-wrapper">
                <table class="data-table history-table">
                    <thead>
                        <tr>
                            <th>Date</th>
                            <th>Guest</th>
                            <th>From</th>
                            <th>To</th>
                            <th>Reason</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="mig in migrationHistory" :key="mig.id" :class="'status-' + mig.status">
                            <td class="date-col">
                                {{ formatDate(mig.proposed_at) }}
                            </td>
                            <td>
                                <span class="guest-badge" :class="mig.guest_type">{{ mig.guest_type }}</span>
                                {{ mig.guest_name || mig.guest_id }}
                            </td>
                            <td>{{ mig.source_node }}</td>
                            <td>{{ mig.target_node }}</td>
                            <td class="reason-col">{{ mig.reason || '-' }}</td>
                            <td>
                                <span class="status-badge" :class="mig.status">
                                    {{ getStatusIcon(mig.status) }} {{ mig.status }}
                                </span>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Cluster Map Tab -->
        <div v-if="activeTab === 'map'" class="map-panel">
            <div class="control-bar">
                <button class="btn btn-primary" @click="runAnalysis" :disabled="loading">
                    <span v-if="loading" class="spinner-sm"></span>
                    {{ loading ? 'Loading...' : '🔄 Refresh Map' }}
                </button>
                <div class="map-legend">
                    <span class="legend-item"><span class="legend-dot healthy"></span> Healthy</span>
                    <span class="legend-item"><span class="legend-dot warning"></span> High Load</span>
                    <span class="legend-item"><span class="legend-dot critical"></span> Critical</span>
                </div>
            </div>

            <div v-if="!lastAnalysis" class="empty-state">
                <p>🗺️ Click "Refresh Map" to load cluster visualization</p>
            </div>

            <div v-else class="cluster-map">
                <div 
                    v-for="(node, nodeName) in lastAnalysis.nodes" 
                    :key="nodeName" 
                    class="map-node"
                    :class="getNodeHealthClass(node)"
                >
                    <div class="map-node-header">
                        <h3 class="map-node-name">🖥️ {{ nodeName }}</h3>
                        <span class="map-node-status" :class="getNodeStatusClass(node)">
                            {{ getNodeStatus(node) }}
                        </span>
                    </div>
                    
                    <div class="map-node-metrics">
                        <div class="map-metric">
                            <span class="map-metric-label">CPU</span>
                            <div class="map-metric-bar">
                                <div 
                                    class="map-metric-fill"
                                    :class="getProgressClass(node.cpu_used_percent)"
                                    :style="{ width: (node.cpu_used_percent || 0) + '%' }"
                                ></div>
                            </div>
                            <span class="map-metric-value">{{ formatPercentDirect(node.cpu_used_percent) }}</span>
                        </div>
                        <div class="map-metric">
                            <span class="map-metric-label">MEM</span>
                            <div class="map-metric-bar">
                                <div 
                                    class="map-metric-fill"
                                    :class="getProgressClass(node.memory_used_percent)"
                                    :style="{ width: (node.memory_used_percent || 0) + '%' }"
                                ></div>
                            </div>
                            <span class="map-metric-value">{{ formatPercentDirect(node.memory_used_percent) }}</span>
                        </div>
                    </div>
                    
                    <div class="map-guests-container">
                        <div class="map-guests-header">
                            <span>{{ getGuestsForNode(nodeName).length }} Guests</span>
                        </div>
                        <div class="map-guests-grid">
                            <div 
                                v-for="guest in getGuestsForNode(nodeName).slice(0, 20)" 
                                :key="guest.id"
                                class="map-guest"
                                :class="guest.type"
                                :title="getGuestTooltip(guest)"
                            >
                                <span class="map-guest-type">{{ guest.type === 'vm' ? '🖥' : '📦' }}</span>
                                <span class="map-guest-id">{{ guest.id }}</span>
                            </div>
                            <div 
                                v-if="getGuestsForNode(nodeName).length > 20" 
                                class="map-guest more"
                            >
                                +{{ getGuestsForNode(nodeName).length - 20 }}
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Map Summary -->
            <div v-if="lastAnalysis" class="map-summary">
                <div class="map-summary-item">
                    <span class="map-summary-icon">🖥️</span>
                    <span class="map-summary-value">{{ Object.keys(lastAnalysis.nodes || {}).length }}</span>
                    <span class="map-summary-label">Nodes</span>
                </div>
                <div class="map-summary-item">
                    <span class="map-summary-icon">💻</span>
                    <span class="map-summary-value">{{ totalVMs }}</span>
                    <span class="map-summary-label">VMs</span>
                </div>
                <div class="map-summary-item">
                    <span class="map-summary-icon">📦</span>
                    <span class="map-summary-value">{{ totalCTs }}</span>
                    <span class="map-summary-label">Containers</span>
                </div>
                <div class="map-summary-item">
                    <span class="map-summary-icon">⚖️</span>
                    <span class="map-summary-value" :class="getScoreClass(balanciness)">{{ balanciness }}%</span>
                    <span class="map-summary-label">Imbalance</span>
                </div>
            </div>
        </div>

        <!-- Guest Manager Tab -->
        <div v-if="activeTab === 'guests'" class="guests-panel">
            <div class="control-bar">
                <button class="btn btn-primary" @click="runAnalysis" :disabled="loading">
                    <span v-if="loading" class="spinner-sm"></span>
                    {{ loading ? 'Reloading...' : '🔄 Refresh List' }}
                </button>
                
                <div class="search-box">
                    <span class="search-icon">🔍</span>
                    <input 
                        type="text" 
                        v-model="guestSearch" 
                        placeholder="Search guests..." 
                        class="search-input"
                    >
                </div>

                <select v-model="guestTypeFilter" class="filter-select">
                    <option value="all">All Types</option>
                    <option value="vm">Virtual Machines</option>
                    <option value="ct">Containers</option>
                </select>

                <select v-model="guestNodeFilter" class="filter-select">
                    <option value="all">All Nodes</option>
                    <option v-for="node in availableNodes" :key="node" :value="node">
                        {{ node }}
                    </option>
                </select>
            </div>

            <div v-if="selectedGuests.length > 0" class="bulk-actions-bar">
                <span class="selection-count">{{ selectedGuests.length }} selected</span>
                <div class="bulk-buttons">
                    <button class="btn btn-warning btn-sm" @click="bulkIgnoreGuests(true)">
                        🚫 Ignore Selected
                    </button>
                    <button class="btn btn-success btn-sm" @click="bulkIgnoreGuests(false)">
                        ✅ Include Selected
                    </button>
                    <button class="btn btn-secondary btn-sm" @click="bulkUnlockGuests">
                        🔓 Unlock Selected
                    </button>
                </div>
                <button class="btn-text" @click="selectedGuests = []">Clear Selection</button>
            </div>

            <div class="table-wrapper">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th class="col-checkbox">
                                <input 
                                    type="checkbox" 
                                    :checked="isAllSelected" 
                                    @change="toggleSelectAll"
                                >
                            </th>
                            <th>Status</th>
                            <th>ID</th>
                            <th>Name</th>
                            <th>Type</th>
                            <th>Node</th>
                            <th>CPU</th>
                            <th>RAM</th>
                            <th>Disk</th>
                            <th>Ignored</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="guest in filteredGuests" :key="guest.id" :class="{ 'row-ignored': isGuestIgnored(guest.id) }">
                            <td class="col-checkbox">
                                <input 
                                    type="checkbox" 
                                    v-model="selectedGuests" 
                                    :value="guest.id"
                                >
                            </td>
                            <td>
                                <span class="status-dot" :class="guest.status"></span>
                            </td>
                            <td class="font-mono">{{ guest.id }}</td>
                            <td class="font-bold">{{ guest.name || '-' }}</td>
                            <td>
                                <span class="guest-badge" :class="guest.type">{{ guest.type }}</span>
                            </td>
                            <td>{{ guest.node_current }}</td>
                            <td class="mono-text">
                                <div class="metric-cell">
                                    <span>{{ formatPercent(guest.cpu_used || 0) }}</span>
                                    <span class="sub-metric">{{ guest.cpu_total }} C</span>
                                </div>
                            </td>
                            <td class="mono-text">
                                <div class="metric-cell">
                                    <span>{{ formatBytes(guest.memory_used || 0) }}</span>
                                    <span class="sub-metric">/ {{ formatBytes(guest.memory_total || 0) }}</span>
                                </div>
                            </td>
                            <td class="mono-text">
                                <div class="metric-cell">
                                    <span>{{ formatBytes(guest.disk_used || 0) }}</span>
                                    <span class="sub-metric">/ {{ formatBytes(guest.disk_total || 0) }}</span>
                                </div>
                            </td>
                            <td>
                                <span v-if="isGuestIgnored(guest.id)" class="badge-ignored">IGNORED</span>
                                <span v-else class="text-muted">-</span>
                            </td>
                        </tr>
                        <tr v-if="filteredGuests.length === 0">
                            <td colspan="9" class="text-center py-4">
                                No guests found matching filters.
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- HA Manager Tab -->
        <div v-if="activeTab === 'ha'" class="ha-panel">
            <div class="section-header">
                <h3>🛡️ High Availability Manager</h3>
                <button class="btn btn-sm btn-primary" @click="loadHAData" :disabled="loading">
                    🔄 Refresh
                </button>
            </div>

            <div v-if="haLoading" class="loading-indicator">
                <span class="spinner-sm"></span> Loading HA data...
            </div>

            <!-- HA Resources -->
            <div class="card mt-3">
                <h4>HA Managed Resources</h4>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>SID</th>
                            <th>Type</th>
                            <th>State</th>
                            <th>Group</th>
                            <th>Max Restart</th>
                            <th>Max Relocate</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="res in haResources" :key="res.sid">
                            <td><strong>{{ res.sid }}</strong></td>
                            <td>
                                <span :class="res.type === 'vm' ? 'badge-success' : 'badge-info'">
                                    {{ res.type?.toUpperCase() }}
                                </span>
                            </td>
                            <td>
                                <span :class="getHAStateClass(res.state)">
                                    {{ res.state }}
                                </span>
                            </td>
                            <td>{{ res.group || '-' }}</td>
                            <td>{{ res.max_restart || 1 }}</td>
                            <td>{{ res.max_relocate || 1 }}</td>
                            <td>
                                <button class="btn btn-xs btn-danger" @click="removeFromHA(res)">
                                    ❌ Remove
                                </button>
                            </td>
                        </tr>
                        <tr v-if="haResources.length === 0">
                            <td colspan="7" class="text-center py-4">
                                No HA resources configured. Add VMs to HA from the VM/CT Manager.
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- HA Groups -->
            <div class="card mt-3">
                <h4>HA Groups</h4>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Group Name</th>
                            <th>Nodes</th>
                            <th>Restricted</th>
                            <th>No Failback</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="grp in haGroups" :key="grp.group">
                            <td><strong>{{ grp.group }}</strong></td>
                            <td>{{ grp.nodes }}</td>
                            <td>{{ grp.restricted ? '✅' : '❌' }}</td>
                            <td>{{ grp.nofailback ? '✅' : '❌' }}</td>
                            <td>
                                <button class="btn btn-xs btn-danger" @click="deleteHAGroup(grp.group)">
                                    🗑️ Delete
                                </button>
                            </td>
                        </tr>
                        <tr v-if="haGroups.length === 0">
                            <td colspan="5" class="text-center py-4">
                                No HA groups configured.
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Cluster Tab -->
        <div v-if="activeTab === 'cluster'" class="cluster-panel">
            <div class="section-header">
                <h3>🖥️ Cluster Node Management</h3>
                <button class="btn btn-sm btn-primary" @click="loadClusterData" :disabled="loading">
                    🔄 Refresh
                </button>
            </div>

            <div v-if="clusterLoading" class="loading-indicator">
                <span class="spinner-sm"></span> Loading cluster data...
            </div>

            <!-- Cluster Status -->
            <div class="card mt-3" v-if="clusterStatus">
                <h4>Cluster Status</h4>
                <div class="cluster-status-grid">
                    <div class="status-item">
                        <span class="label">Cluster Name:</span>
                        <strong>{{ clusterStatus.cluster_name || 'N/A' }}</strong>
                    </div>
                    <div class="status-item">
                        <span class="label">Quorum:</span>
                        <span :class="clusterStatus.quorum ? 'badge-success' : 'badge-danger'">
                            {{ clusterStatus.quorum ? '✅ YES' : '❌ NO' }}
                        </span>
                    </div>
                    <div class="status-item">
                        <span class="label">Expected Votes:</span>
                        <strong>{{ clusterStatus.expected_votes || 0 }}</strong>
                    </div>
                    <div class="status-item">
                        <span class="label">Total Votes:</span>
                        <strong>{{ clusterStatus.total_votes || 0 }}</strong>
                    </div>
                </div>
            </div>

            <!-- Cluster Nodes -->
            <div class="card mt-3">
                <h4>Cluster Nodes</h4>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Node ID</th>
                            <th>Name</th>
                            <th>Votes</th>
                            <th>Status</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="node in clusterNodes" :key="node.node_id">
                            <td>{{ node.node_id }}</td>
                            <td>
                                <strong>{{ node.name }}</strong>
                                <span v-if="node.is_local" class="badge-info ml-1">LOCAL</span>
                            </td>
                            <td>{{ node.votes }}</td>
                            <td>
                                <span :class="node.status === 'online' ? 'badge-success' : 'badge-danger'">
                                    {{ node.status?.toUpperCase() }}
                                </span>
                            </td>
                            <td>
                                <button 
                                    class="btn btn-xs btn-warning" 
                                    @click="cleanNodeReferences(node.name)"
                                    title="Clean leftover references">
                                    🧹 Clean
                                </button>
                                <button 
                                    class="btn btn-xs btn-danger" 
                                    @click="removeNodeFromCluster(node.name)"
                                    :disabled="node.is_local"
                                    title="Remove node from cluster (must be offline)">
                                    ❌ Remove
                                </button>
                            </td>
                        </tr>
                        <tr v-if="clusterNodes.length === 0">
                            <td colspan="5" class="text-center py-4">
                                No cluster nodes found or not in a cluster.
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- Add Node Panel -->
            <div class="card mt-3">
                <h4>➕ Add New Node</h4>
                <div class="form-grid">
                    <div class="form-group">
                        <label>New Node IP</label>
                        <input type="text" v-model="newNodeIP" class="form-input" placeholder="192.168.1.100">
                    </div>
                    <div class="form-group">
                        <label>Link0 (optional)</label>
                        <input type="text" v-model="newNodeLink0" class="form-input" placeholder="Primary network IP">
                    </div>
                    <div class="form-group">
                        <label>Link1 (optional)</label>
                        <input type="text" v-model="newNodeLink1" class="form-input" placeholder="Secondary network IP">
                    </div>
                </div>
                <button class="btn btn-primary mt-2" @click="addNodeToCluster" :disabled="!newNodeIP">
                    ➕ Add Node to Cluster
                </button>
                <p class="help-text mt-2">⚠️ The new node must have Proxmox installed and SSH access configured.</p>
            </div>
        </div>

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
import { ref, onMounted, onUnmounted, computed, reactive, watch } from 'vue';
import loadBalancerService from '../services/loadBalancer';

const activeTab = ref('analysis');
const loading = ref(false);
const executing = ref(false);
const error = ref<string | null>(null);
const lastAnalysis = ref<any>(null);
const configJson = ref('{}');
const executionLog = ref<string[]>([]);
const showJsonPreview = ref(false);

// Auto-refresh state
const autoRefreshEnabled = ref(false);
const autoRefreshInterval = ref(30); // seconds
const countdown = ref(0);
const lastUpdateTime = ref('');
let autoRefreshTimer: ReturnType<typeof setInterval> | null = null;
let countdownTimer: ReturnType<typeof setInterval> | null = null;

// Migration History state
const migrationHistory = ref<any[]>([]);
const historyLoading = ref(false);

// Load migration history
const loadMigrationHistory = async () => {
    historyLoading.value = true;
    try {
        const res = await loadBalancerService.getMigrationHistory(100);
        migrationHistory.value = res.data || [];
    } catch (e) {
        console.error('Failed to load migration history:', e);
        migrationHistory.value = [];
    } finally {
        historyLoading.value = false;
    }
};

// Format date for display
const formatDate = (dateStr: string) => {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleString();
};

// Get status icon
const getStatusIcon = (status: string) => {
    const icons: Record<string, string> = {
        'proposed': '📝',
        'executing': '⏳',
        'completed': '✅',
        'failed': '❌',
        'skipped': '⏭️'
    };
    return icons[status] || '❓';
};

// Cluster Map helpers
const getGuestsForNode = (nodeName: string) => {
    if (!lastAnalysis.value || !lastAnalysis.value.guests) return [];
    const guests = lastAnalysis.value.guests;
    const nodeGuests: any[] = [];
    for (const id in guests) {
        const guest = guests[id];
        if (guest.node_current === nodeName) {
            nodeGuests.push({ ...guest, id });
        }
    }
    return nodeGuests.sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));
};

const getGuestTooltip = (guest: any) => {
    const name = guest.name || guest.id;
    const type = guest.type === 'vm' ? 'VM' : 'Container';
    const cpu = guest.cpu_allocated ? `CPU: ${guest.cpu_allocated}` : '';
    const mem = guest.memory_allocated ? `RAM: ${(guest.memory_allocated / (1024*1024*1024)).toFixed(1)}GB` : '';
    return `${type} ${guest.id}: ${name}\n${cpu} ${mem}`.trim();
};

// Guest Manager State
const guestSearch = ref('');
const guestTypeFilter = ref('all');
const guestNodeFilter = ref('all');
const selectedGuests = ref<string[]>([]);

// Computed Guests for Manager
const availableNodes = computed(() => {
    if (!lastAnalysis.value || !lastAnalysis.value.nodes) return [];
    return Object.keys(lastAnalysis.value.nodes).sort();
});

const filteredGuests = computed(() => {
    if (!lastAnalysis.value || !lastAnalysis.value.guests) return [];
    
    let guests = Object.values(lastAnalysis.value.guests) as any[];

    // Search filter
    if (guestSearch.value) {
        const query = guestSearch.value.toLowerCase();
        guests = guests.filter(g => 
            (g.name && g.name.toLowerCase().includes(query)) || 
            (g.id && g.id.toString().includes(query))
        );
    }

    // Type filter
    if (guestTypeFilter.value !== 'all') {
        guests = guests.filter(g => g.type === guestTypeFilter.value);
    }

    // Node filter
    if (guestNodeFilter.value !== 'all') {
        guests = guests.filter(g => g.node_current === guestNodeFilter.value);
    }

    // Sort by ID
    return guests.sort((a, b) => parseInt(a.id) - parseInt(b.id));
});

const isAllSelected = computed(() => {
    return filteredGuests.value.length > 0 && selectedGuests.value.length === filteredGuests.value.length;
});

const toggleSelectAll = () => {
    if (isAllSelected.value) {
        selectedGuests.value = [];
    } else {
        selectedGuests.value = filteredGuests.value.map(g => g.id);
    }
};

const isGuestIgnored = (guestId: string) => {
    return ignoredGuestIds.value.includes(guestId);
};

const bulkIgnoreGuests = async (ignore: boolean) => {
    if (selectedGuests.value.length === 0) return;
    
    // Sync with ignoredGuestIds
    const currentIgnored = new Set(ignoredGuestIds.value);
    
    selectedGuests.value.forEach(id => {
        if (ignore) {
            currentIgnored.add(id);
        } else {
            currentIgnored.delete(id);
        }
    });
    
    ignoredGuestIds.value = Array.from(currentIgnored);
    // Config will be updated in saveConfiguration using ignoredGuestIds.value
    
    loading.value = true;
    try {
        await saveConfiguration();
        // Clear selection after success
        selectedGuests.value = [];
    } finally {
        loading.value = false;
    }
};

// Unlock locked VMs/CTs (ported from ProxmoxScripts/BulkUnlock.sh)
const bulkUnlockGuests = async () => {
    if (selectedGuests.value.length === 0) return;
    
    // Find node for each guest and group by node
    const guestsByNode = new Map<string, number[]>();
    
    allGuests.value.forEach(g => {
        if (selectedGuests.value.includes(g.id)) {
            const node = g.node_current;
            if (!guestsByNode.has(node)) {
                guestsByNode.set(node, []);
            }
            // Extract numeric ID from string
            const numId = parseInt(g.id, 10);
            if (!isNaN(numId)) {
                guestsByNode.get(node)!.push(numId);
            }
        }
    });
    
    loading.value = true;
    try {
        let totalSuccess = 0;
        let totalFailed = 0;
        
        for (const [nodeName, guestIds] of guestsByNode) {
            // Ensure we have registered nodes loaded
            if (registeredNodes.value.length === 0) {
                await fetchRegisteredNodes();
            }
            
            // Find node_id from registered nodes
            const node = registeredNodes.value?.find(n => n.name === nodeName);
            if (!node) {
                console.warn(`Node ${nodeName} not found in registered nodes`);
                totalFailed += guestIds.length;
                continue;
            }
            
            // Call bulk unlock API with auth
            const token = localStorage.getItem('token');
            const response = await fetch(`/api/vms/node/${node.id}/bulk-unlock`, {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({ guest_ids: guestIds })
            });
            
            if (response.ok) {
                const result = await response.json();
                totalSuccess += result.success?.length || 0;
                totalFailed += result.failed?.length || 0;
            } else {
                totalFailed += guestIds.length;
            }
        }
        
        if (totalSuccess > 0) {
            alert(`Unlocked ${totalSuccess} guests${totalFailed > 0 ? `, ${totalFailed} failed` : ''}`);
        } else if (totalFailed > 0) {
            alert(`Failed to unlock ${totalFailed} guests`);
        }
        
        selectedGuests.value = [];
    } catch (err) {
        console.error('Bulk unlock error:', err);
        alert('Error during bulk unlock');
    } finally {
        loading.value = false;
    }
};

// ========== HA & Cluster Management ==========
const haResources = ref<any[]>([]);
const haGroups = ref<any[]>([]);
const haLoading = ref(false);
const clusterStatus = ref<any>(null);
const clusterNodes = ref<any[]>([]);
const clusterLoading = ref(false);
const newNodeIP = ref('');
const newNodeLink0 = ref('');
const newNodeLink1 = ref('');

// Registered nodes from DB for API calls
const registeredNodes = ref<any[]>([]);

// Fetch registered nodes from database
const fetchRegisteredNodes = async () => {
    try {
        const token = localStorage.getItem('token');
        const res = await fetch('/api/nodes', {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (res.ok) {
            registeredNodes.value = await res.json();
        }
    } catch (err) {
        console.error('Error fetching registered nodes:', err);
    }
};

// Get first available PVE node ID for API calls
const getFirstPVENodeId = async () => {
    // Ensure we have nodes loaded
    if (registeredNodes.value.length === 0) {
        await fetchRegisteredNodes();
    }
    
    if (registeredNodes.value.length > 0) {
        const pveNode = registeredNodes.value.find(n => n.type === 'pve' || n.node_type === 'pve');
        return pveNode?.id || registeredNodes.value[0].id;
    }
    return null;
};

const loadHAData = async () => {
    const nodeId = await getFirstPVENodeId();
    if (!nodeId) {
        console.warn('No PVE node available for HA data');
        return;
    }
    
    haLoading.value = true;
    const token = localStorage.getItem('token');
    try {
        const [resourcesRes, groupsRes] = await Promise.all([
            fetch(`/api/ha/node/${nodeId}/resources`, {
                headers: { 'Authorization': `Bearer ${token}` }
            }),
            fetch(`/api/ha/node/${nodeId}/groups`, {
                headers: { 'Authorization': `Bearer ${token}` }
            })
        ]);
        
        if (resourcesRes.ok) {
            haResources.value = await resourcesRes.json();
        }
        if (groupsRes.ok) {
            haGroups.value = await groupsRes.json();
        }
    } catch (err) {
        console.error('Error loading HA data:', err);
    } finally {
        haLoading.value = false;
    }
};

const loadClusterData = async () => {
    const nodeId = await getFirstPVENodeId();
    if (!nodeId) {
        console.warn('No PVE node available for cluster data');
        return;
    }
    
    clusterLoading.value = true;
    const token = localStorage.getItem('token');
    try {
        const [statusRes, nodesRes] = await Promise.all([
            fetch(`/api/ha/node/${nodeId}/cluster/status`, {
                headers: { 'Authorization': `Bearer ${token}` }
            }),
            fetch(`/api/ha/node/${nodeId}/cluster/nodes`, {
                headers: { 'Authorization': `Bearer ${token}` }
            })
        ]);
        
        if (statusRes.ok) {
            clusterStatus.value = await statusRes.json();
        }
        if (nodesRes.ok) {
            clusterNodes.value = await nodesRes.json();
        }
    } catch (err) {
        console.error('Error loading cluster data:', err);
    } finally {
        clusterLoading.value = false;
    }
};

const getHAStateClass = (state: string) => {
    switch (state) {
        case 'started': return 'badge-success';
        case 'stopped': return 'badge-warning';
        case 'disabled': return 'badge-secondary';
        case 'error': return 'badge-danger';
        default: return 'badge-info';
    }
};

const removeFromHA = async (resource: any) => {
    if (!confirm(`Remove ${resource.sid} from HA?`)) return;
    
    const nodeId = await getFirstPVENodeId();
    if (!nodeId) return;
    
    // Parse SID (vm:100 or ct:200)
    const [type, vmid] = resource.sid.split(':');
    
    try {
        const token = localStorage.getItem('token');
        const res = await fetch(`/api/ha/node/${nodeId}/resources/${vmid}?vm_type=${type}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();
        alert(data.message || 'Resource removed');
        loadHAData();
    } catch (err) {
        alert('Error removing resource from HA');
    }
};

const deleteHAGroup = async (groupName: string) => {
    if (!confirm(`Delete HA group "${groupName}"?`)) return;
    
    const nodeId = await getFirstPVENodeId();
    if (!nodeId) return;
    
    try {
        const token = localStorage.getItem('token');
        const res = await fetch(`/api/ha/node/${nodeId}/groups/${groupName}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();
        alert(data.message || 'Group deleted');
        loadHAData();
    } catch (err) {
        alert('Error deleting HA group');
    }
};

const removeNodeFromCluster = async (nodeName: string) => {
    if (!confirm(`⚠️ DANGEROUS: Remove node "${nodeName}" from cluster?\n\nThe node must be POWERED OFF before removal!`)) return;
    
    const nodeId = await getFirstPVENodeId();
    if (!nodeId) return;
    
    try {
        const token = localStorage.getItem('token');
        const res = await fetch(`/api/ha/node/${nodeId}/cluster/nodes/${nodeName}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();
        
        if (data.success) {
            alert(`Node ${nodeName} removed successfully`);
            loadClusterData();
        } else {
            alert(`Error: ${data.message}`);
        }
    } catch (err) {
        alert('Error removing node from cluster');
    }
};

const cleanNodeReferences = async (nodeName: string) => {
    if (!confirm(`Clean leftover references for node "${nodeName}"?`)) return;
    
    const nodeId = await getFirstPVENodeId();
    if (!nodeId) return;
    
    try {
        const token = localStorage.getItem('token');
        const res = await fetch(`/api/ha/node/${nodeId}/cluster/nodes/${nodeName}/clean`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();
        alert(`Cleanup complete for ${nodeName}`);
    } catch (err) {
        alert('Error cleaning node references');
    }
};

const addNodeToCluster = async () => {
    if (!newNodeIP.value) return;
    
    if (!confirm(`Add node ${newNodeIP.value} to cluster?\n\nThe new node must have:\n- Proxmox installed\n- SSH access configured\n- NOT already in a cluster`)) return;
    
    const nodeId = await getFirstPVENodeId();
    if (!nodeId) return;
    
    loading.value = true;
    try {
        const token = localStorage.getItem('token');
        const res = await fetch(`/api/ha/node/${nodeId}/cluster/nodes`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}` 
            },
            body: JSON.stringify({
                new_node_ip: newNodeIP.value,
                link0: newNodeLink0.value || null,
                link1: newNodeLink1.value || null
            })
        });
        const data = await res.json();
        
        if (data.success) {
            alert(`Node ${newNodeIP.value} added successfully!`);
            newNodeIP.value = '';
            newNodeLink0.value = '';
            newNodeLink1.value = '';
            loadClusterData();
        } else {
            alert(`Error: ${data.message}`);
        }
    } catch (err) {
        alert('Error adding node to cluster');
    } finally {
        loading.value = false;
    }
};

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
        ignored_guests: [] as string[],
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
// availableNodes is computed now
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
            // availableNodes is computed from lastAnalysis
        }
        
        // Populate guests list from analysis
        if (lastAnalysis.value.guests) {
            allGuests.value = Object.values(lastAnalysis.value.guests);
        }
        
        // Update last refresh time
        lastUpdateTime.value = new Date().toLocaleTimeString();
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

// Auto-refresh functions
const startAutoRefresh = () => {
    stopAutoRefresh();
    countdown.value = autoRefreshInterval.value;
    
    // Countdown timer (every second)
    countdownTimer = setInterval(() => {
        countdown.value--;
        if (countdown.value <= 0) {
            countdown.value = autoRefreshInterval.value;
        }
    }, 1000);
    
    // Refresh timer
    autoRefreshTimer = setInterval(() => {
        if (activeTab.value === 'health' && !loading.value) {
            runAnalysis();
        }
    }, autoRefreshInterval.value * 1000);
};

const stopAutoRefresh = () => {
    if (autoRefreshTimer) {
        clearInterval(autoRefreshTimer);
        autoRefreshTimer = null;
    }
    if (countdownTimer) {
        clearInterval(countdownTimer);
        countdownTimer = null;
    }
    countdown.value = 0;
};

const toggleAutoRefresh = () => {
    if (autoRefreshEnabled.value) {
        startAutoRefresh();
    } else {
        stopAutoRefresh();
    }
};

// Watch for interval changes while enabled
watch(autoRefreshInterval, () => {
    if (autoRefreshEnabled.value) {
        startAutoRefresh();
    }
});

// Stop auto-refresh when leaving health tab
watch(activeTab, (newTab) => {
    if (newTab !== 'health' && autoRefreshEnabled.value) {
        stopAutoRefresh();
    } else if (newTab === 'health' && autoRefreshEnabled.value) {
        startAutoRefresh();
    }
});

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

onUnmounted(() => {
    stopAutoRefresh();
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

/* Auto-refresh controls */
.auto-refresh-controls {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 16px;
    background: var(--bg-secondary);
    border-radius: 8px;
    border: 1px solid var(--border-color);
}

.toggle-label {
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    font-size: 0.9rem;
}

.toggle-label input {
    display: none;
}

.toggle-switch {
    width: 40px;
    height: 22px;
    background: var(--border-color);
    border-radius: 11px;
    position: relative;
    transition: background 0.3s;
}

.toggle-switch::after {
    content: '';
    width: 18px;
    height: 18px;
    background: white;
    border-radius: 50%;
    position: absolute;
    top: 2px;
    left: 2px;
    transition: transform 0.3s;
}

.toggle-label input:checked + .toggle-switch {
    background: #22c55e;
}

.toggle-label input:checked + .toggle-switch::after {
    transform: translateX(18px);
}

.interval-select {
    padding: 6px 10px;
    border-radius: 6px;
    border: 1px solid var(--border-color);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.85rem;
    cursor: pointer;
}

.interval-select:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.countdown {
    font-size: 0.85rem;
    color: var(--accent-primary);
    font-weight: 600;
    min-width: 50px;
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

/* Migration History Panel */
.history-panel {
    padding-bottom: 40px;
}

.history-count {
    color: var(--text-muted);
    font-size: 0.9rem;
}

.history-table-wrapper {
    overflow-x: auto;
}

.history-table {
    width: 100%;
    border-collapse: collapse;
}

.history-table th {
    text-align: left;
    padding: 12px;
    background: var(--bg-primary);
    border-bottom: 2px solid var(--border-color);
    font-weight: 600;
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.history-table td {
    padding: 12px;
    border-bottom: 1px solid var(--border-color);
    vertical-align: middle;
}

.history-table tbody tr:hover {
    background: rgba(255, 255, 255, 0.03);
}

.date-col {
    white-space: nowrap;
    font-size: 0.85rem;
    color: var(--text-muted);
}

.reason-col {
    max-width: 250px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.status-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 0.8rem;
    font-weight: 600;
}

.status-badge.proposed {
    background: rgba(59, 130, 246, 0.2);
    color: #3b82f6;
}

.status-badge.executing {
    background: rgba(245, 158, 11, 0.2);
    color: #f59e0b;
}

.status-badge.completed {
    background: rgba(34, 197, 94, 0.2);
    color: #22c55e;
}

.status-badge.failed {
    background: rgba(239, 68, 68, 0.2);
    color: #ef4444;
}

.status-badge.skipped {
    background: rgba(107, 114, 128, 0.2);
    color: #9ca3af;
}

.history-table tr.status-failed {
    background: rgba(239, 68, 68, 0.05);
}

.history-table tr.status-completed {
    background: rgba(34, 197, 94, 0.03);
}

/* Cluster Map Panel */
.map-panel {
    padding-bottom: 40px;
}

.map-legend {
    display: flex;
    gap: 16px;
    margin-left: auto;
}

.legend-item {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.85rem;
    color: var(--text-muted);
}

.legend-dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
}

.legend-dot.healthy { background: #22c55e; }
.legend-dot.warning { background: #f59e0b; }
.legend-dot.critical { background: #ef4444; }

.cluster-map {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
    gap: 24px;
    margin-bottom: 24px;
}

.map-node {
    background: var(--bg-secondary);
    border: 2px solid var(--border-color);
    border-radius: 16px;
    padding: 20px;
    transition: all 0.3s ease;
    position: relative;
    overflow: hidden;
}

.map-node::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 4px;
    background: var(--border-color);
}

.map-node.health-good::before { background: linear-gradient(90deg, #22c55e, #4ade80); }
.map-node.health-warning::before { background: linear-gradient(90deg, #f59e0b, #fbbf24); }
.map-node.health-critical::before { background: linear-gradient(90deg, #ef4444, #f87171); }

.map-node:hover {
    transform: translateY(-4px);
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.4);
}

.map-node-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
}

.map-node-name {
    margin: 0;
    font-size: 1.2rem;
    font-weight: 600;
}

.map-node-status {
    font-size: 0.75rem;
    font-weight: 600;
    padding: 4px 10px;
    border-radius: 10px;
}

.map-node-metrics {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin-bottom: 16px;
}

.map-metric {
    display: flex;
    align-items: center;
    gap: 10px;
}

.map-metric-label {
    width: 35px;
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--text-muted);
}

.map-metric-bar {
    flex: 1;
    height: 6px;
    background: var(--border-color);
    border-radius: 3px;
    overflow: hidden;
}

.map-metric-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.5s ease;
}

.map-metric-value {
    width: 45px;
    text-align: right;
    font-size: 0.8rem;
    font-weight: 600;
}

.map-guests-container {
    background: var(--bg-primary);
    border-radius: 10px;
    padding: 12px;
}

.map-guests-header {
    font-size: 0.8rem;
    color: var(--text-muted);
    margin-bottom: 10px;
    font-weight: 500;
}

.map-guests-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}

.map-guest {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 4px 8px;
    border-radius: 6px;
    font-size: 0.75rem;
    cursor: pointer;
    transition: all 0.2s ease;
}

.map-guest.vm {
    background: rgba(59, 130, 246, 0.15);
    color: #3b82f6;
}

.map-guest.ct {
    background: rgba(168, 85, 247, 0.15);
    color: #a855f7;
}

.map-guest:hover {
    transform: scale(1.05);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

.map-guest.more {
    background: rgba(107, 114, 128, 0.2);
    color: var(--text-muted);
    font-weight: 600;
}

.map-guest-type {
    font-size: 0.9rem;
}

.map-guest-id {
    font-weight: 600;
}

/* Map Summary */
.map-summary {
    display: flex;
    justify-content: center;
    gap: 40px;
    padding: 20px;
    background: var(--bg-secondary);
    border-radius: 12px;
    border: 1px solid var(--border-color);
}

.map-summary-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
}

.map-summary-icon {
    font-size: 1.5rem;
}

.map-summary-value {
    font-size: 1.8rem;
    font-weight: 700;
}

.map-summary-label {
    font-size: 0.8rem;
    color: var(--text-muted);
}

/* Guest Manager Panel */
.guests-panel {
    padding-bottom: 40px;
}

.search-box {
    position: relative;
    flex: 1;
    min-width: 200px;
    max-width: 300px;
}

.search-icon {
    position: absolute;
    left: 10px;
    top: 50%;
    transform: translateY(-50%);
    color: var(--text-muted);
    font-size: 0.9rem;
}

.search-input {
    width: 100%;
    padding: 8px 12px 8px 32px;
    border-radius: 6px;
    border: 1px solid var(--border-color);
    background: var(--bg-secondary);
    color: var(--text-color);
    font-size: 0.9rem;
}

.search-input:focus {
    border-color: var(--primary-color);
    outline: none;
}

.filter-select {
    padding: 8px 12px;
    border-radius: 6px;
    border: 1px solid var(--border-color);
    background: var(--bg-secondary);
    color: var(--text-color);
    cursor: pointer;
    min-width: 120px;
}

/* Bulk Actions Bar */
.bulk-actions-bar {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 10px 16px;
    background: rgba(59, 130, 246, 0.1);
    border: 1px solid rgba(59, 130, 246, 0.3);
    border-radius: 8px;
    margin-bottom: 16px;
    animation: fadeIn 0.3s ease;
}

.selection-count {
    font-weight: 600;
    color: #3b82f6;
    font-size: 0.9rem;
}

.bulk-buttons {
    display: flex;
    gap: 8px;
}

.btn-text {
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 0.85rem;
    text-decoration: underline;
    margin-left: auto;
}

.btn-text:hover {
    color: var(--text-color);
}

.col-checkbox {
    width: 40px;
    text-align: center;
}

.status-dot {
    display: block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #ccc;
}

.status-dot.running { background: #22c55e; }
.status-dot.stopped { background: #9ca3af; }

.badge-ignored {
    background: #f59e0b;
    color: #fff;
    font-size: 0.7rem;
    padding: 2px 6px;
    border-radius: 4px;
    font-weight: 700;
}

.row-ignored {
    opacity: 0.6;
    background: rgba(245, 158, 11, 0.05);
}

.row-ignored:hover {
    opacity: 0.9;
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(-5px); }
    to { opacity: 1; transform: translateY(0); }
}

@media (max-width: 768px) {
    .cluster-map {
        grid-template-columns: 1fr;
    }
    
    .map-summary {
        flex-wrap: wrap;
        gap: 20px;
    }
}

.metric-cell {
    display: flex;
    flex-direction: column;
    font-size: 0.9rem;
    line-height: 1.2;
}

.sub-metric {
    font-size: 0.75rem;
    color: var(--text-secondary);
}

.mono-text {
    font-family: monospace;
}
</style>
