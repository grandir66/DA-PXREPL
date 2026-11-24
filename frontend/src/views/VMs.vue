<template>
 <div class="vms-page">
 <PageHeader :title="t('vm.titolo')" :subtitle="t('vm.sottotitolo')" icon="monitor">
 <template #actions>
 <button class="btn btn-secondary btn-sm" @click="loadVMs(false)" :disabled="loading">
 <Icon name="refresh" :size="14" :class="{ spin: loading }" />
 {{ loading ? t('comune.aggiornoInCorso') : t('comune.aggiorna') }}
 </button>
 <button class="btn btn-primary btn-sm" @click="loadVMs(true)" :disabled="loading" :title="t('vm.dalVivoAiuto')">
 {{ t('vm.dalVivo') }}
 </button>
 <input type="text" v-model="search" :placeholder="t('vm.cerca')" class="form-input search-input">
 </template>
 </PageHeader>

 <!-- Stats Summary -->
 <div class="grid-3 mb-4">
 <div class="card stat-mini">
 <div class="stat-value">{{ vms.length }}</div>
 <div class="stat-label">{{ t('vm.totali') }}</div>
 </div>
 <div class="card stat-mini">
 <div class="stat-value text-success">{{ runningCount }}</div>
 <div class="stat-label">{{ t('vm.accese') }}</div>
 </div>
 <div class="card stat-mini">
 <div class="stat-value text-secondary">{{ vms.length - runningCount }}</div>
 <div class="stat-label">{{ t('vm.spente') }}</div>
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
 {{ t('comune.nome') }} <span v-if="sortKey === 'name'">{{ sortDesc ? '↓' : '↑' }}</span>
 </th>
 <th width="120" style="min-width: 120px;" @click="sortBy('node')" class="cursor-pointer hover:text-accent select-none">
 Host <span v-if="sortKey === 'node'">{{ sortDesc ? '↓' : '↑' }}</span>
 </th>
 <th width="100" @click="sortBy('status')" class="cursor-pointer hover:text-accent select-none">
 {{ t('comune.stato') }} <span v-if="sortKey === 'status'">{{ sortDesc ? '↓' : '↑' }}</span>
 </th>
 <th width="180">{{ t('vm.allocazioni') }}</th>
 <th width="420" class="text-right">{{ t('comune.azioni') }}</th>
 </tr>
 </thead>
 <tbody>
 <tr v-for="vm in filteredVMs" :key="vm.vmid + '-' + vm.node">
 <td class="font-mono font-bold text-accent">{{ vm.vmid }}</td>
 <td style="width: 250px;">
 <div class="flex items-center gap-2">
 <span class="font-medium text-lg cursor-pointer hover:text-accent border-b border-dashed border-secondary hover:border-accent" @click="openVMInfoModal(vm)">
 {{ vm.name }}
 </span>
 <span class="badge text-xs" :class="vm.type === 'lxc' ? 'badge-warning' : 'badge-info'">
 {{ vm.type === 'lxc' ? 'CT' : 'VM' }}
 </span>
 </div>
 <div v-if="vm.net0_ip" class="text-xs font-mono text-secondary mt-1">
 {{ vm.net0_ip }}
 </div>
 </td>
 <td>
 <router-link :to="'/nodes?openInfo=' + vm.node" class="badge badge-outline text-sm no-underline hover:bg-accent hover:text-white transition-colors" :title="t('vm.vaiNodo')">
 {{ vm.node }}
 </router-link>
 </td>
 <td>
 <span class="badge" :class="vm.status === 'running' ? 'badge-success' : 'badge-secondary'">
 <span class="status-dot"></span>
 {{ vm.status === 'running' ? 'ON' : 'OFF' }}
 </span>
 <div v-if="vm.loading" class="text-xs text-accent mt-1">{{ t('stato.running') }}…</div>
 </td>
 <td class="resource-cell">
 <!-- Allocated Resources (Text) -->
 <div class="text-xs space-y-1">
 <span class="font-mono text-primary font-bold mr-2">{{ t('nodi.core', { n: vm.maxcpu || 1 }) }}</span>
 <span class="font-mono text-primary font-bold mr-2">{{ formatSize(vm.maxmem || 0) }} RAM</span>
 <span class="font-mono text-primary" v-if="vm.maxdisk">{{ formatSize(vm.maxdisk || 0) }} HD</span>
 </div>
 </td>
 <td class="text-right">
 <div class="flex justify-end gap-2">
 <button class="btn btn-sm btn-outline" @click="openVMInfoModal(vm)" :title="t('vm.dettagliVm')">
 {{ t('nodi.info') }}
 </button>
 <button class="btn btn-sm btn-cyan" @click="openBackupModal(vm)" title="Backup PBS">
 Backup PBS
 </button>
 <button class="btn btn-sm btn-primary" @click="openReplicationWizard(vm)" :title="t('vm.configuraReplica')">
 {{ t('vm.replica') }}
 </button>
 <button class="btn btn-sm btn-dark" @click="openSnapshotModal(vm)" title="Snapshot">
 Snapshot
 </button>
 <!-- Start/Stop mini actions -->
 <button v-if="vm.status === 'stopped'" 
 class="btn btn-success btn-xs btn-icon" 
 @click="manageState(vm, 'start')"
 :disabled="vm.loading"
 :title="t('vm.avviaVm')">
 <Icon name="play" :size="14" />
 </button>
 <button v-else 
 class="btn btn-danger btn-xs btn-icon" 
 @click="manageState(vm, 'shutdown')"
 :disabled="vm.loading"
 :title="t('vm.spegniVm')">
 <Icon name="stop" :size="14" />
 </button>
 </div>
 </td>
 </tr>
 <tr v-if="filteredVMs.length === 0 && !loading">
 <td colspan="6" class="empty-state-cell text-center py-8 text-secondary">{{ t('vm.nessuna') }}</td>
 </tr>
 </tbody>
 </table>
 </div>
 </div>

 <!-- Snapshot Modal -->
 <ModalDialog v-model:visible="showSnapshotModal" :title="t('vm.snapTitolo', { nome: selectedVM?.name })" width="900px">
 <div class="tabs mb-4">
 <button class="tab-btn" :class="{ active: snapshotTab === 'proxmox' }" @click="snapshotTab = 'proxmox'">{{ t('vm.snapProxmox') }}</button>
 <button class="tab-btn" :class="{ active: snapshotTab === 'sanoid' }" @click="openSanoidSection()">{{ t('vm.snapSanoid') }}</button>
 </div>

 <!-- Proxmox Snapshots Tab -->
 <div v-if="snapshotTab === 'proxmox'">
 <div class="action-bar mb-4 bg-dark-soft p-3 rounded flex justify-between items-center">
 <span class="text-sm text-secondary">{{ t('vm.snapStandard') }}</span>
 <button class="btn btn-primary btn-sm" @click="showCreatePveSnapshot = true" v-if="!showCreatePveSnapshot">{{ t('vm.snapCrea') }}</button>
 </div>

 <!-- Create Form -->
 <div v-if="showCreatePveSnapshot" class="card p-4 mb-4 border-accent">
 <h4 class="mb-3">{{ t('vm.snapNuovo') }}</h4>
 <div class="grid-2 gap-4 mb-3">
 <input v-model="newSnapName" :placeholder="t('vm.snapNome')" class="form-input">
 <div class="flex items-center">
 <label class="flex items-center gap-2 cursor-pointer">
 <input type="checkbox" v-model="newSnapRam"> 
 <span>{{ t('vm.snapRam') }}</span>
 </label>
 </div>
 </div>
 <input v-model="newSnapDesc" :placeholder="t('vm.snapDescr')" class="form-input mb-3">
 <div class="flex gap-2 justify-end">
 <button class="btn btn-secondary btn-sm" @click="showCreatePveSnapshot = false">{{ t('comune.annulla') }}</button>
 <button class="btn btn-primary btn-sm" @click="createPveSnapshot">{{ t('vm.snapCreaBtn') }}</button>
 </div>
 </div>

 <!-- PVE Snapshots List -->
 <div class="snapshot-list">
 <div v-if="snapshotsLoading" class="text-center p-4">{{ t('comune.caricamento') }}</div>
 <div v-else-if="allSnapshots.length === 0" class="text-center text-secondary p-4">{{ t('vm.snapNessuno') }}</div>
 <div v-else>
 <!-- PVE Snapshots Section -->
 <div v-if="snapshots.length > 0" class="mb-4">
 <h5 class="text-sm font-bold text-secondary mb-2"><Icon name="camera" :size="20" /> {{ t('vm.snapVmProxmox') }}</h5>
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
 <button class="btn btn-warning btn-xs" @click="rollbackPveSnapshot(snap.name)">{{ t('vm.rollback') }}</button>
 <button class="btn btn-danger btn-xs" @click="deletePveSnapshot(snap.name)">{{ t('comune.elimina') }}</button>
 </div>
 </div>
 </div>
 
 <!-- ZFS/Sanoid Snapshots Section -->
 <div v-if="groupedZfsSnapshots.length > 0">
 <h5 class="text-sm font-bold text-secondary mb-2"><Icon name="zap" :size="20" /> {{ t('vm.snapZfs') }}</h5>
 <div v-for="snap in groupedZfsSnapshots" :key="'zfs-' + snap.name" class="snapshot-item card flex justify-between items-center p-3 mb-2">
 <div>
 <div class="font-bold flex items-center gap-2">
 {{ snap.name }}
 <span class="badge badge-info text-xs">ZFS</span>
 <span class="badge badge-outline text-xs" :title="t('vm.dischiCoinvolti')">{{ t('vm.nDischi', { n: snap.datasetsCount }) }}</span>
 <span class="badge text-xs" :class="getPolicyBadge(snap.name).class">{{ getPolicyBadge(snap.name).text }}</span>
 </div>
 <div class="text-xs text-secondary">{{ snap.creation || t('comune.nd') }}</div>
 </div>
 <div class="btn-group">
 <button class="btn btn-cyan btn-xs" @click="startZfsCloneWizard(snap)">{{ t('vm.clona') }}</button>
 <button class="btn btn-warning btn-xs" @click="rollbackZfs(snap)">{{ t('vm.rollback') }}</button>
 <button class="btn btn-danger btn-xs" @click="deleteZfsSnapshot(snap)">{{ t('comune.elimina') }}</button>
 </div>
 </div>
 </div>
 </div>
 </div>
 </div>



 <!-- Sanoid Config Tab -->
 <div v-if="snapshotTab === 'sanoid'">
 <div v-if="sanoidLoading" class="text-center p-8">{{ t('vm.sanLettura') }}</div>
 <div v-else class="sanoid-form">
 <div class="flex items-center gap-3 mb-6 p-4 bg-dark-soft rounded">
 <label class="switch">
 <input type="checkbox" v-model="sanoidConfig.enable">
 <span class="slider round"></span>
 </label>
 <div>
 <div class="font-bold">{{ t('vm.sanAbilita') }}</div>
 <div class="text-xs text-secondary">{{ t('vm.sanAbilitaSotto') }}</div>
 </div>
 </div>

 <div v-if="sanoidConfig.enable" class="grid-2 gap-6">
 <div class="card p-4">
 <h4 class="mb-3">{{ t('vm.sanModello') }}</h4>
 <select v-model="sanoidConfig.template" class="form-select w-full mb-3">
 <option value="production">{{ t('vm.sanProd') }}</option>
 <option value="backup">{{ t('vm.sanBackup') }}</option>
 <option value="test">{{ t('vm.sanTest') }}</option>
 </select>
 <div class="flex gap-4">
 <label class="flex items-center gap-2">
 <input type="checkbox" v-model="sanoidConfig.autosnap"> {{ t('vm.sanAutosnap') }}
 </label>
 <label class="flex items-center gap-2">
 <input type="checkbox" v-model="sanoidConfig.autoprune"> {{ t('vm.sanAutoprune') }}
 </label>
 </div>
 </div>

 <div class="card p-4">
 <h4 class="mb-3">{{ t('vm.sanConserv') }}</h4>
 <div class="grid-2 gap-2 text-sm">
 <label>{{ t('vm.san_orari') }} <input type="number" v-model="sanoidConfig.hourly" class="form-input-sm"></label>
 <label>{{ t('vm.san_giornalieri') }} <input type="number" v-model="sanoidConfig.daily" class="form-input-sm"></label>
 <label>{{ t('vm.san_settimanali') }} <input type="number" v-model="sanoidConfig.weekly" class="form-input-sm"></label>
 <label>{{ t('vm.san_mensili') }} <input type="number" v-model="sanoidConfig.monthly" class="form-input-sm"></label>
 <label>{{ t('vm.san_annuali') }} <input type="number" v-model="sanoidConfig.yearly" class="form-input-sm"></label>
 </div>
 </div>
 </div>
 </div>
 </div>

 <template #footer>
 <div v-if="snapshotTab === 'sanoid'" class="w-full flex justify-between">
 <button class="btn btn-cyan" @click="triggerSanoidSnapshot" :disabled="sanoidTriggering">
 {{ sanoidTriggering ? t('vm.sanCreazione') : t('vm.sanAdesso') }}
 </button>
 <button class="btn btn-primary" @click="saveSanoidConfig" :disabled="sanoidSaving">
 {{ sanoidSaving ? t('comune.salvataggio') : t('vm.sanSalva') }}
 </button>
 </div>
 <div v-if="snapshotTab === 'sanoid'" class="w-full text-center mt-2">
 <p class="text-xs text-secondary">
 <Icon name="info" :size="14" /> <i18n-t keypath="vm.sanNota" tag="span"><template #nota><strong>{{ t('vm.nota') }}</strong></template><template #cron><code>cron</code></template><template #sanoid><code>sanoid</code></template></i18n-t>
 </p>
 </div>
 <div v-else class="w-full flex justify-end">
 <button class="btn btn-secondary" @click="showSnapshotModal = false">{{ t('comune.chiudi') }}</button>
 </div>
 </template>
 </ModalDialog>

 <!-- Backup Modal -->
 <ModalDialog v-model:visible="showBackupModal" :title="t('vm.bkTitolo', { nome: selectedVM?.name })" width="900px">
 <div v-if="!restoreMode">
 <!-- List View -->
 <div class="mb-4 flex justify-between items-center">
 <div class="text-sm text-secondary">{{ t('vm.bkDisponibili') }}</div>
 <div>
 <!-- Future: Backup Now button -->
 </div>
 </div>
 
 <div v-if="backupsLoading" class="text-center p-8">{{ t('vm.bkCaricamento') }}</div>
 <div v-else-if="backups.length === 0" class="text-center p-8 text-secondary border border-dashed border-gray-700 rounded">
 {{ t('vm.bkNessuno') }}
 </div>
 <div v-else class="backup-list">
 <table class="w-full text-sm">
 <thead>
 <tr class="text-left text-secondary border-b border-gray-700">
 <th class="p-2">{{ t('vm.bkQuando') }}</th>
 <th class="p-2">{{ t('vm.bkDimensione') }}</th>
 <th class="p-2">Storage</th>
 <th class="p-2 text-right">{{ t('comune.azioni') }}</th>
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
 <button class="btn btn-primary btn-xs" @click="startRestoreWizard(bak)">{{ t('vm.bkRipristina') }}</button>
 </td>
 </tr>
 </tbody>
 </table>
 </div>
 </div>

 <div v-else class="restore-wizard">
 <!-- Restore Wizard -->
 <div class="mb-4 pb-2 border-b border-gray-700 flex justify-between items-center">
 <h3>{{ zfsCloneMode ? t('vm.wizClone') : t('vm.wizRipristino') }}</h3>
 <button class="btn-xs btn-secondary" @click="restoreMode = false; zfsCloneMode = false; showBackupModal = zfsCloneMode ? false : true">{{ t('comune.indietro') }}</button>
 </div>
 
 <div class="grid-2 gap-8">
 <div class="wizard-info">
 <h4>{{ zfsCloneMode ? t('vm.wizSnapOrigine') : t('vm.wizBkOrigine') }}</h4>
 <div class="p-3 bg-dark-soft rounded mb-4 text-sm space-y-2">
 <div><strong>VM:</strong> {{ selectedVM?.name }} ({{ selectedVM?.vmid }})</div>
 <div v-if="!zfsCloneMode"><strong>Backup:</strong> {{ formatDate(restoreSelection?.['backup-time'] || 0) }}</div>
 <div v-else><strong>Snapshot:</strong> {{ zfsCloneSelection?.name }}</div>
 <div class="text-xs break-all text-secondary">{{ !zfsCloneMode ? restoreSelection?.volid : zfsCloneSelection?.dataset }}</div>
 <div v-if="zfsCloneMode" class="text-xs text-secondary">{{ t('vm.nDataset', { n: zfsCloneSelection?.datasetsCount || 1 }) }}</div>
 </div>
 
 <div class="alert alert-warning" v-if="!restoreOptions.newVmid">
 <Icon name="alert-triangle" :size="14" /> <strong>{{ t('vm.attenzione') }}</strong> {{ t('vm.wizSovrascrive') }}
 </div>
 <div class="alert alert-info" v-else>
 <Icon name="info" :size="14" /> <i18n-t keypath="vm.wizNuovaVm" tag="span"><template #id><strong>{{ restoreOptions.newVmid }}</strong></template></i18n-t>
 </div>
 </div>
 
 <div class="wizard-form space-y-4">
 <div>
 <label class="block text-sm text-secondary mb-1">{{ t('vm.wizNodo') }}</label>
 <select v-model="restoreOptions.targetNodeId" class="form-select w-full" @change="loadTargetStorages">
 <option v-for="node in availableNodes" :key="node.id" :value="node.id">
 {{ node.name }} ({{ node.hostname }})
 </option>
 </select>
 </div>

 <div>
 <label class="block text-sm text-secondary mb-1">{{ t('vm.wizStorage') }}</label>
 <select v-model="restoreOptions.storage" class="form-select w-full">
 <option value="">{{ t('vm.wizStorageDefault') }}</option>
 <option v-for="st in targetStorages" :key="st.name" :value="st.name">
 {{ st.name }} ({{ st.type }}) - {{ t('vm.gbLiberi', { n: st.avail_gb || '?' }) }}
 </option>
 </select>
 </div>
 
 <div>
 <label class="block text-sm text-secondary mb-1">{{ t('vm.wizNuovoVmid') }}</label>
 <input v-model.number="restoreOptions.newVmid" type="number" class="form-input" :placeholder="String(selectedVM?.vmid)">
 <div class="text-xs text-secondary mt-1">{{ t('vm.wizNuovoVmidNota') }}</div>
 </div>

 <div>
 <label class="block text-sm text-secondary mb-1">{{ t('vm.wizNome') }}</label>
 <input v-model="restoreOptions.newName" type="text" class="form-input" :placeholder="selectedVM?.name">
 <div class="text-xs text-secondary mt-1">{{ t('vm.wizNomeNota') }}</div>
 </div>
 
 <div class="pt-2">
 <label class="flex items-center gap-2 cursor-pointer">
 <input type="checkbox" v-model="restoreOptions.start"> 
 <span>{{ t('vm.wizAvvia') }}</span>
 </label>
 </div>
 </div>
 </div>
 </div>

 <template #footer>
 <div v-if="restoreMode || zfsCloneMode"> 
 <!-- Footer for Wizard -->
 <div class="flex justify-end gap-2">
 <button class="btn btn-secondary" @click="restoreMode = false; zfsCloneMode = false; showBackupModal = zfsCloneMode ? false : true">{{ t('comune.annulla') }}</button>
 <button v-if="!zfsCloneMode" class="btn btn-danger" @click="executeRestore">{{ t('vm.wizAvviaRipristino') }}</button>
 <button v-else class="btn btn-cyan" @click="confirmZfsClone">{{ t('vm.wizAvviaClone') }}</button>
 </div>
 </div>
 <div v-else class="flex justify-end">
 <button class="btn btn-secondary" @click="showBackupModal = false">{{ t('comune.chiudi') }}</button>
 </div>
 </template>
 </ModalDialog>

 <!-- ZFS Clone Modal (Dedicated) -->
 <ModalDialog :visible="showZfsCloneModal" @close="showZfsCloneModal = false" :title="t('vm.wizClone')" width="600px">
 <div class="zfs-clone-wizard">
 <div class="alert alert-warning mb-4">
 <Icon name="alert-triangle" :size="14" /> <strong>{{ t('vm.attenzione') }}</strong> {{ t('vm.cloneAvviso') }}
 </div>
 
 <div class="p-4 bg-dark-soft rounded mb-4 space-y-2">
 <div><strong>{{ t('vm.vmOrigine') }}</strong> {{ selectedVM?.name }} ({{ selectedVM?.vmid }})</div>
 <div><strong>Snapshot:</strong> {{ zfsCloneSelection?.name }}</div>
 <div class="text-xs text-secondary">{{ t('vm.nDataset', { n: zfsCloneSelection?.datasetsCount || 1 }) }}</div>
 </div>

 <div class="space-y-4">
 <div>
 <label class="block text-sm text-secondary mb-1">{{ t('vm.nuovoVmid') }} <span class="text-danger">*</span></label>
 <input v-model.number="zfsCloneOptions.newVmid" type="number" class="form-input" :placeholder="t('vm.es999')">
 </div>
 <div>
 <label class="block text-sm text-secondary mb-1">{{ t('vm.nomeNuovaVm') }}</label>
 <input v-model="zfsCloneOptions.newName" type="text" class="form-input" :placeholder="selectedVM?.name + '-clone'">
 </div>
 </div>
 </div>
 
 <template #footer>
 <div class="flex justify-between w-full">
 <button class="btn btn-secondary" @click="showZfsCloneModal = false">{{ t('comune.annulla') }}</button>
 <button class="btn btn-primary" @click="confirmZfsClone" :disabled="!zfsCloneOptions.newVmid">
 {{ t('vm.creaClone') }}
 </button>
 </div>
 </template>
 </ModalDialog>

 <!-- VM Info Modal -->
 <ModalDialog v-model:visible="showVMInfoModal" :title="t('vm.detTitolo', { nome: vmInfoData?.name || selectedVM?.name })" width="800px">
 <div v-if="vmInfoLoading" class="text-center p-8">
 <div class="spinner-lg mb-4"></div>
 <p>{{ t('vm.detCaricamento') }}</p>
 </div>
 <div v-else-if="vmInfoData" class="vm-details-grid">
 <!-- Basic Info -->
 <div class="detail-card">
 <h4><Icon name="monitor" :size="20" /> {{ t('vm.detBase') }}</h4>
 <table class="simple-table">
 <tr><td>VMID:</td><td><strong class="text-accent">{{ vmInfoData.vmid }}</strong></td></tr>
 <tr><td>{{ t('vm.detNome') }}</td><td>{{ vmInfoData.config?.name || selectedVM?.name }}</td></tr>
 <tr><td>{{ t('vm.detTipo') }}</td><td><span class="badge" :class="vmInfoData.type === 'lxc' ? 'badge-warning' : 'badge-info'">{{ vmInfoData.type === 'lxc' ? t('vm.container') : t('vm.vmQemu') }}</span></td></tr>
 <tr><td>{{ t('comune.statoDuePunti') }}</td><td><span class="badge" :class="selectedVM?.status === 'running' ? 'badge-success' : 'badge-secondary'">{{ selectedVM?.status }}</span></td></tr>
 <tr><td>{{ t('vm.detNodo') }}</td><td>{{ selectedVM?.node }}</td></tr>
 </table>
 </div>

 <!-- Resources -->
 <div class="detail-card">
 <h4><Icon name="settings" :size="20" /> {{ t('vm.detRisorse') }}</h4>
 <table class="simple-table">
 <tr><td>{{ t('vm.detCore') }}</td><td><strong>{{ vmInfoData.config?.cores || vmInfoData.config?.cpulimit || 1 }}</strong></td></tr>
 <tr v-if="vmInfoData.config?.sockets"><td>{{ t('vm.detSocket') }}</td><td>{{ vmInfoData.config.sockets }}</td></tr>
 <tr><td>{{ t('vm.detMemoria') }}</td><td><strong>{{ vmInfoData.config?.memory || vmInfoData.config?.swap || 0 }} MB</strong></td></tr>
 <tr v-if="vmInfoData.config?.balloon"><td>Balloon:</td><td>{{ vmInfoData.config.balloon }} MB</td></tr>
 <tr v-if="vmInfoData.config?.cpu"><td>{{ t('vm.detTipoCpu') }}</td><td class="text-xs">{{ vmInfoData.config.cpu }}</td></tr>
 </table>
 </div>

 <!-- Disks -->
 <div class="detail-card full-width">
 <h4><Icon name="hard-drive" :size="20" /> {{ t('vm.detDischi') }}</h4>
 <div class="disk-list">
 <div v-for="(value, key) in getDiskEntries(vmInfoData.config)" :key="key" class="disk-item">
 <span class="font-bold">{{ key }}:</span>
 <span class="text-sm text-secondary ml-2">{{ value }}</span>
 </div>
 <div v-if="Object.keys(getDiskEntries(vmInfoData.config)).length === 0" class="text-secondary text-sm">
 {{ t('vm.detNessunDisco') }}
 </div>
 </div>
 </div>

 <!-- Network -->
 <div class="detail-card full-width">
 <h4><Icon name="globe" :size="20" /> {{ t('vm.detRete') }}</h4>
 <div class="network-list">
 <div v-for="(value, key) in getNetworkEntries(vmInfoData.config)" :key="key" class="network-item">
 <span class="font-bold">{{ key }}:</span>
 <span class="text-sm text-secondary ml-2">{{ value }}</span>
 </div>
 <div v-if="selectedVM?.net0_ip" class="mt-2">
 <span class="text-xs text-secondary">{{ t('vm.detIp') }}</span>
 <span class="font-mono text-accent ml-2">{{ selectedVM.net0_ip }}</span>
 </div>
 <div v-if="Object.keys(getNetworkEntries(vmInfoData.config)).length === 0" class="text-secondary text-sm">
 {{ t('vm.detNessunaRete') }}
 </div>
 </div>
 </div>

 <!-- Boot & Options -->
 <div class="detail-card">
 <h4><Icon name="wrench" :size="20" /> {{ t('vm.detOpzioni') }}</h4>
 <table class="simple-table">
 <tr v-if="vmInfoData.config?.boot"><td>{{ t('vm.detBoot') }}</td><td class="text-xs">{{ vmInfoData.config.boot }}</td></tr>
 <tr v-if="vmInfoData.config?.onboot !== undefined"><td>{{ t('vm.detAvvioAuto') }}</td><td><Icon :name="vmInfoData.config.onboot ? 'check-circle' : 'x-circle'" :size="14" :class="vmInfoData.config.onboot ? 'text-success' : 'text-danger'" /> {{ vmInfoData.config.onboot ? t('vm.si') : t('vm.no') }}</td></tr>
 <tr v-if="vmInfoData.config?.ostype"><td>{{ t('vm.detOs') }}</td><td>{{ vmInfoData.config.ostype }}</td></tr>
 <tr v-if="vmInfoData.config?.machine"><td>{{ t('vm.detMacchina') }}</td><td class="text-xs">{{ vmInfoData.config.machine }}</td></tr>
 <tr v-if="vmInfoData.config?.bios"><td>BIOS:</td><td>{{ vmInfoData.config.bios }}</td></tr>
 </table>
 </div>

 <!-- Identita' replica (solo per VM registrate da DA-PXREPL) -->
 <div v-if="vmInfoData.replica_identity?.is_replica" class="detail-card full-width">
 <h4><Icon name="shield" :size="20" /> {{ t('vm.idTitolo') }}</h4>
 <table class="simple-table">
 <tr v-if="vmInfoData.replica_identity.source_vmid"><td>{{ t('vm.idOrigine') }}</td><td>VM <strong>{{ vmInfoData.replica_identity.source_vmid }}</strong><span v-if="vmInfoData.replica_identity.source_hostname"> {{ t('vm.suHost', { host: vmInfoData.replica_identity.source_hostname }) }}</span></td></tr>
 <tr><td>{{ t('vm.idUuidAttuale') }}</td><td class="text-xs font-mono">{{ vmInfoData.replica_identity.current_smbios_uuid || '—' }}</td></tr>
 <tr><td>{{ t('vm.idUuidOriginale') }}</td><td class="text-xs font-mono">{{ vmInfoData.replica_identity.source_smbios_uuid }}</td></tr>
 <tr><td>{{ t('comune.statoDuePunti') }}</td><td>
 <span v-if="vmInfoData.replica_identity.dr_attivo" class="badge badge-warning">{{ t('vm.idDrAttivo') }}</span>
 <span v-else class="badge badge-success">{{ t('vm.idReplica') }}</span>
 </td></tr>
 </table>
 <div class="mt-3 flex items-center gap-3">
 <button class="btn btn-sm btn-warning" :disabled="vmInfoData.replica_identity.dr_attivo || vmInfoData.status === 'running'" @click="openActivateDR" :title="t('vm.idDrAiuto')">
 <Icon name="alert-triangle" :size="14" /> {{ t('vm.idAttivaDr') }}
 </button>
 <span class="text-xs text-secondary">{{ t('vm.idDrNota') }}</span>
 </div>
 </div>

 <!-- Ritorno all'originale (3.27.0): solo repliche che stanno, o sono state, al posto dell'originale -->
 <div v-if="ritornoVisibile && ritorno" class="detail-card full-width">
 <h4><Icon name="rotate-ccw" :size="20" /> {{ t('vm.ritTitolo') }}</h4>
 <p class="text-sm mb-3">
 <span class="badge" :class="ritornoVista.classe"><Icon :name="ritornoVista.icona" :size="12" /> {{ ritornoVista.parola }}</span>
 <span class="ml-2">{{ ritornoVista.frase }}</span>
 <span v-if="ritorno.dettaglio.aggiornato" class="text-xs text-secondary ml-2">({{ ritorno.dettaglio.aggiornato }})</span>
 </p>
 <table class="simple-table">
 <tr><td>{{ t('vm.rit_replica') }}</td><td><i18n-t keypath="vm.ritRigaVm" tag="span"><template #vmid><strong>{{ ritorno.replica.vmid }}</strong></template><template #nome>{{ ritorno.replica.nome }}</template><template #nodo>{{ ritorno.replica.nodo }}</template><template #stato>{{ statoVmParola(ritorno.replica.stato) }}</template></i18n-t></td></tr>
 <tr><td>{{ t('vm.rit_originale') }}</td><td><i18n-t keypath="vm.ritRigaVm" tag="span"><template #vmid><strong>{{ ritorno.originale.vmid }}</strong></template><template #nome>{{ ritorno.originale.nome }}</template><template #nodo>{{ ritorno.originale.nodo }}</template><template #stato>{{ statoVmParola(ritorno.originale.stato) }}</template></i18n-t></td></tr>
 <tr><td>{{ t('vm.ritConfig') }}</td><td>
 <span v-if="ritorno.fotografia.presente">{{ t('vm.ritFotoPresente', { quando: ritorno.fotografia.del }) }}</span>
 <span v-else><Icon name="alert-triangle" :size="12" /> {{ t('vm.ritFotoAssente') }}</span>
 </td></tr>
 </table>
 <table class="simple-table mt-3">
 <tr><th class="text-left">{{ t('vm.ritDisco') }}</th><th class="text-left">{{ t('vm.ritDa') }}</th><th class="text-left">{{ t('vm.ritA') }}</th><th class="text-left">{{ t('vm.ritDiscoAttuale') }}</th></tr>
 <tr v-for="d in ritorno.piano.dischi" :key="d.job_id">
 <td>{{ d.disk_name || '—' }}</td>
 <td class="text-xs font-mono">{{ d.da }}</td>
 <td class="text-xs font-mono">{{ d.a }}</td>
 <td class="text-xs">
 <span v-if="ritorno.dettaglio.dischi?.[d.job_id]?.vecchio">{{ t('vm.ritMessoDaParte') }} <span class="font-mono">{{ ritorno.dettaglio.dischi?.[d.job_id]?.vecchio }}</span></span>
 <span v-else-if="ritorno.dettaglio.dischi?.[d.job_id]">{{ t('vm.ritNonCera') }}</span>
 <span v-else-if="d.rinomina">{{ t('vm.ritVerraMesso') }}</span>
 <span v-else>{{ t('vm.ritNonCe') }}</span>
 </td>
 </tr>
 </table>
 <ul v-if="ritornoAvvisi.length" class="text-sm mt-3 space-y-1">
 <li v-for="a in ritornoAvvisi" :key="a"><Icon name="alert-triangle" :size="12" /> {{ a }}</li>
 </ul>
 <div class="mt-3 flex items-center gap-3">
 <button class="btn btn-sm btn-primary" :disabled="!ritornoPuoPreparare" @click="openRitorno('prepara')">
 <Icon name="refresh" :size="14" /> {{ t('vm.ritPreparaBtn') }}
 </button>
 <button class="btn btn-sm btn-warning" :disabled="ritorno.stato !== 'pronto' || ritorno.in_corso" @click="openRitorno('completa')">
 <Icon name="rotate-ccw" :size="14" /> {{ t('vm.ritCompletaBtn') }}
 </button>
 <span v-if="!ritorno.piano.possibile && !ritornoAttivo" class="text-xs text-secondary">{{ t('vm.ritNonPossibile', { motivo: ritorno.piano.motivo }) }}</span>
 <span v-else-if="ritorno.stato === 'pronto'" class="text-xs text-secondary">{{ t('vm.ritRipetere') }}</span>
 </div>
 </div>

 <!-- Replica registrata prima della 3.22.0: stessa identita' della sorgente -->
 <div v-else-if="vmInfoData.replica_identity?.da_riallineare" class="detail-card full-width">
 <h4><Icon name="shield" :size="20" /> {{ t('vm.idTitolo') }}</h4>
 <p class="text-sm">
 <span class="badge badge-warning">{{ t('vm.idDaRiallineare') }}</span>
 <i18n-t keypath="vm.idVecchie" tag="span"><template #vmid><strong>{{ vmInfoData.replica_identity.source_vmid }}</strong></template></i18n-t>
 </p>
 <div class="mt-3 flex items-center gap-3">
 <button class="btn btn-sm btn-primary" :disabled="riallineaBusy || vmInfoData.status === 'running'" @click="riallineaIdentita">
 <Icon name="shield" :size="14" /> {{ riallineaBusy ? t('vm.inCorso') : t('vm.idRiallinea') }}
 </button>
 <span class="text-xs text-secondary">{{ t('vm.idRiallineaNota') }}</span>
 </div>
 </div>

 <!-- Snapshots Summary -->
 <div class="detail-card">
 <h4><Icon name="camera" :size="20" /> {{ t('vm.snapRiquadro') }}</h4>
 <div v-if="vmInfoData.snapshots?.list?.length">
 <div class="text-2xl font-bold text-accent mb-2">{{ vmInfoData.snapshots.list.length }}</div>
 <div class="text-sm text-secondary">{{ t('vm.snapDisponibili') }}</div>
 <div class="mt-2 text-xs">
 {{ t('vm.snapUltimo', { nome: vmInfoData.snapshots.list[vmInfoData.snapshots.list.length - 1]?.name }) }}
 </div>
 </div>
 <div v-else class="text-secondary text-sm">{{ t('vm.snapZero') }}</div>
 </div>

 <!-- Raw Config Toggle -->
 <div class="detail-card full-width">
 <details>
 <summary class="cursor-pointer text-secondary"><Icon name="clipboard" :size="14" /> {{ t('vm.configGrezza') }}</summary>
 <pre class="text-xs mt-2" style="max-height: 300px; overflow: auto; background: var(--bg-secondary); padding: 8px; border-radius: 4px;">{{ JSON.stringify(vmInfoData.config, null, 2) }}</pre>
 </details>
 </div>
 </div>
 <div v-else class="text-center text-secondary p-8">
 {{ t('vm.nessunDato') }}
 </div>
 
 <template #footer>
 <button class="btn btn-secondary" @click="showVMInfoModal = false">{{ t('comune.chiudi') }}</button>
 </template>
 </ModalDialog>

 <!-- Attiva DR (identita' replica) -->
 <ModalDialog :visible="showRitorno" @close="showRitorno = false" :title="ritornoAzione === 'prepara' ? t('vm.ritPreparaTitolo') : t('vm.ritCompletaTitolo')" width="600px">
 <div v-if="ritornoAzione === 'prepara'" class="alert alert-info mb-4">
 <Icon name="info" :size="14" /> <strong>{{ t('vm.ritPrepForte') }}</strong> {{ t('vm.ritPrepTesto') }}
 </div>
 <div v-else class="alert alert-warning mb-4">
 <Icon name="alert-triangle" :size="14" /> <strong>{{ t('vm.ritComplForte') }}</strong> {{ t('vm.ritComplTesto') }}
 </div>
 <div class="p-4 bg-dark-soft rounded mb-4 space-y-2" v-if="ritorno">
 <div><strong>{{ t('vm.rit_replica') }}</strong> {{ t('vm.ritVmSu', { vmid: ritorno.replica.vmid, nome: ritorno.replica.nome, nodo: ritorno.replica.nodo }) }}</div>
 <div><strong>{{ t('vm.rit_originale') }}</strong> {{ t('vm.ritVmSu', { vmid: ritorno.originale.vmid, nome: ritorno.originale.nome, nodo: ritorno.originale.nodo }) }}</div>
 </div>
 <div class="space-y-4">
 <div v-if="ritornoAzione === 'completa'">
 <label class="block text-sm text-secondary mb-1">{{ t('vm.ritAttesa') }}</label>
 <input v-model.number="ritornoAttesa" type="number" min="30" max="1800" class="form-input">
 </div>
 <div>
 <label class="block text-sm text-secondary mb-1"><i18n-t keypath="vm.scriviPerConfermare" tag="span"><template #parola><code>RITORNA</code></template></i18n-t> <span class="text-danger">*</span></label>
 <input v-model="ritornoConferma" type="text" class="form-input" placeholder="RITORNA" autocomplete="off">
 </div>
 </div>
 <template #footer>
 <div class="flex justify-between w-full">
 <button class="btn btn-secondary" @click="showRitorno = false">{{ t('comune.annulla') }}</button>
 <button class="btn" :class="ritornoAzione === 'prepara' ? 'btn-primary' : 'btn-warning'" @click="confirmRitorno" :disabled="ritornoConferma !== 'RITORNA' || ritornoBusy">
 {{ ritornoBusy ? t('vm.inCorso') : (ritornoAzione === 'prepara' ? t('vm.ritPrepara') : t('vm.ritCompleta')) }}
 </button>
 </div>
 </template>
 </ModalDialog>

 <ModalDialog :visible="showActivateDR" @close="showActivateDR = false" :title="t('vm.drTitolo')" width="600px">
 <div class="alert alert-warning mb-4">
 <Icon name="alert-triangle" :size="14" /> <strong>{{ t('vm.drCosaFa') }}</strong> {{ t('vm.drCosaFaTesto') }} <strong>{{ t('vm.drCosaNonFa') }}</strong> {{ t('vm.drCosaNonFaTesto') }}
 </div>
 <div class="p-4 bg-dark-soft rounded mb-4 space-y-2">
 <div><strong>{{ t('vm.rit_replica') }}</strong> {{ selectedVM?.name }} ({{ selectedVM?.vmid }})</div>
 <div class="text-xs font-mono"><strong>{{ t('vm.idUuidAttuale') }}</strong> {{ vmInfoData?.replica_identity?.current_smbios_uuid }}</div>
 <div class="text-xs font-mono"><strong>{{ t('vm.drUuidNuovo') }}</strong> {{ vmInfoData?.replica_identity?.source_smbios_uuid }}</div>
 </div>
 <div class="space-y-4">
 <div>
 <label class="block text-sm text-secondary mb-1"><i18n-t keypath="vm.scriviPerConfermare" tag="span"><template #parola><code>ATTIVA</code></template></i18n-t> <span class="text-danger">*</span></label>
 <input v-model="activateDROptions.confirm" type="text" class="form-input" placeholder="ATTIVA" autocomplete="off">
 </div>
 <label class="flex items-center gap-2 text-sm">
 <input type="checkbox" v-model="activateDROptions.ripristina_vmgenid">
 <span><i18n-t keypath="vm.drVmgenid" tag="span"><template #vmgenid><code>vmgenid</code></template></i18n-t> <span class="text-secondary">{{ t('vm.drVmgenidNota') }}</span></span>
 </label>
 <label class="flex items-center gap-2 text-sm">
 <input type="checkbox" v-model="activateDROptions.force">
 <span>{{ t('vm.drForza') }} <span class="text-danger">{{ t('vm.drForzaNota') }}</span></span>
 </label>
 </div>
 <template #footer>
 <div class="flex justify-between w-full">
 <button class="btn btn-secondary" @click="showActivateDR = false">{{ t('comune.annulla') }}</button>
 <button class="btn btn-warning" @click="confirmActivateDR" :disabled="activateDROptions.confirm !== 'ATTIVA' || activateDRBusy">
 {{ activateDRBusy ? t('vm.inCorso') : t('vm.drAttiva') }}
 </button>
 </div>
 </template>
 </ModalDialog>

 <!-- Modale unificato VM-centrico (sostituisce il vecchio ReplicationWizard) -->
 <JobModal
 v-model:visible="showReplicationWizard"
 mode="syncoid"
 :preset-vm="selectedReplicationVM"
 @saved="onReplicationSaved"
 />

 </div>
</template>

<script setup lang="ts">
import apiClient from '../services/api';
import { useToast, errorMessage } from '../stores/toast';
import { ref, onMounted, onUnmounted, computed, watch } from 'vue';
import { confirmDangerous } from '../stores/confirm';
import { useRoute } from 'vue-router';
import PageHeader from '../components/ui/PageHeader.vue';
import Icon from '../components/ui/Icon.vue';
import { useI18n } from 'vue-i18n';
import { dataOra } from '../utils/formato';
import vmsService, { type VM, type Snapshot, type Backup, type SanoidConfig, type ZFSSnapshot, type RitornoStato } from '../services/vms';
import nodesService from '../services/nodes';
import ModalDialog from '../components/ModalDialog.vue';
import JobModal from '../components/jobs/JobModal.vue';

const toast = useToast()
const { t, te } = useI18n()

// State
const vms = ref<VM[]>([]);
const loading = ref(false);
const search = ref('');
const selectedVM = ref<VM | null>(null);

// VM Info Modal State
const showVMInfoModal = ref(false);
const vmInfoData = ref<any>(null);
const showActivateDR = ref(false);
const activateDRBusy = ref(false);
const activateDROptions = ref({ confirm: '', force: false, ripristina_vmgenid: false });
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
const snapshotTab = ref<'proxmox' | 'sanoid' | 'zfs'>('proxmox');
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
 selectedReplicationVM.value = {
 vmid: vm.vmid,
 name: vm.name,
 type: vm.type,
 node_id: vm.node_id,
 };
 showReplicationWizard.value = true;
};

