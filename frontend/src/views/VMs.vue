<template>
  <div class="vms-page">
    <div class="page-header">
        <h1 class="page-title">🖥️ Virtual Machines</h1>
        <p class="page-subtitle">Gestione risorse, lifecycle, snapshot e backup</p>
        <div class="header-actions">
            <button class="btn btn-secondary btn-sm" @click="loadVMs" :disabled="loading">
                <span v-if="loading" class="spinner-sm"></span>
                <span v-else>🔄 Aggiorna</span>
            </button>
            <input type="text" v-model="search" placeholder="Cerca VM o ID..." class="form-input search-input">
        </div>
    </div>

    <!-- Stats Summary -->
    <div class="grid-3 mb-4">
        <div class="card stat-mini">
             <div class="stat-value">{{ vms.length }}</div>
             <div class="stat-label">Totali</div>
        </div>
        <div class="card stat-mini">
             <div class="stat-value text-success">{{ runningCount }}</div>
             <div class="stat-label">Running</div>
        </div>
        <div class="card stat-mini">
             <div class="stat-value text-secondary">{{ vms.length - runningCount }}</div>
             <div class="stat-label">Stopped</div>
        </div>
    </div>

    <div class="card">
        <div class="table-container">
            <table class="data-table w-full">
                <thead>
                    <tr>
                        <th width="80" @click="sortBy('vmid')" class="cursor-pointer hover:text-accent select-none">
                            ID <span v-if="sortKey === 'vmid'">{{ sortDesc ? '↓' : '↑' }}</span>
                        </th>
                        <th @click="sortBy('name')" class="cursor-pointer hover:text-accent select-none">
                            Nome <span v-if="sortKey === 'name'">{{ sortDesc ? '↓' : '↑' }}</span>
                        </th>
                        <th width="120" style="min-width: 120px;" @click="sortBy('node')" class="cursor-pointer hover:text-accent select-none">
                            Host <span v-if="sortKey === 'node'">{{ sortDesc ? '↓' : '↑' }}</span>
                        </th>
                         <th width="100" @click="sortBy('status')" class="cursor-pointer hover:text-accent select-none">
                            Stato <span v-if="sortKey === 'status'">{{ sortDesc ? '↓' : '↑' }}</span>
                        </th>
                        <th width="180">Allocazioni</th>
                        <th width="140">Backup PBS</th>
                        <th width="420" class="text-right">Azioni</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="vm in filteredVMs" :key="vm.vmid + '-' + vm.node">
                        <td class="font-mono font-bold text-accent">{{ vm.vmid }}</td>
                        <td style="width: 250px;">
                            <div class="flex items-center gap-2">
                                <span class="font-medium text-lg">{{ vm.name }}</span>
                                <span class="badge text-xs" :class="vm.type === 'lxc' ? 'badge-warning' : 'badge-info'">
                                    {{ vm.type === 'lxc' ? 'CT' : 'VM' }}
                                </span>
                            </div>
                            <div v-if="vm.net0_ip" class="text-xs font-mono text-secondary mt-1">
                                {{ vm.net0_ip }}
                            </div>
                        </td>
                        <td>
                             <span class="badge badge-outline text-sm">{{ vm.node }}</span>
                        </td>
                        <td>
                            <span class="badge" :class="vm.status === 'running' ? 'badge-success' : 'badge-secondary'">
                                <span class="status-dot"></span>
                                {{ vm.status === 'running' ? 'ON' : 'OFF' }}
                            </span>
                            <div v-if="vm.loading" class="text-xs text-accent mt-1">Processing...</div>
                        </td>
                        <td class="resource-cell">
                            <!-- Allocated Resources (Text) -->
                            <div class="text-xs space-y-1">
                                <span class="font-mono text-primary font-bold mr-2">{{ vm.maxcpu || 1 }} Core</span>
                                <span class="font-mono text-primary font-bold mr-2">{{ formatSize(vm.maxmem || 0) }} RAM</span>
                                <span class="font-mono text-primary" v-if="vm.maxdisk">{{ formatSize(vm.maxdisk || 0) }} HD</span>
                            </div>
                        </td>
                        <td>
                            <!-- Legacy: Backup PBS Count -->
                            <div class="pbs-backup-cell">
                                <span v-if="vm.backupCount !== undefined" class="badge badge-purple">
                                    📦 {{ vm.backupCount }} backup
                                </span>
                                <span v-else class="text-xs text-secondary animate-pulse">Checking...</span>
                            </div>
                        </td>
                        <td class="text-right">
                            <div class="flex justify-end gap-2">
                                <button class="btn btn-sm btn-outline" @click="openVMInfoModal(vm)" title="Dettagli VM">
                                    📊 Info
                                </button>
                                <button class="btn btn-sm btn-cyan" @click="openBackupModal(vm)" title="Backup PBS">
                                    ☁️ Backup PBS
                                </button>
                                <button class="btn btn-sm btn-primary" @click="openReplicationWizard(vm)" title="Configura Replica">
                                    🔄 Replica
                                </button>
                                <button class="btn btn-sm btn-dark" @click="openSnapshotModal(vm)" title="Snapshot">
                                    📷 Snapshot
                                </button>
                                <!-- Start/Stop mini actions -->
                                 <button v-if="vm.status === 'stopped'" 
                                        class="btn btn-success btn-xs btn-icon" 
                                        @click="manageState(vm, 'start')"
                                        :disabled="vm.loading"
                                        title="Start VM">
                                    ▶
                                </button>
                                <button v-else 
                                        class="btn btn-danger btn-xs btn-icon" 
                                        @click="manageState(vm, 'shutdown')"
                                        :disabled="vm.loading"
                                        title="Shutdown VM">
                                    ⏹
                                </button>
                            </div>
                        </td>
                    </tr>
                    <tr v-if="filteredVMs.length === 0 && !loading">
                         <td colspan="7" class="empty-state-cell text-center py-8 text-secondary">Nessuna VM trovata</td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>

    <!-- Snapshot Modal -->
    <ModalDialog v-model:visible="showSnapshotModal" :title="`📸 Snapshot Manager - ${selectedVM?.name}`" width="900px">
        <div class="tabs mb-4">
            <button class="tab-btn" :class="{ active: snapshotTab === 'proxmox' }" @click="snapshotTab = 'proxmox'">Proxmox Snapshots</button>
            <button class="tab-btn" :class="{ active: snapshotTab === 'sanoid' }" @click="openSanoidSection()">Sanoid Config</button>
        </div>

        <!-- Proxmox Snapshots Tab -->
        <div v-if="snapshotTab === 'proxmox'">
            <div class="action-bar mb-4 bg-dark-soft p-3 rounded flex justify-between items-center">
                 <span class="text-sm text-secondary">Snapshot standard Proxmox VE (con RAM opzionale)</span>
                 <button class="btn btn-primary btn-sm" @click="showCreatePveSnapshot = true" v-if="!showCreatePveSnapshot">+ Create Snapshot</button>
            </div>

            <!-- Create Form -->
            <div v-if="showCreatePveSnapshot" class="card p-4 mb-4 border-accent">
                <h4 class="mb-3">Nuovo Proxmox Snapshot</h4>
                <div class="grid-2 gap-4 mb-3">
                    <input v-model="newSnapName" placeholder="Nome snapshot" class="form-input">
                    <div class="flex items-center">
                        <label class="flex items-center gap-2 cursor-pointer">
                            <input type="checkbox" v-model="newSnapRam"> 
                            <span>Include RAM</span>
                        </label>
                    </div>
                </div>
                <input v-model="newSnapDesc" placeholder="Descrizione (opzionale)" class="form-input mb-3">
                <div class="flex gap-2 justify-end">
                    <button class="btn btn-secondary btn-sm" @click="showCreatePveSnapshot = false">Annulla</button>
                    <button class="btn btn-primary btn-sm" @click="createPveSnapshot">Crea Snapshot</button>
                </div>
            </div>

            <!-- PVE Snapshots List -->
            <div class="snapshot-list">
                <div v-if="snapshotsLoading" class="text-center p-4">Caricamento...</div>
                <div v-else-if="allSnapshots.length === 0" class="text-center text-secondary p-4">Nessuno snapshot trovato.</div>
                <div v-else>
                    <!-- PVE Snapshots Section -->
                    <div v-if="snapshots.length > 0" class="mb-4">
                        <h5 class="text-sm font-bold text-secondary mb-2">📷 Proxmox VM Snapshots</h5>
                        <div v-for="snap in snapshots" :key="'pve-' + snap.name" class="snapshot-item card flex justify-between items-center p-3 mb-2">
                            <div>
                                <div class="font-bold flex items-center gap-2">
                                    {{ snap.name }}
                                    <span v-if="snap.vmstate" class="badge badge-purple text-xs">RAM</span>
                                </div>
                                <div class="text-xs text-secondary">{{ formatDate(snap.snaptime) }}</div>
                                <div class="text-xs text-secondary mt-1">{{ snap.description }}</div>
                            </div>
                            <div class="btn-group">
                                <button class="btn btn-warning btn-xs" @click="rollbackPveSnapshot(snap.name)">Rollback</button>
                                <button class="btn btn-danger btn-xs" @click="deletePveSnapshot(snap.name)">Delete</button>
                            </div>
                        </div>
                    </div>
                    
                    <!-- ZFS/Sanoid Snapshots Section -->
                    <div v-if="groupedZfsSnapshots.length > 0">
                        <h5 class="text-sm font-bold text-secondary mb-2">⚡ ZFS/Sanoid Snapshots</h5>
                        <div v-for="snap in groupedZfsSnapshots" :key="'zfs-' + snap.name" class="snapshot-item card flex justify-between items-center p-3 mb-2">
                            <div>
                                <div class="font-bold flex items-center gap-2">
                                    {{ snap.name }}
                                    <span class="badge badge-info text-xs">ZFS</span>
                                    <span class="badge badge-outline text-xs" title="Dischi coinvolti">{{ snap.datasetsCount }} disks</span>
                                    <span class="badge text-xs" :class="getPolicyBadge(snap.name).class">{{ getPolicyBadge(snap.name).text }}</span>
                                </div>
                                <div class="text-xs text-secondary">{{ snap.creation || 'N/A' }}</div>
                            </div>
                            <div class="btn-group">
                                <button class="btn btn-cyan btn-xs" @click="startZfsCloneWizard(snap)">Clone</button>
                                <button class="btn btn-warning btn-xs" @click="rollbackZfs(snap)">Rollback</button>
                                <button class="btn btn-danger btn-xs" @click="deleteZfsSnapshot(snap)">Delete</button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>



        <!-- Sanoid Config Tab -->
        <div v-if="snapshotTab === 'sanoid'">
            <div v-if="sanoidLoading" class="text-center p-8">Reading configuration...</div>
            <div v-else class="sanoid-form">
                <div class="flex items-center gap-3 mb-6 p-4 bg-dark-soft rounded">
                    <label class="switch">
                        <input type="checkbox" v-model="sanoidConfig.enable">
                        <span class="slider round"></span>
                    </label>
                    <div>
                        <div class="font-bold">Abilita Sanoid per questa VM</div>
                        <div class="text-xs text-secondary">Gestione automatica snapshot su tutti i dischi</div>
                    </div>
                </div>

                <div v-if="sanoidConfig.enable" class="grid-2 gap-6">
                    <div class="card p-4">
                        <h4 class="mb-3">Policy Template</h4>
                        <select v-model="sanoidConfig.template" class="form-select w-full mb-3">
                            <option value="production">Production (Freq High)</option>
                            <option value="backup">Backup (Long Term)</option>
                            <option value="test">Test (Short Term)</option>
                        </select>
                        <div class="flex gap-4">
                            <label class="flex items-center gap-2">
                                <input type="checkbox" v-model="sanoidConfig.autosnap"> Auto Snapshot
                            </label>
                            <label class="flex items-center gap-2">
                                <input type="checkbox" v-model="sanoidConfig.autoprune"> Auto Prune
                            </label>
                        </div>
                    </div>

                    <div class="card p-4">
                        <h4 class="mb-3">Retention Policy (Override)</h4>
                        <div class="grid-2 gap-2 text-sm">
                            <label>Hourly <input type="number" v-model="sanoidConfig.hourly" class="form-input-sm"></label>
                            <label>Daily <input type="number" v-model="sanoidConfig.daily" class="form-input-sm"></label>
                             <label>Weekly <input type="number" v-model="sanoidConfig.weekly" class="form-input-sm"></label>
                            <label>Monthly <input type="number" v-model="sanoidConfig.monthly" class="form-input-sm"></label>
                            <label>Yearly <input type="number" v-model="sanoidConfig.yearly" class="form-input-sm"></label>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <template #footer>
            <div v-if="snapshotTab === 'sanoid'" class="w-full flex justify-between">
                <button class="btn btn-cyan" @click="triggerSanoidSnapshot" :disabled="sanoidTriggering">
                    {{ sanoidTriggering ? 'Creating...' : '⚡ Snapshot Adesso' }}
                </button>
                <button class="btn btn-primary" @click="saveSanoidConfig" :disabled="sanoidSaving">
                    {{ sanoidSaving ? 'Saving...' : 'Salva Configurazione' }}
                </button>
            </div>
            <div v-if="snapshotTab === 'sanoid'" class="w-full text-center mt-2">
                <p class="text-xs text-secondary">
                    ℹ️ <strong>Nota:</strong> Gli snapshot automatici sono gestiti da <code>cron</code> e <code>sanoid</code> a livello di sistema.<br>
                    Le policy configurate qui vengono applicate alle prossime esecuzioni pianificate (es. ogni 15 minuti/ora).
                </p>
            </div>
            <div v-else class="w-full flex justify-end">
                 <button class="btn btn-secondary" @click="showSnapshotModal = false">Chiudi</button>
            </div>
        </template>
    </ModalDialog>

    <!-- Backup Modal -->
    <ModalDialog v-model:visible="showBackupModal" :title="`💾 Backup & Restore - ${selectedVM?.name}`" width="900px">
        <div v-if="!restoreMode">
            <!-- List View -->
             <div class="mb-4 flex justify-between items-center">
                 <div class="text-sm text-secondary">Backup PBS disponibili per questa VM.</div>
                 <div>
                     <!-- Future: Backup Now button -->
                 </div>
             </div>
             
             <div v-if="backupsLoading" class="text-center p-8">Caricamento backup...</div>
             <div v-else-if="backups.length === 0" class="text-center p-8 text-secondary border border-dashed border-gray-700 rounded">
                 Nessun backup trovato. Verifica la configurazione PBS.
             </div>
             <div v-else class="backup-list">
                 <table class="w-full text-sm">
                    <thead>
                        <tr class="text-left text-secondary border-b border-gray-700">
                            <th class="p-2">Time</th>
                            <th class="p-2">Size</th>
                            <th class="p-2">Storage</th>
                            <th class="p-2 text-right">Action</th>
                        </tr>
                    </thead>
                    <tbody>
                         <tr v-for="bak in backups" :key="bak.volid" class="border-b border-gray-800 hover:bg-white/5">
                            <td class="p-2">
                                <div class="font-bold">{{ formatDate(bak['backup-time']) }}</div>
                                <div class="text-xs text-secondary font-mono">{{ bak.volid }}</div>
                            </td>
                             <td class="p-2">{{ formatSize(bak.size) }}</td>
                             <td class="p-2"><span class="badge badge-outline text-xs">{{ bak.storage_id }}</span></td>
                             <td class="p-2 text-right">
                                 <button class="btn btn-primary btn-xs" @click="startRestoreWizard(bak)">Restore...</button>
                             </td>
                         </tr>
                    </tbody>
                 </table>
             </div>
        </div>

        <div v-else class="restore-wizard">
            <!-- Restore Wizard -->
            <div class="mb-4 pb-2 border-b border-gray-700 flex justify-between items-center">
                <h3>🔄 {{ zfsCloneMode ? 'ZFS Clone Wizard' : 'Restore Wizard' }}</h3>
                <button class="btn-xs btn-secondary" @click="restoreMode = false; zfsCloneMode = false; showBackupModal = zfsCloneMode ? false : true">Back</button>
            </div>
            
            <div class="grid-2 gap-8">
                <div class="wizard-info">
                    <h4>{{ zfsCloneMode ? 'Source Snapshot' : 'Source Backup' }}</h4>
                    <div class="p-3 bg-dark-soft rounded mb-4 text-sm space-y-2">
                        <div><strong>VM:</strong> {{ selectedVM?.name }} ({{ selectedVM?.vmid }})</div>
                        <div v-if="!zfsCloneMode"><strong>Backup:</strong> {{ formatDate(restoreSelection?.['backup-time'] || 0) }}</div>
                        <div v-else><strong>Snapshot:</strong> {{ zfsCloneSelection?.name }}</div>
                        <div class="text-xs break-all text-secondary">{{ !zfsCloneMode ? restoreSelection?.volid : zfsCloneSelection?.dataset }}</div>
                        <div v-if="zfsCloneMode" class="text-xs text-secondary">{{ zfsCloneSelection?.datasetsCount || 1 }} datasets included</div>
                    </div>
                    
                    <div class="alert alert-warning" v-if="!restoreOptions.newVmid">
                        ⚠️ <strong>Attenzione:</strong> Il ripristino sovrascriverà i dati esistenti se si usa lo stesso VMID.
                    </div>
                    <div class="alert alert-info" v-else>
                         ℹ️ Verrà creata una nuova VM con ID <strong>{{ restoreOptions.newVmid }}</strong>.
                    </div>
                </div>
                
                <div class="wizard-form space-y-4">
                    <div>
                        <label class="block text-sm text-secondary mb-1">Target Node</label>
                        <select v-model="restoreOptions.targetNodeId" class="form-select w-full" @change="loadTargetStorages">
                            <option v-for="node in availableNodes" :key="node.id" :value="node.id">
                                {{ node.name }} ({{ node.hostname }})
                            </option>
                        </select>
                    </div>

                    <div>
                         <label class="block text-sm text-secondary mb-1">Target Storage</label>
                         <select v-model="restoreOptions.storage" class="form-select w-full">
                             <option value="">(Default dal backup)</option>
                             <option v-for="st in targetStorages" :key="st.name" :value="st.name">
                                 {{ st.name }} ({{ st.type }}) - {{ st.avail_gb || '?' }} GB free
                             </option>
                         </select>
                    </div>
                    
                     <div>
                         <label class="block text-sm text-secondary mb-1">New VMID (Clone) - Optional</label>
                         <input v-model.number="restoreOptions.newVmid" type="number" class="form-input" :placeholder="String(selectedVM?.vmid)">
                         <div class="text-xs text-secondary mt-1">Lascia vuoto per sovrascrivere la VM esistente.</div>
                    </div>

                    <div>
                         <label class="block text-sm text-secondary mb-1">VM Name - Optional</label>
                         <input v-model="restoreOptions.newName" type="text" class="form-input" :placeholder="selectedVM?.name">
                         <div class="text-xs text-secondary mt-1">Nuovo nome per la VM (solo se cambi VMID).</div>
                    </div>
                    
                    <div class="pt-2">
                        <label class="flex items-center gap-2 cursor-pointer">
                            <input type="checkbox" v-model="restoreOptions.start"> 
                            <span>Start VM after restore</span>
                        </label>
                    </div>
                </div>
            </div>
        </div>

        <template #footer>
            <div v-if="restoreMode || zfsCloneMode"> 
                <!-- Footer for Wizard -->
                <div class="flex justify-end gap-2">
                    <button class="btn btn-secondary" @click="restoreMode = false; zfsCloneMode = false; showBackupModal = zfsCloneMode ? false : true">Annulla</button>
                    <button v-if="!zfsCloneMode" class="btn btn-danger" @click="executeRestore">Start Restore</button>
                    <button v-else class="btn btn-cyan" @click="executeZfsClone">Start ZFS Clone</button>
                </div>
            </div>
            <div v-else class="flex justify-end">
                <button class="btn btn-secondary" @click="showBackupModal = false">Chiudi</button>
            </div>
        </template>
    </ModalDialog>

    <!-- ZFS Clone Modal (Dedicated) -->
    <ModalDialog :show="showZfsCloneModal" @close="showZfsCloneModal = false" title="⚡ Clone da Snapshot ZFS" size="md">
        <div class="zfs-clone-wizard">
            <div class="alert alert-warning mb-4">
                ⚠️ <strong>Attenzione:</strong> Questa operazione creerà una <b>nuova VM</b> clonando i dischi dallo snapshot selezionato.
                La VM originale non verrà modificata.
            </div>
            
            <div class="p-4 bg-dark-soft rounded mb-4 space-y-2">
                <div><strong>VM Origine:</strong> {{ selectedVM?.name }} ({{ selectedVM?.vmid }})</div>
                <div><strong>Snapshot:</strong> {{ zfsCloneSelection?.name }}</div>
                <div class="text-xs text-secondary">{{ zfsCloneSelection?.datasetsCount || 1 }} dataset(s)</div>
            </div>

            <div class="space-y-4">
                <div>
                    <label class="block text-sm text-secondary mb-1">Nuovo VMID <span class="text-danger">*</span></label>
                    <input v-model.number="zfsCloneOptions.newVmid" type="number" class="form-input" placeholder="Es: 999">
                </div>
                <div>
                    <label class="block text-sm text-secondary mb-1">Nome Nuova VM</label>
                    <input v-model="zfsCloneOptions.newName" type="text" class="form-input" :placeholder="selectedVM?.name + '-clone'">
                </div>
            </div>
        </div>
        
        <template #footer>
            <div class="flex justify-between w-full">
                <button class="btn btn-secondary" @click="showZfsCloneModal = false">Annulla</button>
                <button class="btn btn-primary" @click="confirmZfsClone" :disabled="!zfsCloneOptions.newVmid">
                    🚀 Crea Clone
                </button>
            </div>
        </template>
    </ModalDialog>

    <!-- VM Info Modal -->
    <ModalDialog v-model:visible="showVMInfoModal" :title="`📊 Dettagli VM: ${vmInfoData?.name || selectedVM?.name}`" width="800px">
        <div v-if="vmInfoLoading" class="text-center p-8">
            <div class="spinner-lg mb-4"></div>
            <p>Caricamento dettagli VM...</p>
        </div>
        <div v-else-if="vmInfoData" class="vm-details-grid">
            <!-- Basic Info -->
            <div class="detail-card">
                <h4>🖥️ Info Base</h4>
                <table class="simple-table">
                    <tr><td>VMID:</td><td><strong class="text-accent">{{ vmInfoData.vmid }}</strong></td></tr>
                    <tr><td>Nome:</td><td>{{ vmInfoData.config?.name || selectedVM?.name }}</td></tr>
                    <tr><td>Tipo:</td><td><span class="badge" :class="vmInfoData.type === 'lxc' ? 'badge-warning' : 'badge-info'">{{ vmInfoData.type === 'lxc' ? 'Container' : 'QEMU VM' }}</span></td></tr>
                    <tr><td>Stato:</td><td><span class="badge" :class="selectedVM?.status === 'running' ? 'badge-success' : 'badge-secondary'">{{ selectedVM?.status }}</span></td></tr>
                    <tr><td>Nodo:</td><td>{{ selectedVM?.node }}</td></tr>
                </table>
            </div>

            <!-- Resources -->
            <div class="detail-card">
                <h4>⚙️ Risorse Allocate</h4>
                <table class="simple-table">
                    <tr><td>CPU Cores:</td><td><strong>{{ vmInfoData.config?.cores || vmInfoData.config?.cpulimit || 1 }}</strong></td></tr>
                    <tr v-if="vmInfoData.config?.sockets"><td>Sockets:</td><td>{{ vmInfoData.config.sockets }}</td></tr>
                    <tr><td>Memoria:</td><td><strong>{{ vmInfoData.config?.memory || vmInfoData.config?.swap || 0 }} MB</strong></td></tr>
                    <tr v-if="vmInfoData.config?.balloon"><td>Balloon:</td><td>{{ vmInfoData.config.balloon }} MB</td></tr>
                    <tr v-if="vmInfoData.config?.cpu"><td>CPU Type:</td><td class="text-xs">{{ vmInfoData.config.cpu }}</td></tr>
                </table>
            </div>

            <!-- Disks -->
            <div class="detail-card full-width">
                <h4>💽 Dischi</h4>
                <div class="disk-list">
                    <div v-for="(value, key) in getDiskEntries(vmInfoData.config)" :key="key" class="disk-item">
                        <span class="font-bold">{{ key }}:</span>
                        <span class="text-sm text-secondary ml-2">{{ value }}</span>
                    </div>
                    <div v-if="Object.keys(getDiskEntries(vmInfoData.config)).length === 0" class="text-secondary text-sm">
                        Nessun disco trovato
                    </div>
                </div>
            </div>

            <!-- Network -->
            <div class="detail-card full-width">
                <h4>🌐 Network</h4>
                <div class="network-list">
                    <div v-for="(value, key) in getNetworkEntries(vmInfoData.config)" :key="key" class="network-item">
                        <span class="font-bold">{{ key }}:</span>
                        <span class="text-sm text-secondary ml-2">{{ value }}</span>
                    </div>
                    <div v-if="selectedVM?.net0_ip" class="mt-2">
                        <span class="text-xs text-secondary">IP Rilevato:</span>
                        <span class="font-mono text-accent ml-2">{{ selectedVM.net0_ip }}</span>
                    </div>
                    <div v-if="Object.keys(getNetworkEntries(vmInfoData.config)).length === 0" class="text-secondary text-sm">
                        Nessuna interfaccia di rete
                    </div>
                </div>
            </div>

            <!-- Boot & Options -->
            <div class="detail-card">
                <h4>🔧 Opzioni</h4>
                <table class="simple-table">
                    <tr v-if="vmInfoData.config?.boot"><td>Boot Order:</td><td class="text-xs">{{ vmInfoData.config.boot }}</td></tr>
                    <tr v-if="vmInfoData.config?.onboot !== undefined"><td>Start on Boot:</td><td>{{ vmInfoData.config.onboot ? '✅ Yes' : '❌ No' }}</td></tr>
                    <tr v-if="vmInfoData.config?.ostype"><td>OS Type:</td><td>{{ vmInfoData.config.ostype }}</td></tr>
                    <tr v-if="vmInfoData.config?.machine"><td>Machine:</td><td class="text-xs">{{ vmInfoData.config.machine }}</td></tr>
                    <tr v-if="vmInfoData.config?.bios"><td>BIOS:</td><td>{{ vmInfoData.config.bios }}</td></tr>
                </table>
            </div>

            <!-- Snapshots Summary -->
            <div class="detail-card">
                <h4>📷 Snapshots</h4>
                <div v-if="vmInfoData.snapshots?.list?.length">
                    <div class="text-2xl font-bold text-accent mb-2">{{ vmInfoData.snapshots.list.length }}</div>
                    <div class="text-sm text-secondary">snapshot disponibili</div>
                    <div class="mt-2 text-xs">
                        Ultimo: {{ vmInfoData.snapshots.list[vmInfoData.snapshots.list.length - 1]?.name }}
                    </div>
                </div>
                <div v-else class="text-secondary text-sm">Nessuno snapshot</div>
            </div>

            <!-- Raw Config Toggle -->
            <div class="detail-card full-width">
                <details>
                    <summary class="cursor-pointer text-secondary">📋 Mostra configurazione raw</summary>
                    <pre class="text-xs mt-2" style="max-height: 300px; overflow: auto; background: var(--bg-secondary); padding: 8px; border-radius: 4px;">{{ JSON.stringify(vmInfoData.config, null, 2) }}</pre>
                </details>
            </div>
        </div>
        <div v-else class="text-center text-secondary p-8">
            Nessun dato disponibile
        </div>
        
        <template #footer>
            <button class="btn btn-secondary" @click="showVMInfoModal = false">Chiudi</button>
        </template>
    </ModalDialog>

    <!-- Replication Wizard -->
    <ReplicationWizard 
      v-if="showReplicationWizard" 
      :initial-vm="selectedReplicationVM"
      @close="showReplicationWizard = false" 
      @created="showReplicationWizard = false; loadVMs()" 
    />

  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue';
