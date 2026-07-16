<template>
  <div class="pbs-inventory-page">
    <PageHeader
      title="Inventario PBS"
      subtitle="Backup VM/CT già presenti su Proxmox Backup Server (creati da Proxmox, da dapx o manualmente)"
      icon="database"
    />

    <div class="info-banner mb-6">
      <div class="icon">📦</div>
      <div class="content">
        <strong>Esplora i backup sul PBS</strong>
        <p>
          Elenco letto dal datastore PBS o dallo storage PBS configurato sui nodi PVE.
          Puoi avviare un restore verso un nodo PVE senza creare un job di replica.
        </p>
      </div>
    </div>

    <div class="card mb-6">
      <div class="card-body filters-grid">
        <div class="form-group">
          <label>Nodo PBS</label>
          <select v-model.number="filters.pbsNodeId" class="form-input" @change="onPbsChange">
            <option :value="null" disabled>— Seleziona PBS —</option>
            <option v-for="n in pbsNodes" :key="n.id" :value="n.id">
              {{ n.name }} ({{ n.hostname }})
            </option>
          </select>
        </div>
        <div class="form-group">
          <label>Datastore</label>
          <input
            v-model="filters.datastore"
            class="form-input"
            :placeholder="selectedPbs?.pbs_datastore || 'datastore1'"
          />
        </div>
        <div class="form-group">
          <label>Nodo PVE (per pvesh)</label>
          <select v-model.number="filters.pveNodeId" class="form-input">
            <option :value="null">Auto</option>
            <option v-for="n in pveNodes" :key="n.id" :value="n.id">
              {{ n.name }}
            </option>
          </select>
        </div>
        <div class="form-group">
          <label>Storage PBS su PVE</label>
          <input v-model="filters.pbsStorage" class="form-input" placeholder="es. PBS-BACK" />
        </div>
        <div class="form-group">
          <label>Filtra VMID</label>
          <input
            v-model.number="filters.vmId"
            type="number"
            min="100"
            class="form-input"
            placeholder="Tutte"
          />
        </div>
        <div class="form-group filter-checkbox">
          <label class="checkbox-label">
            <input v-model="latestOnly" type="checkbox" />
            Solo ultima versione per VM
          </label>
        </div>
        <div class="form-group filter-actions">
          <label>&nbsp;</label>
          <button class="btn btn-primary" :disabled="!filters.pbsNodeId || loading" @click="loadBackups">
            {{ loading ? 'Caricamento…' : 'Aggiorna elenco' }}
          </button>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-header flex justify-between items-center">
        <h3>
          Backup trovati
          <span v-if="datastoreLabel" class="text-secondary text-sm font-normal">
            — datastore {{ datastoreLabel }}
          </span>
        </h3>
        <span class="badge badge-purple">{{ displayedBackups.length }} versioni</span>
        <span v-if="filters.vmId && !latestOnly" class="text-secondary text-sm ml-2">
          (tutte le versioni VM {{ filters.vmId }})
        </span>
      </div>

      <div class="card-body">
        <div v-if="!filters.pbsNodeId" class="empty-state">
          Seleziona un nodo PBS per visualizzare l'inventario.
        </div>
        <div v-else-if="loading" class="empty-state">Caricamento backup PBS…</div>
        <div v-else-if="error" class="alert alert-danger">{{ error }}</div>
        <div v-else-if="backups.length === 0" class="empty-state">
          Nessun backup trovato. Verifica datastore, credenziali PBS e storage PBS sui nodi PVE.
        </div>
        <template v-else>
          <div class="mb-4">
            <input
              v-model="search"
              class="form-input"
              placeholder="Cerca per VMID, nome, backup-id…"
            />
          </div>
          <div class="table-wrap">
            <table class="data-table">
              <thead>
                <tr>
                  <th>VM / CT</th>
                  <th>Data backup</th>
                  <th>Dimensione</th>
                  <th>Backup ID</th>
                  <th class="text-right">Azioni</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="bak in displayedBackups" :key="backupKey(bak)">
                  <td>
                    <div class="font-bold">
                      {{ bak.vm_name || ('VM #' + (bak.vmid ?? '?')) }}
                    </div>
                    <div class="text-xs text-secondary">
                      {{ bak.vm_type === 'lxc' ? 'LXC' : 'QEMU' }}
                      · VMID {{ bak.vmid ?? '—' }}
                    </div>
                  </td>
                  <td>
                    <div class="font-bold">{{ formatBackupTime(bak.backup_time) }}</div>
                    <div v-if="isLatestForVm(bak)" class="text-xs text-success">Ultima versione</div>
                  </td>
                  <td>{{ formatSize(bak.size) }}</td>
                  <td class="font-mono text-xs break-all">{{ backupId(bak) }}</td>
                  <td class="text-right">
                    <button class="btn btn-xs btn-primary" @click="openRestore(bak)">
                      Restore
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </div>
    </div>

    <ModalDialog
      v-model:visible="restoreVisible"
      :title="`Restore da PBS — ${restoreBackup?.vm_name || restoreBackup?.vmid || ''}`"
      width="720px"
    >
      <div v-if="restoreBackup" class="restore-form space-y-4">
        <div class="p-3 bg-dark-soft rounded text-sm">
          <div><strong>Backup:</strong> {{ formatBackupTime(restoreBackup.backup_time) }}</div>
          <div class="text-xs text-secondary break-all mt-1">{{ backupId(restoreBackup) }}</div>
        </div>

        <div class="form-group">
          <label>Nodo PVE destinazione</label>
          <select v-model.number="restoreForm.destNodeId" class="form-input" @change="loadStorages">
            <option :value="null" disabled>— Seleziona nodo —</option>
            <option v-for="n in pveNodes" :key="n.id" :value="n.id">{{ n.name }}</option>
          </select>
        </div>

        <div class="grid-2 gap-4">
          <div class="form-group">
            <label>VMID destinazione</label>
            <input
              v-model.number="restoreForm.destVmid"
              type="number"
              min="100"
              class="form-input"
              :placeholder="String(restoreBackup.vmid || '')"
            />
          </div>
          <div class="form-group">
            <label>Storage destinazione</label>
            <select v-model="restoreForm.destStorage" class="form-input">
              <option value="">Default nodo</option>
              <option v-for="s in targetStorages" :key="s.name" :value="s.name">
                {{ s.name }} ({{ s.type }})
              </option>
            </select>
          </div>
        </div>

        <div class="alert alert-warning text-sm">
          Il restore sovrascrive la VM se il VMID esiste già sul nodo destinazione.
        </div>
      </div>

      <template #footer>
        <button class="btn btn-secondary" @click="restoreVisible = false">Annulla</button>
        <button
          class="btn btn-primary"
          :disabled="restoring || !restoreForm.destNodeId"
          @click="executeRestore"
        >
          {{ restoring ? 'Restore in corso…' : 'Avvia restore' }}
        </button>
      </template>
    </ModalDialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import PageHeader from '../components/ui/PageHeader.vue'