const onReplicationSaved = () => {
 showReplicationWizard.value = false;
 loadVMs();
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
 result = result.filter(v => 
 v.name?.toLowerCase().includes(term) || 
 v.vmid?.toString().includes(term) ||
 v.node?.toLowerCase().includes(term)
 );
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

const route = useRoute();

onMounted(async () => {
 await loadVMs();
 
 // Check for query param to auto-open VM details
 const openVmId = route.query.openVm as string;
 if (openVmId) {
 const vm = vms.value.find(v => String(v.vmid) === openVmId);
 if (vm) {
 openVMInfoModal(vm);
 }
 }

 // Check for search query param
 if (route.query.search) {
 search.value = route.query.search as string;
 }
});

const loadVMs = async (forceRefresh: boolean = false) => {
 loading.value = true;
 try {
 const res = await vmsService.getVMs(forceRefresh);
 vms.value = res.data;
 } catch (e) {
 console.error('Error loading VMs', e);
 } finally {
 loading.value = false;
 }
};

const manageState = async (vm: VM, action: any) => {
 if (!await confirmDangerous(t('vm.confAzione', { azione: te(`vm.azione.${action}`) ? t(`vm.azione.${action}`) : action, nome: vm.name }))) return;
 vm.loading = true;
 try {
 await vmsService.manageState(vm.node_id!, vm.vmid, action);
 setTimeout(() => loadVMs(), 2000);
 } catch (e) {
 toast.error(t('vm.errAzione'), errorMessage(e));
 vm.loading = false;
 }
};

// --- VM Info Modal ---
const openVMInfoModal = async (vm: VM) => {
 selectedVM.value = vm;
 vmInfoData.value = null;
 ritorno.value = null;
 vmInfoLoading.value = true;
 showVMInfoModal.value = true;
 
 try {
 const res = await vmsService.getVMDetails(vm.node_id!, vm.vmid, vm.type);
 vmInfoData.value = res.data;
 void caricaRitorno();
 } catch (e) {
 console.error('Error loading VM details', e);
 vmInfoData.value = null;
 } finally {
 vmInfoLoading.value = false;
 }
};

// --- Riallinea identita' (repliche pre-3.22.0, 3.25.0) ---
const riallineaBusy = ref(false);
const riallineaIdentita = async () => {
 if (!selectedVM.value) return;
 riallineaBusy.value = true;
 try {
 const res = await apiClient.post(`/vms/node/${selectedVM.value.node_id}/vm/${selectedVM.value.vmid}/riallinea-identita`);
 toast.success(t('vm.idRiallineata'), res.data.messaggio);
 await openVMInfoModal(selectedVM.value);
 } catch (e) {
 toast.error(t('vm.idRifiutato'), errorMessage(e));
 } finally {
 riallineaBusy.value = false;
 }
};

// --- Ritorno all'originale (3.27.0) ---
const ritorno = ref<RitornoStato | null>(null);
const showRitorno = ref(false);
const ritornoAzione = ref<'prepara' | 'completa'>('prepara');
const ritornoConferma = ref('');
const ritornoAttesa = ref(180);
const ritornoBusy = ref(false);
let ritornoTimer: ReturnType<typeof setTimeout> | null = null;

const ritornoAttivo = computed(() => !!ritorno.value && ['preparazione', 'scambio'].includes(ritorno.value.stato) && ritorno.value.in_corso);
const ritornoVisibile = computed(() => {
 const r = ritorno.value;
 if (!r) return false;
 const ident = vmInfoData.value?.replica_identity;
 return r.stato !== 'nessuno' || !!ident?.dr_attivo || vmInfoData.value?.status === 'running';
});
const ritornoPuoPreparare = computed(() => {
 const r = ritorno.value;
 return !!r && !r.in_corso && r.piano.possibile;
});
const ritornoAvvisi = computed(() => {
 const r = ritorno.value;
 if (!r) return [];
 return Array.from(new Set([...(r.piano.avvisi || []), ...(r.dettaglio.avvisi || [])]));
});
// Stati distinti da icona e parola, non dal solo colore.
const ritornoVista = computed(() => {
 const r = ritorno.value;
 if (!r) return { icona: 'info', parola: '', frase: '', classe: '' };
 if (r.interrotto) return { icona: 'rotate-ccw', parola: t('vm.rs_interrotto'), frase: t('vm.rf_interrotto'), classe: 'badge-warning' };
 switch (r.stato) {
 case 'preparazione': return { icona: 'refresh', parola: t('vm.rs_preparazione'), frase: t('vm.rf_preparazione'), classe: 'badge-info' };
 case 'pronto': return { icona: 'check', parola: t('vm.rs_pronto'), frase: t('vm.rf_pronto'), classe: 'badge-success' };
 case 'scambio': return { icona: 'refresh', parola: t('vm.rs_scambio'), frase: t('vm.rf_scambio'), classe: 'badge-warning' };
 case 'completato': return { icona: 'check-circle', parola: t('vm.rs_completato'), frase: r.dettaglio.messaggio || t('vm.rf_completato'), classe: 'badge-success' };
 case 'fallito': return { icona: 'alert-triangle', parola: t('vm.rs_fallito'), frase: r.dettaglio.messaggio || r.dettaglio.errore || '', classe: 'badge-danger' };
 default: return { icona: 'info', parola: t('vm.rs_daPreparare'), frase: t('vm.rf_daPreparare'), classe: 'badge-secondary' };
 }
});
const statoVmParola = (stato: string) => (te(`vm.statoVm.${stato}`) ? t(`vm.statoVm.${stato}`) : stato);

const fermaRitornoTimer = () => {
 if (ritornoTimer) { clearTimeout(ritornoTimer); ritornoTimer = null; }
};
const caricaRitorno = async () => {
 fermaRitornoTimer();
 const vm = selectedVM.value;
 // Si chiede per ogni VM qemu: chi non è la replica di un job risponde 404 senza toccare i nodi.
 if (!vm || vm.type !== 'qemu') { ritorno.value = null; return; }
 try {
 const res = await vmsService.getRitorno(vm.node_id!, vm.vmid);
 if (selectedVM.value !== vm) return;
 ritorno.value = res.data;
 if (showVMInfoModal.value && ['preparazione', 'scambio'].includes(res.data.stato) && res.data.in_corso) {
 ritornoTimer = setTimeout(caricaRitorno, 5000);
 }
 } catch {
 // 404 = nessun job di replica collegato: la scheda non si mostra
 ritorno.value = null;
 }
};
watch(showVMInfoModal, (aperta) => { if (!aperta) fermaRitornoTimer(); });
onUnmounted(fermaRitornoTimer);

const openRitorno = (azione: 'prepara' | 'completa') => {
 ritornoAzione.value = azione;
 ritornoConferma.value = '';
 ritornoAttesa.value = 180;
 showRitorno.value = true;
};
const confirmRitorno = async () => {
 const vm = selectedVM.value;
 if (!vm || ritornoConferma.value !== 'RITORNA') return;
 ritornoBusy.value = true;
 try {
 if (ritornoAzione.value === 'prepara') {
 await vmsService.preparaRitorno(vm.node_id!, vm.vmid);
 toast.success(t('vm.ritAvviataPrep'), t('vm.ritAvviataPrepDett'));
 } else {
 await vmsService.completaRitorno(vm.node_id!, vm.vmid, ritornoAttesa.value);
 toast.success(t('vm.ritAvviatoScambio'), t('vm.ritAvviatoScambioDett'));
 }
 showRitorno.value = false;
 setTimeout(caricaRitorno, 1500);
 } catch (e) {
 toast.error(t('vm.ritRifiutato'), errorMessage(e));
 } finally {
 ritornoBusy.value = false;
 }
};

// --- Attiva DR (identita' replica, 3.22.0) ---
const openActivateDR = () => {
 activateDROptions.value = { confirm: '', force: false, ripristina_vmgenid: false };
 showActivateDR.value = true;
};

const confirmActivateDR = async () => {
 if (!selectedVM.value || activateDROptions.value.confirm !== 'ATTIVA') return;
 activateDRBusy.value = true;
 try {
 const res = await vmsService.activateDR(selectedVM.value.node_id!, selectedVM.value.vmid, {
 confirm: 'ATTIVA',
 force: activateDROptions.value.force,
 ripristina_vmgenid: activateDROptions.value.ripristina_vmgenid,
 vm_type: selectedVM.value.type,
 });
 showActivateDR.value = false;
 toast.success(t('vm.drAttivato'), `smbios1 → ${res.data.smbios1_dopo}. ${res.data.avviso}`);
 await openVMInfoModal(selectedVM.value);
 } catch (e) {
 toast.error(t('vm.drRifiutato'), errorMessage(e));
 } finally {
 activateDRBusy.value = false;
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
 } catch(e) { toast.error(t('comune.errore'), errorMessage(e)); }
};

const rollbackPveSnapshot = async (name: string) => {
 if(!await confirmDangerous(t('vm.confRollback', { nome: name }))) return;
 try {
 await vmsService.rollbackSnapshot(selectedVM.value!.node_id!, selectedVM.value!.vmid, name, true);
 toast.success(t('vm.rollbackAvviato'));
 loadPveSnapshots();
 } catch(e) { toast.error(t('comune.errore'), errorMessage(e)); }
};

const deletePveSnapshot = async (name: string) => {
 if(!await confirmDangerous(t('vm.confElimina', { nome: name }))) return;
 try {
 await vmsService.deleteSnapshot(selectedVM.value!.node_id!, selectedVM.value!.vmid, name);
 loadPveSnapshots();
 } catch(e) { toast.error(t('comune.errore'), errorMessage(e)); }
};

// ZFS

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
 if(!await confirmDangerous(t('vm.confRollbackZfs', { nome: snap.name, dataset: snap.dataset }))) return;
 try {
 await vmsService.restoreZFSSnapshot(selectedVM.value!.node_id!, selectedVM.value!.vmid, snap.name, 'rollback');
 toast.success(t('vm.rollbackZfsFatto'));
 } catch(e) { toast.error(t('comune.errore'), errorMessage(e)); }
};