import vmsService, { type VM, type Snapshot, type Backup, type SanoidConfig, type ZFSSnapshot } from '../services/vms';
import nodesService from '../services/nodes';
import ModalDialog from '../components/ModalDialog.vue';
import ReplicationWizard from './replication/ReplicationWizard.vue';

// State
const vms = ref<VM[]>([]);
const loading = ref(false);
const search = ref('');
const selectedVM = ref<VM | null>(null);

// VM Info Modal State
const showVMInfoModal = ref(false);
const vmInfoData = ref<any>(null);
const vmInfoLoading = ref(false);

// Sorting
const sortKey = ref('vmid');
const sortDesc = ref(false);

const sortBy = (key: string) => {
    if (sortKey.value === key) {
        sortDesc.value = !sortDesc.value;
    } else {
        sortKey.value = key;
        sortDesc.value = false;
    }
};

// Snapshot Modal State
const showSnapshotModal = ref(false);
const snapshotTab = ref<'proxmox' | 'sanoid'>('proxmox');
const snapshots = ref<Snapshot[]>([]);
const snapshotsLoading = ref(false);
const showCreatePveSnapshot = ref(false);
const newSnapName = ref('');
const newSnapDesc = ref('');
const newSnapRam = ref(false);

// ZFS State
const zfsSnapshots = ref<ZFSSnapshot[]>([]);
const zfsLoading = ref(false);