import ModalDialog from '../components/ModalDialog.vue'
import nodesService, { type Node, type NodeStorage } from '../services/nodes'
import pbsInventoryService, { type PBSBackupEntry } from '../services/pbsInventory'
import { useToast, errorMessage } from '../stores/toast'
import { confirmDangerous } from '../stores/confirm'

const toast = useToast()

const pbsNodes = ref<Node[]>([])
const pveNodes = ref<Node[]>([])
const backups = ref<PBSBackupEntry[]>([])
const datastoreLabel = ref('')
const loading = ref(false)
const error = ref('')
const search = ref('')
const latestOnly = ref(false)

const filters = reactive({
  pbsNodeId: null as number | null,
  datastore: '',
  pveNodeId: null as number | null,
  pbsStorage: '',
  vmId: null as number | null,
})

const restoreVisible = ref(false)
const restoreBackup = ref<PBSBackupEntry | null>(null)
const restoring = ref(false)
const targetStorages = ref<NodeStorage[]>([])
const restoreForm = reactive({
  destNodeId: null as number | null,
  destVmid: null as number | null,
  destStorage: '',
})

const selectedPbs = computed(() =>
  pbsNodes.value.find(n => n.id === filters.pbsNodeId) ?? null
)

const filteredBackups = computed(() => {
  const q = search.value.trim().toLowerCase()
  let list = backups.value
  if (q) {
    list = list.filter(b => {
      const id = backupId(b).toLowerCase()
      const name = (b.vm_name || '').toLowerCase()
      const vmid = String(b.vmid ?? '')
      return id.includes(q) || name.includes(q) || vmid.includes(q)
    })
  }
  return list
})

const displayedBackups = computed(() => {
  if (!latestOnly.value) return filteredBackups.value
  const latestByVm = new Map<number, PBSBackupEntry>()
  for (const b of filteredBackups.value) {
    const vid = b.vmid
    if (vid == null) continue
    const prev = latestByVm.get(vid)
    if (!prev || (b.backup_time || 0) > (prev.backup_time || 0)) {
      latestByVm.set(vid, b)
    }
  }
  return [...latestByVm.values()].sort((a, b) => (b.backup_time || 0) - (a.backup_time || 0))
})

const latestVmIds = computed(() => {
  const m = new Map<number, number>()
  for (const b of backups.value) {
    if (b.vmid == null) continue
    const t = b.backup_time || 0
    if (!m.has(b.vmid) || t > (m.get(b.vmid) || 0)) m.set(b.vmid, t)
  }
  return m
})