const deleteZfsSnapshot = async (snap: ZFSSnapshot) => {
 if(!await confirmDangerous(t('vm.confEliminaSnap', { nome: snap.name }))) return;
 try {
 await vmsService.deleteZfsSnapshot(selectedVM.value!.node_id!, selectedVM.value!.vmid, snap.name);
 toast.success(t('vm.snapEliminato'));
 loadZfsSnapshots();
 } catch(e) { toast.error(t('comune.errore'), errorMessage(e)); }
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
 if (!newId) { toast.warning(t('vm.cloneServeVmid')); return; }
 
 if (!await confirmDangerous(t('vm.confClone', { da: selectedVM.value.vmid, a: newId }))) return;
 
 try {
 await vmsService.restoreZFSSnapshot(
 selectedVM.value.node_id!, 
 selectedVM.value.vmid, 
 zfsCloneSelection.value.name, 
 'clone', 
 newId
 );
 toast.success(t('vm.cloneAvviato'), t('vm.cloneInCreazione', { id: newId }));
 showZfsCloneModal.value = false;
 loadVMs();
 } catch(e) { toast.error(t('comune.errore'), errorMessage(e)); }
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
 toast.success(t('vm.configSalvata'));
 } catch(e) { toast.error(t('comune.errore'), errorMessage(e)); }
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
 toast.success(t('vm.snapManuale'), t('vm.snapManualeDett'));
 } catch(e) { 
 toast.error(t('vm.errSnapshot'), errorMessage(e));
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
 const raw = res.data?.storages || [];
 targetStorages.value = raw.map((s: any) => ({
  name: s.storage || s.name,
  type: s.type,
  avail_gb: s.avail_gb ?? (s.avail ? Math.round(s.avail / (1024 ** 3)) : undefined),
 }));
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
 newName: '',
 start: true
 };
 restoreMode.value = true;
 await loadAvailableNodes();
 await loadTargetStorages();
};