// Sanoid State
const sanoidConfig = ref<SanoidConfig>({
    enable: false,
    template: 'production',
    autosnap: true,
    autoprune: true,
    hourly: 0,
    daily: 0,
    weekly: 0,
    monthly: 0,
    yearly: 0,
    datasets: []
});
const sanoidLoading = ref(false);
const sanoidSaving = ref(false);
const sanoidTriggering = ref(false);

// ZFS Clone Modal State (Dedicated)
const showZfsCloneModal = ref(false);
const zfsCloneOptions = ref({
    newVmid: null as number | null,
    newName: ''
});

// Backup Modal State
const showBackupModal = ref(false);
const backups = ref<Backup[]>([]);
const backupsLoading = ref(false);
const restoreMode = ref(false);
const zfsCloneMode = ref(false); // Distinction for Wizard context
const restoreSelection = ref<Backup | null>(null);
const zfsCloneSelection = ref<ZFSSnapshot | null>(null);
const restoreOptions = ref({
    targetNodeId: 0,
    storage: '',
    newVmid: null as number | null,
    newName: '',
    start: true
});

// Replication Wizard State
const showReplicationWizard = ref(false);
const selectedReplicationVM = ref<any>(null);

const openReplicationWizard = (vm: VM) => {
    selectedReplicationVM.value = vm;
    showReplicationWizard.value = true;
};