function isLatestForVm(b: PBSBackupEntry): boolean {
  if (b.vmid == null) return false
  return (latestVmIds.value.get(b.vmid) || 0) === (b.backup_time || 0)
}

onMounted(async () => {
  await loadNodes()
  if (pbsNodes.value.length === 1) {
    filters.pbsNodeId = pbsNodes.value[0].id
    if (pbsNodes.value[0].pbs_datastore) {
      filters.datastore = pbsNodes.value[0].pbs_datastore
    }
    await loadBackups()
  }
})

async function loadNodes() {
  try {
    const res = await nodesService.getNodes()
    const all = res.data || []
    pbsNodes.value = all.filter(n => n.node_type === 'pbs')
    pveNodes.value = all.filter(n => n.node_type !== 'pbs')
  } catch (e) {
    toast.error('Errore caricamento nodi', errorMessage(e))
  }
}

function onPbsChange() {
  const pbs = selectedPbs.value
  if (pbs?.pbs_datastore && !filters.datastore) {
    filters.datastore = pbs.pbs_datastore
  }
  backups.value = []
  error.value = ''
}

async function loadBackups() {
  if (!filters.pbsNodeId) return
  loading.value = true
  error.value = ''
  try {
    const params: Record<string, string | number> = {}
    if (filters.datastore.trim()) params.datastore = filters.datastore.trim()
    if (filters.pveNodeId) params.pve_node_id = filters.pveNodeId
    if (filters.pbsStorage.trim()) params.pbs_storage = filters.pbsStorage.trim()
    if (filters.vmId) params.vm_id = filters.vmId

    const res = await pbsInventoryService.listBackups(filters.pbsNodeId, params)
    backups.value = res.data.backups || []
    datastoreLabel.value = res.data.datastore || filters.datastore || ''
    backups.value.sort((a, b) => (b.backup_time || 0) - (a.backup_time || 0))
  } catch (e) {
    error.value = errorMessage(e)
    backups.value = []
  } finally {
    loading.value = false
  }
}

function backupId(b: PBSBackupEntry): string {
  return b.restore_path || b.backup_id || b['backup-id'] || b.volid || ''
}

function backupKey(b: PBSBackupEntry): string {
  return `${backupId(b)}-${b.backup_time || 0}`
}

function formatBackupTime(ts?: number): string {
  if (!ts) return '—'
  const ms = ts > 1e12 ? ts : ts * 1000
  return new Date(ms).toLocaleString()
}

function formatSize(bytes?: number): string {
  if (!bytes) return '—'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`
}

function openRestore(bak: PBSBackupEntry) {
  restoreBackup.value = bak
  restoreForm.destNodeId = pveNodes.value[0]?.id ?? null
  restoreForm.destVmid = bak.vmid ?? null
  restoreForm.destStorage = ''
  restoreVisible.value = true
  if (restoreForm.destNodeId) loadStorages()
}

async function loadStorages() {
  if (!restoreForm.destNodeId) {
    targetStorages.value = []
    return
  }
  try {
    const res = await nodesService.getStorages(restoreForm.destNodeId)
    targetStorages.value = res.data?.storages || []
  } catch {
    targetStorages.value = []
  }
}

async function executeRestore() {
  if (!restoreBackup.value || !filters.pbsNodeId || !restoreForm.destNodeId) return
  const bid = backupId(restoreBackup.value)
  if (!bid) {
    toast.error('Backup ID mancante')
    return
  }
  if (!await confirmDangerous(`Avviare il restore di ${restoreBackup.value.vm_name || bid}?`)) return

  restoring.value = true
  try {
    await pbsInventoryService.directRestore({
      pbs_node_id: filters.pbsNodeId,
      backup_id: bid,
      dest_node_id: restoreForm.destNodeId,
      dest_vmid: restoreForm.destVmid || restoreBackup.value.vmid || undefined,
      dest_storage: restoreForm.destStorage || undefined,
      vm_type: (restoreBackup.value.vm_type === 'lxc' ? 'lxc' : 'qemu'),
    })
    toast.success('Restore completato')
    restoreVisible.value = false
  } catch (e) {
    toast.error('Restore fallito', errorMessage(e))
  } finally {
    restoring.value = false
  }
}
</script>

<style scoped>
.filter-checkbox {
  display: flex;
  align-items: flex-end;
}

.filter-checkbox .checkbox-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
  padding-bottom: 0.35rem;
  font-size: 0.875rem;
}

.filters-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 1rem;
  align-items: end;
}

.filter-actions .btn {
  width: 100%;
}

.table-wrap {
  overflow-x: auto;
}

.restore-form .grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

@media (max-width: 640px) {
  .restore-form .grid-2 {
    grid-template-columns: 1fr;
  }
}
</style>
