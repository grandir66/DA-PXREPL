<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal-card wizard-modal">
      <div class="wizard-header">
        <h2>+ Nuova Replica VM</h2>
        <button class="close-btn" @click="$emit('close')">&times;</button>
      </div>

      <!-- Phase 1: Method + Nodes + VM List -->
      <div v-if="!showConfigModal" class="wizard-body">
        <!-- Method Selection -->
        <div class="section-label">🔧 Metodo di Sincronizzazione</div>
        <div class="method-cards">
          <div 
            class="method-card" 
            :class="{ active: form.mode === 'syncoid' }" 
            @click="form.mode = 'syncoid'"
          >
            <div class="method-icon">🗄️</div>
            <div class="method-name">ZFS / Syncoid</div>
            <div class="method-desc">Replica con ZFS send/receive</div>
          </div>
          <div 
            class="method-card" 
            :class="{ active: form.mode === 'pbs' }" 
            @click="form.mode = 'pbs'"
          >
            <div class="method-icon">📦</div>
            <div class="method-name">PBS Recovery</div>
            <div class="method-desc">Backup + Restore via PBS</div>
          </div>
          <div 
            class="method-card" 
            :class="{ active: form.mode === 'pve', disabled: true }" 
            @click="form.mode = 'pve'"
            title="Richiede nodi nello stesso cluster"
          >
            <div class="method-icon">🔄</div>
            <div class="method-name">PVE Native</div>
            <div class="method-desc">Replica nativa Proxmox</div>
          </div>
        </div>

        <!-- Node Selection -->
        <div class="node-row">
          <div class="node-select-group">
            <div class="section-label">📍 Nodo Sorgente</div>
            <select v-model="form.source_node_id" @change="loadVMs" class="node-select">
              <option :value="null">Seleziona nodo...</option>
              <option v-for="node in pveNodes" :key="node.id" :value="node.id">
                {{ node.name }} ({{ node.hostname }})
              </option>
            </select>
          </div>
          
          <div class="node-select-group">
            <div class="section-label">📦 Nodo Destinazione</div>
            <select v-model="form.dest_node_id" class="node-select" @change="onDestNodeChange">
              <option :value="null">Seleziona destinazione...</option>
              <template v-if="form.mode === 'pbs'">
                <option v-for="node in pveNodes" :key="node.id" :value="node.id">
                  {{ node.name }} ({{ node.hostname }})
                </option>
              </template>
              <template v-else>
                <option v-for="node in pveNodes.filter(n => n.id !== form.source_node_id)" :key="node.id" :value="node.id">
                  {{ node.name }} ({{ node.hostname }})
                </option>
              </template>
            </select>
          </div>
        </div>

        <!-- PBS Node (only for PBS mode) -->
        <div v-if="form.mode === 'pbs' && form.source_node_id" class="pbs-node-row">
          <div class="section-label">🖥️ Server PBS</div>
          <select v-model="form.pbs_node_id" class="node-select" @change="loadPBSDatastores">
            <option :value="null">Seleziona PBS Server...</option>
            <option v-for="node in pbsNodes" :key="node.id" :value="node.id">
              {{ node.name }} ({{ node.hostname }})
            </option>
          </select>
        </div>

        <!-- VM List -->
        <div v-if="form.source_node_id && form.dest_node_id" class="vm-list-section">
          <div class="section-label">🖥️ Seleziona VM da Replicare</div>
          <div class="vm-table-container">
            <table class="vm-table">
              <thead>
                <tr>
                  <th>VMID</th>
                  <th>NOME</th>
                  <th>TIPO</th>
                  <th>STATO</th>
                  <th>AZIONE</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="loadingVMs">
                  <td colspan="5" class="loading-cell">Caricamento VM...</td>
                </tr>
                <tr v-else-if="vms.length === 0">
                  <td colspan="5" class="empty-cell">Nessuna VM trovata sul nodo sorgente</td>
                </tr>
                <tr v-for="vm in vms" :key="vm.vmid">
                  <td class="vmid-cell">{{ vm.vmid }}</td>
                  <td class="name-cell">{{ vm.name }}</td>
                  <td><span class="badge badge-type">{{ vm.type }}</span></td>
                  <td><span class="badge" :class="vm.status === 'running' ? 'badge-running' : 'badge-stopped'">{{ vm.status }}</span></td>
                  <td>
                    <button class="btn-configure" @click="openConfigModal(vm)">
                      Configura →
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- Phase 2: Configuration Modal -->
      <div v-if="showConfigModal" class="config-modal-body">
        <div class="config-header">
          <div class="config-title">
            <span class="config-icon">⚙️</span> Configura Replica
          </div>
          <button class="btn-back" @click="showConfigModal = false">← Cambia VM</button>
        </div>
        
        <div class="config-vm-info">
          <span class="vm-badge">🖥️ {{ selectedVm?.name }} ({{ selectedVm?.vmid }})</span>
        </div>

        <div class="config-sections">
          <!-- Disks Section (Syncoid only) -->
          <div v-if="form.mode === 'syncoid'" class="config-section">
            <div class="section-header">🗄️ Dischi da Replicare</div>
            <table class="disks-table">
              <thead>
                <tr>
                  <th>DISCO</th>
                  <th>DATASET ZFS</th>
                  <th>DIMENSIONE</th>
                  <th>REPLICA</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="disk in vmDisks" :key="disk.disk_name">
                  <td>{{ disk.disk_name }}</td>
                  <td class="dataset-cell">{{ disk.dataset || 'N/A' }}</td>
                  <td><span class="size-badge">{{ disk.size }}</span></td>
                  <td><input type="checkbox" v-model="disk.selected" :checked="true"></td>
                </tr>
                <tr v-if="vmDisks.length === 0">
                  <td colspan="4" class="empty-cell">Nessun disco ZFS trovato</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- Destination Section -->
          <div class="config-section">
            <div class="section-header">📦 Destinazione</div>
            <div class="form-grid">
              <!-- Pool ZFS (Syncoid) -->
              <div v-if="form.mode === 'syncoid'" class="form-group">
                <label>Pool ZFS Destinazione</label>
                <select v-model="form.dest_pool" class="form-control" :disabled="loadingDestPools">
                  <option value="">{{ loadingDestPools ? 'Caricamento...' : 'Seleziona pool' }}</option>
                  <option v-for="pool in destPools" :key="pool" :value="pool">{{ pool }}</option>
                </select>
              </div>
              
              <!-- PBS Datastore (PBS only) -->
              <div v-if="form.mode === 'pbs'" class="form-group">
                <label>Datastore PBS</label>
                <select v-model="form.pbs_datastore" class="form-control">
                  <option value="">Seleziona datastore</option>
                  <option v-for="ds in pbsDatastores" :key="ds" :value="ds">{{ ds }}</option>
                </select>
              </div>
              
              <!-- Storage Dest (PBS) -->
              <div v-if="form.mode === 'pbs'" class="form-group">
                <label>Storage Destinazione</label>
                <select v-model="form.dest_storage" class="form-control">
                  <option value="">Seleziona storage</option>
                  <option v-for="s in destStorages" :key="s.storage" :value="s.storage">
                    {{ s.storage }} ({{ s.type }})
                  </option>
                </select>
              </div>

              <div v-if="form.mode === 'syncoid'" class="form-group">
                <label>Sottocartella ZFS</label>
                <input v-model="form.dest_subfolder" class="form-control" placeholder="replica">
              </div>
              
              <div class="form-group">
                <label>VMID Destinazione</label>
                <input type="number" v-model="form.dest_vmid" class="form-control" :placeholder="selectedVm?.vmid">
              </div>
              
              <div class="form-group">
                <label>Suffisso Nome VM</label>
                <input v-model="form.dest_name_suffix" class="form-control" placeholder="-replica">
              </div>
              
              <div class="form-group">
                <label>Schedule</label>
                <select v-model="cronPreset" @change="onCronPreset" class="form-control">
                  <option value="once">🔒 Manuale (disattivato)</option>
                  <option value="hourly">⏰ Ogni ora</option>
                  <option value="daily">📅 Giornaliero</option>
                  <option value="custom">✏️ Personalizzato</option>
                </select>
              </div>
            </div>
          </div>

          <!-- Options Section -->
          <div class="config-section">
            <div class="section-header">⚡ Opzioni</div>
            <div class="form-grid">
              <div class="form-group" v-if="form.mode === 'syncoid'">
                <label>Compressione</label>
                <select v-model="form.compress" class="form-control">
                  <option value="lz4">LZ4 (veloce)</option>
                  <option value="zstd">ZSTD</option>
                  <option value="gzip">GZIP</option>
                  <option value="none">Nessuna</option>
                </select>
              </div>
              
              <div class="form-group" v-if="form.mode === 'pbs'">
                <label>Modalità Backup</label>
                <select v-model="form.backup_mode" class="form-control">
                  <option value="snapshot">Snapshot (Live)</option>
                  <option value="suspend">Suspend</option>
                  <option value="stop">Stop</option>
                </select>
              </div>
              
              <div class="form-group">
                <label>🗃️ Versioni da mantenere</label>
                <input type="number" v-model="form.keep_snapshots" class="form-control" min="0">
              </div>
              
              <div class="form-group checkbox-cell">
                <label class="checkbox-label">
                  <input type="checkbox" v-model="form.register_vm">
                  Registra VM su destinazione
                </label>
              </div>
            </div>
          </div>

          <!-- Notifications Section -->
          <div class="config-section">
            <div class="section-header">📧 Notifiche</div>
            <div class="form-grid">
              <div class="form-group">
                <label>Invio Email</label>
                <select v-model="form.notify_mode" class="form-control">
                  <option value="never">Mai</option>
                  <option value="failure">Solo errori</option>
                  <option value="daily">📅 Riepilogo giornaliero</option>
                  <option value="always">Sempre</option>
                </select>
              </div>
              <div class="form-group">
                <label>Soggetto Email</label>
                <input v-model="form.email_subject" class="form-control" placeholder="[REPLICA] {vm_name}">
              </div>
            </div>
          </div>
        </div>

        <div class="config-footer">
          <button class="btn-cancel" @click="showConfigModal = false">Annulla</button>
          <button class="btn-create" @click="submit" :disabled="submitting">
            {{ submitting ? 'Creazione...' : '🚀 Crea 1 Job di Replica' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue';
import nodesService, { type Node } from '../../services/nodes';
import vmsService from '../../services/vms';
import syncJobsService from '../../services/syncJobs';
import recoveryJobsService from '../../services/recoveryJobs';
import { pveReplicationService } from '../../services/pveReplication';

const emit = defineEmits(['close', 'created']);

// State
const showConfigModal = ref(false);
const selectedVm = ref<any>(null);
const submitting = ref(false);
const loadingVMs = ref(false);
const loadingDestPools = ref(false);
const cronPreset = ref('once');

// Data
const nodes = ref<Node[]>([]);
const vms = ref<any[]>([]);
const vmDisks = ref<any[]>([]);
const destPools = ref<string[]>([]);
const destStorages = ref<any[]>([]);
const pbsDatastores = ref<string[]>([]);

// Computed
const pveNodes = computed(() => nodes.value.filter(n => n.node_type !== 'pbs'));
const pbsNodes = computed(() => nodes.value.filter(n => n.node_type === 'pbs'));

// Form
const form = reactive({
  mode: 'syncoid' as 'syncoid' | 'pbs' | 'pve',
  source_node_id: null as number | null,
  dest_node_id: null as number | null,
  pbs_node_id: null as number | null,
  vm_id: null as number | null,
  vm_type: 'qemu',
  vm_name: '',
  dest_pool: '',
  dest_subfolder: 'replica',
  dest_storage: '',
  pbs_datastore: '',
  dest_vmid: null as number | null,
  dest_name_suffix: '-replica',
  register_vm: true,
  schedule: '',
  keep_snapshots: 7,
  compress: 'lz4',
  backup_mode: 'snapshot',
  notify_mode: 'daily',
  email_subject: '[REPLICA] {vm_name}'
});

// Methods
const loadData = async () => {
  try {
    const res = await nodesService.getNodes();
    nodes.value = res.data;
  } catch (e) {
    console.error('Error loading nodes:', e);
  }
};

const loadVMs = async () => {
  if (!form.source_node_id) return;
  loadingVMs.value = true;
  try {
    const res = await vmsService.getNodeVMs(form.source_node_id);
    vms.value = res.data;
  } catch (e) {
    console.error('Error loading VMs:', e);
    vms.value = [];
  } finally {
    loadingVMs.value = false;
  }
};

const onDestNodeChange = async () => {
  if (!form.dest_node_id) return;
  
  loadingDestPools.value = true;
  try {
    // Load ZFS pools
    const res = await nodesService.getNodeDatasets(form.dest_node_id, true);
    const poolNames = new Set<string>();
    res.data.forEach((ds: any) => {
      poolNames.add(ds.name.split('/')[0]);
    });
    destPools.value = Array.from(poolNames);
    if (destPools.value.length === 1) form.dest_pool = destPools.value[0];
    
    // Load storages for PBS mode
    if (form.mode === 'pbs') {
      const storageRes = await nodesService.getStorages(form.dest_node_id);
      destStorages.value = (storageRes.data.storages || []).filter(
        (s: any) => ['zfs', 'zfspool', 'dir', 'lvm', 'lvmthin'].includes(s.type)
      );
    }
  } catch (e) {
    console.error('Error loading dest resources:', e);
  } finally {
    loadingDestPools.value = false;
  }
};

const loadPBSDatastores = async () => {
  if (!form.pbs_node_id) return;
  try {
    const res = await nodesService.getPBSDatastores(form.pbs_node_id);
    pbsDatastores.value = res.data.datastores || [];
    if (pbsDatastores.value.length === 1) form.pbs_datastore = pbsDatastores.value[0];
  } catch (e) {
    console.error('Error loading PBS datastores:', e);
  }
};

const openConfigModal = async (vm: any) => {
  selectedVm.value = vm;
  form.vm_id = vm.vmid;
  form.vm_type = vm.type;
  form.vm_name = vm.name;
  form.dest_vmid = vm.vmid;
  form.dest_name_suffix = '-replica';
  
  // Load VM disks for Syncoid
  if (form.mode === 'syncoid' && form.source_node_id) {
    try {
      const res = await vmsService.getVMDisks(form.source_node_id, vm.vmid, vm.type);
      vmDisks.value = (res.data || []).map((d: any) => ({ ...d, selected: true }));
    } catch (e) {
      console.error('Error loading VM disks:', e);
      vmDisks.value = [];
    }
  }
  
  showConfigModal.value = true;
};

const onCronPreset = () => {
  if (cronPreset.value === 'once') form.schedule = '';
  else if (cronPreset.value === 'hourly') form.schedule = '0 * * * *';
  else if (cronPreset.value === 'daily') form.schedule = '0 0 * * *';
};

const submit = async () => {
  submitting.value = true;
  try {
    if (form.mode === 'syncoid') {
      await syncJobsService.createVMReplica({
        vm_id: form.vm_id!,
        vm_name: form.vm_name,
        vm_type: form.vm_type,
        source_node_id: form.source_node_id!,
        dest_node_id: form.dest_node_id!,
        dest_pool: form.dest_pool,
        dest_subfolder: form.dest_subfolder,
        dest_vm_id: form.dest_vmid!,
        dest_vm_name_suffix: form.dest_name_suffix,
        schedule: form.schedule || null,
        register_vm: form.register_vm,
        keep_snapshots: form.keep_snapshots,
        notify_mode: form.notify_mode
      });
    } else if (form.mode === 'pbs') {
      await recoveryJobsService.createJob({
        name: `Replica ${form.vm_name} via PBS`,
        source_node_id: form.source_node_id!,
        vm_id: form.vm_id!,
        vm_type: form.vm_type,
        vm_name: form.vm_name,
        pbs_node_id: form.pbs_node_id!,
        pbs_datastore: form.pbs_datastore,
        dest_node_id: form.dest_node_id!,
        dest_vm_id: form.dest_vmid,
        dest_vm_name_suffix: form.dest_name_suffix,
        dest_storage: form.dest_storage,
        backup_mode: form.backup_mode,
        schedule: form.schedule || undefined,
        overwrite_existing: true,
        restore_start_vm: false
      });
    } else if (form.mode === 'pve') {
      const destNode = pveNodes.value.find(n => n.id === form.dest_node_id);
      await pveReplicationService.createJob({
        vmid: form.vm_id!,
        target: destNode?.name || '',
        schedule: form.schedule || '*/15',
        comment: 'Replica gestita da DA-PXREPL'
      });
    }
    
    emit('created');
  } catch (e: any) {
    alert('Errore: ' + (e.response?.data?.detail || e.message));
  } finally {
    submitting.value = false;
  }
};

onMounted(loadData);
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.wizard-modal {
  width: 900px;
  max-width: 95vw;
  max-height: 90vh;
  background: #1a1a2e;
  border: 1px solid #2d2d44;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.wizard-header {
  padding: 20px 24px;
  border-bottom: 1px solid #2d2d44;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.wizard-header h2 {
  margin: 0;
  font-size: 1.25rem;
  color: #fff;
}

.close-btn {
  background: none;
  border: none;
  font-size: 1.5rem;
  color: #888;
  cursor: pointer;
}

.wizard-body {
  padding: 24px;
  overflow-y: auto;
  flex: 1;
}

.section-label {
  font-size: 0.85rem;
  color: #00ff9d;
  margin-bottom: 12px;
  font-weight: 600;
}

/* Method Cards */
.method-cards {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
}

.method-card {
  flex: 1;
  padding: 16px;
  background: #252538;
  border: 2px solid #2d2d44;
  border-radius: 10px;
  cursor: pointer;
  text-align: center;
  transition: all 0.2s;
}

.method-card:hover {
  border-color: #00ff9d;
}

.method-card.active {
  border-color: #00ff9d;
  background: rgba(0, 255, 157, 0.05);
}

.method-card.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.method-icon {
  font-size: 2rem;
  margin-bottom: 8px;
}

.method-name {
  font-weight: 600;
  color: #00ff9d;
  margin-bottom: 4px;
}

.method-desc {
  font-size: 0.75rem;
  color: #888;
}

/* Node Selection */
.node-row {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
}

.node-select-group {
  flex: 1;
}

.node-select {
  width: 100%;
  padding: 12px;
  background: #252538;
  border: 1px solid #2d2d44;
  border-radius: 8px;
  color: #fff;
}

.pbs-node-row {
  margin-bottom: 24px;
}

/* VM Table */
.vm-list-section {
  margin-top: 16px;
}

.vm-table-container {
  max-height: 300px;
  overflow-y: auto;
  border: 1px solid #2d2d44;
  border-radius: 8px;
}

.vm-table {
  width: 100%;
  border-collapse: collapse;
}

.vm-table th {
  background: #252538;
  padding: 12px;
  text-align: left;
  font-size: 0.75rem;
  color: #888;
  position: sticky;
  top: 0;
}

.vm-table td {
  padding: 12px;
  border-bottom: 1px solid #2d2d44;
}

.vmid-cell {
  font-weight: 600;
}

.name-cell {
  font-weight: 500;
}

.badge {
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 0.75rem;
}

.badge-type {
  background: rgba(0, 212, 255, 0.15);
  color: #00d4ff;
}

.badge-running {
  background: rgba(0, 255, 157, 0.15);
  color: #00ff9d;
}

.badge-stopped {
  background: rgba(255, 82, 82, 0.15);
  color: #ff5252;
}

.btn-configure {
  padding: 8px 16px;
  background: rgba(0, 255, 157, 0.1);
  border: 1px solid #00ff9d;
  border-radius: 6px;
  color: #00ff9d;
  cursor: pointer;
  font-weight: 500;
  transition: all 0.2s;
}

.btn-configure:hover {
  background: #00ff9d;
  color: #000;
}

.loading-cell, .empty-cell {
  text-align: center;
  color: #888;
  padding: 24px;
}

/* ============ Config Modal (Phase 2) ============ */
.config-modal-body {
  padding: 24px;
  overflow-y: auto;
  flex: 1;
}

.config-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.config-title {
  font-size: 1.1rem;
  font-weight: 600;
}

.config-icon {
  margin-right: 8px;
}

.btn-back {
  padding: 8px 12px;
  background: #252538;
  border: 1px solid #2d2d44;
  border-radius: 6px;
  color: #fff;
  cursor: pointer;
}

.config-vm-info {
  margin-bottom: 20px;
}

.vm-badge {
  display: inline-block;
  padding: 8px 16px;
  background: rgba(0, 255, 157, 0.1);
  border: 1px solid #00ff9d;
  border-radius: 6px;
  color: #00ff9d;
  font-weight: 600;
}

.config-sections {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.config-section {
  background: #252538;
  border: 1px solid #2d2d44;
  border-radius: 10px;
  padding: 16px;
}

.section-header {
  font-size: 0.9rem;
  font-weight: 600;
  color: #00ff9d;
  margin-bottom: 16px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-group label {
  font-size: 0.8rem;
  color: #aaa;
}

.form-control {
  padding: 10px 12px;
  background: #1a1a2e;
  border: 1px solid #2d2d44;
  border-radius: 6px;
  color: #fff;
}

.checkbox-cell {
  display: flex;
  align-items: center;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

/* Disks Table */
.disks-table {
  width: 100%;
  border-collapse: collapse;
}

.disks-table th {
  text-align: left;
  padding: 8px;
  font-size: 0.75rem;
  color: #888;
  border-bottom: 1px solid #2d2d44;
}

.disks-table td {
  padding: 10px 8px;
  border-bottom: 1px solid #2d2d44;
}

.dataset-cell {
  font-family: monospace;
  font-size: 0.85rem;
  color: #00d4ff;
}

.size-badge {
  padding: 4px 8px;
  background: rgba(0, 255, 157, 0.1);
  border-radius: 4px;
  color: #00ff9d;
  font-size: 0.8rem;
}

/* Footer */
.config-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid #2d2d44;
}

.btn-cancel {
  padding: 12px 24px;
  background: #252538;
  border: 1px solid #2d2d44;
  border-radius: 8px;
  color: #fff;
  cursor: pointer;
}

.btn-create {
  padding: 12px 24px;
  background: #00ff9d;
  border: none;
  border-radius: 8px;
  color: #000;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-create:hover {
  background: #00e08a;
}

.btn-create:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