// Nodes and Storages for Restore Wizard
const availableNodes = ref<any[]>([]);
const targetStorages = ref<any[]>([]);

// Computed
const groupedZfsSnapshots = computed(() => {
    const groups: Record<string, any> = {};
    for (const snap of zfsSnapshots.value) {
        if (!groups[snap.name]) {
            groups[snap.name] = { ...snap, datasetsCount: 0, datasets: [] };
        }
        groups[snap.name].datasetsCount++;
        groups[snap.name].datasets.push(snap.dataset);
    }
    // Sort by creation desc (assuming creation date string is comparable or consistent)
    return Object.values(groups).sort((a, b) => (b.creation || '').localeCompare(a.creation || ''));
});

const allSnapshots = computed(() => [...snapshots.value, ...groupedZfsSnapshots.value]);
const runningCount = computed(() => vms.value.filter(v => v.status === 'running').length);
const filteredVMs = computed(() => {
    let result = vms.value;
    if (search.value) {
        const term = search.value.toLowerCase();
        result = result.filter(v => v.name?.toLowerCase().includes(term) || v.vmid?.toString().includes(term));
    }
    return result.slice().sort((a: any, b: any) => {
        const valA = a[sortKey.value];
        const valB = b[sortKey.value];
        const modifier = sortDesc.value ? -1 : 1;
        if (typeof valA === 'string' && typeof valB === 'string') return valA.localeCompare(valB) * modifier;
        if (valA < valB) return -1 * modifier;
        if (valA > valB) return 1 * modifier;
        return 0;
    });
});