const executeRestore = async () => {
 if(!selectedVM.value || !restoreSelection.value) return;
 
 if(!await confirmDangerous(t('vm.confRipristino'))) return;
 
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
 toast.success(t('vm.ripristinoAvviato'));
 showBackupModal.value = false;
 } catch(e) {
 toast.error(t('vm.errRipristino'), errorMessage(e));
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
 return dataOra(ts * 1000, { dateStyle: 'short', timeStyle: 'medium' });
};

const getPolicyBadge = (name: string) => {
 if (name.includes('hourly')) return { text: t('vm.san_orari'), class: 'badge-purple' };
 if (name.includes('daily')) return { text: t('vm.san_giornalieri'), class: 'badge-success' };
 if (name.includes('weekly')) return { text: t('vm.san_settimanali'), class: 'badge-warning' };
 if (name.includes('monthly')) return { text: t('vm.san_mensili'), class: 'badge-danger' };
 if (name.includes('yearly')) return { text: t('vm.san_annuali'), class: 'badge-info' };
 return { text: t('vm.san_manuale'), class: 'badge-secondary' };
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
.btn-primary { background: var(--accent-primary); color: var(--color-text-primary); }
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
.slider:before { position: absolute; content: ""; height: 16px; width: 16px; left: 4px; bottom: 4px; background-color: var(--color-text-primary); transition: .4s; border-radius: 50%; }
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