onMounted(() => {
    loadVMs();
});

const loadVMs = async () => {
    loading.value = true;
    try {
        const res = await vmsService.getVMs();
        vms.value = res.data;
    } catch (e) {
        console.error('Error loading VMs', e);
    } finally {
        loading.value = false;
        fetchBackupCounts();
    }
};

const fetchBackupCounts = async () => {
    for (const vm of vms.value) {
        if (vm.status !== 'running' && vm.status !== 'stopped') continue;
        if (!vm.node_id) continue;
        try {
            const res = await vmsService.getBackups(vm.node_id, vm.vmid);
            vm.backupCount = res.data ? res.data.length : 0;
        } catch (e) { vm.backupCount = 0; }
    }
};

const manageState = async (vm: VM, action: any) => {
    if (!confirm(`Sei sicuro di voler eseguire ${action} su ${vm.name}?`)) return;
    vm.loading = true;
    try {
        await vmsService.manageState(vm.node_id!, vm.vmid, action);
        setTimeout(() => loadVMs(), 2000);
    } catch (e) {
        alert('Errore azione: ' + e);
        vm.loading = false;
    }
};

// --- VM Info Modal ---
const openVMInfoModal = async (vm: VM) => {
    selectedVM.value = vm;
    vmInfoData.value = null;
    vmInfoLoading.value = true;
    showVMInfoModal.value = true;
    
    try {
        const res = await vmsService.getVMDetails(vm.node_id!, vm.vmid, vm.type);
        vmInfoData.value = res.data;
    } catch (e) {
        console.error('Error loading VM details', e);
        vmInfoData.value = null;
    } finally {
        vmInfoLoading.value = false;
    }
};

// Helper: Extract disk entries from VM config
const getDiskEntries = (config: any): Record<string, string> => {
    if (!config) return {};
    const diskKeys = ['scsi0', 'scsi1', 'scsi2', 'scsi3', 'virtio0', 'virtio1', 'virtio2', 'ide0', 'ide1', 'ide2', 'sata0', 'sata1', 'rootfs', 'mp0', 'mp1', 'mp2'];
    const result: Record<string, string> = {};
    for (const key of diskKeys) {
        if (config[key]) {
            result[key] = config[key];
        }
    }
    return result;
};

// Helper: Extract network entries from VM config
const getNetworkEntries = (config: any): Record<string, string> => {
    if (!config) return {};
    const netKeys = ['net0', 'net1', 'net2', 'net3'];
    const result: Record<string, string> = {};
    for (const key of netKeys) {
        if (config[key]) {
            result[key] = config[key];
        }
    }
    return result;
};

// --- Snapshot Logic ---

const openSnapshotModal = (vm: VM) => {
    selectedVM.value = vm;
    showSnapshotModal.value = true;
    snapshotTab.value = 'proxmox';
    loadPveSnapshots();
    loadZfsSnapshots(); // Also load ZFS snapshots
    loadAvailableNodes(); // Preload nodes for potential clone
};

// PVE
const loadPveSnapshots = async () => {
    if (!selectedVM.value) return;
    snapshotsLoading.value = true;
    try {
        const res = await vmsService.getVMDetails(selectedVM.value.node_id!, selectedVM.value.vmid);
        snapshots.value = res.data?.snapshots?.list || [];
    } catch (e) { console.error(e); } 
    finally { snapshotsLoading.value = false; }
};

const createPveSnapshot = async () => {
    if(!selectedVM.value) return;
    try {
        await vmsService.createSnapshot(selectedVM.value.node_id!, selectedVM.value.vmid, newSnapName.value, newSnapDesc.value, newSnapRam.value);
        showCreatePveSnapshot.value = false;
        newSnapName.value = '';
        loadPveSnapshots();
    } catch(e) { alert('Errore: ' + e); }
};

const rollbackPveSnapshot = async (name: string) => {
    if(!confirm(`Rollback a ${name}?`)) return;
    try {
        await vmsService.rollbackSnapshot(selectedVM.value!.node_id!, selectedVM.value!.vmid, name, true);
        alert('Rollback avviato.');
        loadPveSnapshots();
    } catch(e) { alert('Errore: ' + e); }
};

const deletePveSnapshot = async (name: string) => {
    if(!confirm(`Eliminare ${name}?`)) return;
    try {
        await vmsService.deleteSnapshot(selectedVM.value!.node_id!, selectedVM.value!.vmid, name);
        loadPveSnapshots();
    } catch(e) { alert('Errore: ' + e); }
};

// ZFS
const openZFSSection = () => {
    snapshotTab.value = 'zfs';
    loadZfsSnapshots();
};

const loadZfsSnapshots = async () => {
    if (!selectedVM.value) return;
    zfsLoading.value = true;
    try {
        const res = await vmsService.getZFSSnapshots(selectedVM.value.node_id!, selectedVM.value.vmid);
        zfsSnapshots.value = res.data;
    } catch(e) { console.error(e); }
    finally { zfsLoading.value = false; }
};

const rollbackZfs = async (snap: ZFSSnapshot) => {
    if(!confirm(`ATTENZIONE: Rollback distruttivo ZFS a ${snap.name} per dataset ${snap.dataset} (e altri). Confermi?`)) return;
    try {
        await vmsService.restoreZFSSnapshot(selectedVM.value!.node_id!, selectedVM.value!.vmid, snap.name, 'rollback');
        alert('Rollback ZFS eseguito.');
    } catch(e) { alert('Errore: ' + e); }
};

const deleteZfsSnapshot = async (snap: ZFSSnapshot) => {
    if(!confirm(`Eliminare lo snapshot "${snap.name}" da tutti i dischi della VM? Questa azione è irreversibile.`)) return;
    try {
        await vmsService.deleteZfsSnapshot(selectedVM.value!.node_id!, selectedVM.value!.vmid, snap.name);
        alert('Snapshot eliminato.');
        loadZfsSnapshots();
    } catch(e) { alert('Errore: ' + e); }
};

const startZfsCloneWizard = (snap: ZFSSnapshot) => {
    zfsCloneSelection.value = snap;
    zfsCloneOptions.value = {
        newVmid: Number(selectedVM.value!.vmid) + 100,
        newName: `${selectedVM.value!.name}-clone`
    };
    showZfsCloneModal.value = true;
};

const confirmZfsClone = async () => {
    if (!selectedVM.value || !zfsCloneSelection.value) return;
    const newId = zfsCloneOptions.value.newVmid;
    if (!newId) { alert("Devi specificare un Nuovo VMID per il clone."); return; }
    
    if (!confirm(`Sei sicuro di voler clonare la VM ${selectedVM.value.vmid} su VM ${newId}?\nQuesta operazione creerà nuovi dischi.`)) return;
    
    try {
        await vmsService.restoreZFSSnapshot(
            selectedVM.value.node_id!, 
            selectedVM.value.vmid, 
            zfsCloneSelection.value.name, 
            'clone', 
            newId
        );
        alert(`Clone ZFS avviato per VM ${newId}. La nuova VM apparirà nella lista.`);
        showZfsCloneModal.value = false;
        loadVMs();
    } catch(e) { alert('Errore: ' + e); }
};

// Sanoid
const openSanoidSection = () => {
    snapshotTab.value = 'sanoid';
    loadSanoidConfig();
};

const loadSanoidConfig = async () => {
    if (!selectedVM.value) return;
    sanoidLoading.value = true;
    try {
        const res = await vmsService.getSanoidConfig(selectedVM.value.node_id!, selectedVM.value.vmid);
        sanoidConfig.value = res.data;
    } catch(e) { console.error(e); }
    finally { sanoidLoading.value = false; }
};

const saveSanoidConfig = async () => {
    if (!selectedVM.value) return;
    sanoidSaving.value = true;
    try {
        await vmsService.updateSanoidConfig(selectedVM.value.node_id!, selectedVM.value.vmid, sanoidConfig.value);
        alert('Configurazione salvata!');
    } catch(e) { alert('Errore: ' + e); }
    finally { sanoidSaving.value = false; }
};

const triggerSanoidSnapshot = async () => {
    if (!selectedVM.value) return;
    sanoidTriggering.value = true;
    try {
        await vmsService.snapshotNow(selectedVM.value.node_id!, selectedVM.value.vmid);
        // Switch to Proxmox tab and reload ZFS snapshots
        snapshotTab.value = 'proxmox'; // Ensure we view the list that contains manual snapshots (ZFS list is inside PVE snapshots tab area in current UI? No, wait.)
        // Actually ZFS snapshots are in 'zfs' tab or below PVE?
        // Current UI: 
        // <div v-if="snapshotTab === 'proxmox'"> PVE Snaps ... </div>
        // <div v-if="snapshotTab === 'zfs'"> ZFS Snaps ... </div>
        // Wait, the ZFS list is displayed when snapshotTab is 'proxmox' too? No.
        // Let's check where ZFS snapshots are rendered.
        // They are rendered inside `snapshotTab === 'proxmox'` section in previous edits?
        // Let's check the template structure first to be sure where to switch.
        
        // Based on recent edits, ZFS snapshots were moved inside the main snapshot modal along with PVE ones?
        // Or separate tab?
        // Line 186 in recent view:
        // <div v-if="groupedZfsSnapshots.length > 0"> inside the modal body?
        // If so, we just need to refresh.
        
        await loadZfsSnapshots();
        alert('✅ Snapshot Manuale eseguito! Verifica la lista ZFS Snapshots qui sopra.');
    } catch(e) { 
        alert('❌ Errore durante lo snapshot: ' + e);
    }
    finally { sanoidTriggering.value = false; }
};

// --- Nodes & Storages for Wizards ---

const loadAvailableNodes = async () => {
    try {
        const res = await nodesService.getNodes();
        // Filter to PVE nodes only (not PBS)
        availableNodes.value = (res.data || []).filter((n: any) => n.node_type !== 'pbs');
    } catch(e) { console.error('Failed to load nodes', e); }
};

const loadTargetStorages = async () => {
    if (!restoreOptions.value.targetNodeId) return;
    try {
        const res = await nodesService.getStorages(restoreOptions.value.targetNodeId);
        targetStorages.value = res.data || [];
    } catch(e) { 
        console.error('Failed to load storages', e);
        targetStorages.value = []; 
    }
};

// --- Backup Logic ---

const openBackupModal = (vm: VM) => {
    selectedVM.value = vm;
    showBackupModal.value = true;
    restoreMode.value = false;
    loadBackups();
};

const loadBackups = async () => {
    if (!selectedVM.value) return;
    backupsLoading.value = true;
    try {
        const res = await vmsService.getBackups(selectedVM.value.node_id!, selectedVM.value.vmid);
        backups.value = res.data || [];
    } catch (e) {
        console.error(e);
        backups.value = [];
    } finally {
        backupsLoading.value = false;
    }
};

const startRestoreWizard = async (bak: Backup) => {
    restoreSelection.value = bak;
    restoreOptions.value = {
        targetNodeId: selectedVM.value!.node_id!,
        storage: '',
        newVmid: null,
        start: true
    };
    restoreMode.value = true;
    await loadAvailableNodes();
    await loadTargetStorages();
};

const executeRestore = async () => {
    if(!selectedVM.value || !restoreSelection.value) return;
    
    if(!confirm("Confermi l'avvio del ripristino?")) return;
    
    // Logic override if new VMID provided? Not supported by current restoreBackup signature fully in backend?
    // Wait, backend restore uses 'vmid' path param. If we want new VMID, we need to pass it? 
    // Backend qmrestore command `qmrestore backup vmid`.
    // My backend `restore_vm_backup` uses `vmid` from URL path!
    // Issue: If I want to restore to a NEW VMID, I need to call the endpoint on the TARGET NODE but with WHICH VMID?
    // The endpoint is `/node/{node_id}/vm/{vmid}/restore`.
    // If I want a NEW VMID, I should probably use `vmid` param as the TARGET vmid? 
    // BUT the backend endpoint assumes `vmid` is the EXISTING VM unless I change logic.
    // Actually `qmrestore backup vmid` creates `vmid` if it doesn't exist? Yes.
    // So I should call the endpoint with the *TARGET* VMID in the URL path?
    // But `vmid` in URL checks if VM exists for access control?
    // My backend check: `node = db.query(Node)... check_node_access...`
    // It doesn't check if VM exists in DB for this endpoint specifically unless I look at `get_vm_details`.
    // `restore_vm_backup` uses `vmid` argument for the command.
    
    // So:
    // If user wants NEW VMID, I should call endpoint `/node/{TARGET}/vm/{NEWID}/restore`.
    // But does NEWID exist in DB? No.
    // Does backend require VM to exist in DB?
    // `restore_vm_backup` checks node. It does NOT query VMRegistry. It just uses `vmid` int.
    // So it should work!
    
    const targetVmid = restoreOptions.value.newVmid || selectedVM.value.vmid;
    
    try {
        await vmsService.restoreBackup(
             restoreOptions.value.targetNodeId, 
             Number(targetVmid),
             restoreSelection.value.volid,
             restoreSelection.value.storage_id || 'pbs', 
             restoreOptions.value.storage || null,
             restoreOptions.value.start,
             restoreOptions.value.targetNodeId // Pass target node explicit
         );
         alert('Restore avviato!');
         showBackupModal.value = false;
    } catch(e) {
        alert('Errore restore: ' + e);
    }
};

// Utils
const formatSize = (bytes: number) => {
    if (!bytes) return '-';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
};
const formatDate = (ts: number) => {
    return new Date(ts * 1000).toLocaleString();
};

const getPolicyBadge = (name: string) => {
    if (name.includes('hourly')) return { text: 'Hourly', class: 'badge-purple' };
    if (name.includes('daily')) return { text: 'Daily', class: 'badge-success' };
    if (name.includes('weekly')) return { text: 'Weekly', class: 'badge-warning' };
    if (name.includes('monthly')) return { text: 'Monthly', class: 'badge-danger' };
    if (name.includes('yearly')) return { text: 'Yearly', class: 'badge-info' };
    return { text: 'Manual', class: 'badge-secondary' };
};
</script>

<style scoped>
/* Reuse existing styles plus new ones */
.vms-page { max-width: 1800px; margin: 0 auto; padding: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; }
.header-actions { display: flex; gap: 12px; }
.search-input { width: 300px; padding: 8px 16px; border: 1px solid var(--border-color); border-radius: 6px; background: var(--bg-secondary); color: var(--text-primary); }

.data-table { width: 100%; border-collapse: collapse; }
.data-table th { text-align: left; padding: 16px; color: var(--text-secondary); font-weight: 600; font-size: 0.85rem; border-bottom: 2px solid var(--border-color); white-space: nowrap; }
.data-table td { padding: 16px; border-bottom: 1px solid var(--border-color); vertical-align: middle; }
.text-accent { color: var(--accent-primary); }
.text-secondary { color: var(--text-secondary); }
.text-xs { font-size: 0.75rem; }
.text-right { text-align: right; }
.font-mono { font-family: monospace; }
.font-bold { font-weight: 700; }
.w-full { width: 100%; }

.badge { padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
.badge-info { background: rgba(59, 130, 246, 0.1); color: #60a5fa; }
.badge-warning { background: rgba(245, 158, 11, 0.1); color: #fbbf24; }
.badge-success { background: rgba(16, 185, 129, 0.1); color: #34d399; }
.badge-secondary { background: rgba(107, 114, 128, 0.1); color: #9ca3af; }
.badge-purple { background: rgba(139, 92, 246, 0.1); color: #a78bfa; }
.status-dot { height: 8px; width: 8px; border-radius: 50%; background-color: currentColor; display: inline-block; margin-right: 6px; }

.btn { padding: 8px 16px; border-radius: 6px; font-weight: 500; cursor: pointer; border: none; transition: all 0.2s; }
.btn-sm { padding: 6px 12px; font-size: 0.85rem; }
.btn-xs { padding: 4px 8px; font-size: 0.75rem; }
.btn-primary { background: var(--accent-primary); color: white; }
.btn-secondary { background: var(--bg-secondary); color: var(--text-primary); border: 1px solid var(--border-color); }
.btn-danger { background: rgba(239, 68, 68, 0.1); color: #f87171; }
.btn-warning { background: rgba(245, 158, 11, 0.1); color: #fbbf24; }
.btn-cyan { background: rgba(6, 182, 212, 0.1); color: #22d3ee; }
.btn-dark { background: rgba(0,0,0,0.3); color: var(--text-primary); }

.card { background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 8px; overflow: hidden; }
.bg-dark-soft { background: var(--bg-secondary); }

/* Stats */
.grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.stat-mini { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 16px; }
.stat-value { font-size: 1.5rem; font-weight: 700; color: var(--text-primary); }
.stat-label { font-size: 0.8rem; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; }

/* Tabs */
.tabs { display: flex; border-bottom: 2px solid var(--border-color); gap: 20px; }
.tab-btn { background: none; border: none; padding: 10px 0; color: var(--text-secondary); cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -2px; }
.tab-btn.active { color: var(--accent-primary); border-bottom-color: var(--accent-primary); }

/* Switch */
.switch { position: relative; display: inline-block; width: 40px; height: 24px; }
.switch input { opacity: 0; width: 0; height: 0; }
.slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #ccc; transition: .4s; border-radius: 24px; }
.slider:before { position: absolute; content: ""; height: 16px; width: 16px; left: 4px; bottom: 4px; background-color: white; transition: .4s; border-radius: 50%; }
input:checked + .slider { background-color: var(--accent-primary); }
input:checked + .slider:before { transform: translateX(16px); }

/* Forms */
.form-input { width: 100%; padding: 8px; border: 1px solid var(--border-color); background: var(--bg-primary); color: var(--text-primary); border-radius: 4px; }
.form-input-sm { width: 60px; padding: 4px; border: 1px solid var(--border-color); background: var(--bg-primary); color: var(--text-primary); border-radius: 4px; }
.form-select { width: 100%; padding: 8px; border: 1px solid var(--border-color); background: var(--bg-primary); color: var(--text-primary); border-radius: 4px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }

.btn-group { display: flex; gap: 4px; }

/* VM Info Modal Styles */
.vm-details-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    max-height: calc(80vh - 150px);
    overflow-y: auto;
    padding-right: 8px;
}
.vm-details-grid .detail-card {
    background: var(--bg-hover);
    padding: 16px;
    border-radius: 8px;
    border: 1px solid var(--border-color);
}
.vm-details-grid .detail-card h4 {
    margin: 0 0 12px 0;
    color: var(--text-secondary);
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-bottom: 1px solid var(--border-color);
    padding-bottom: 8px;
}
.vm-details-grid .full-width { grid-column: 1 / -1; }
.vm-details-grid .simple-table { width: 100%; font-size: 0.9rem; }
.vm-details-grid .simple-table td { padding: 4px 0; }
.vm-details-grid .simple-table td:first-child { color: var(--text-secondary); width: 40%; }
.disk-item, .network-item { 
    padding: 8px; 
    background: var(--bg-secondary); 
    border-radius: 4px; 
    margin-bottom: 6px;
    word-break: break-all;
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
@keyframes spin { to { transform: rotate(360deg); } }
</style>
