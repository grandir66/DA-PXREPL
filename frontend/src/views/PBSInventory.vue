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
          Ogni macchina è raggruppata con la catena delle date di backup disponibili.
          Scegli la data e avvia il restore verso un nodo PVE.
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
        <span class="badge badge-purple">
          {{ vmGroups.length }} VM · {{ totalVersions }} date
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
              placeholder="Cerca per VMID o nome macchina…"
            />
          </div>

          <div v-if="vmGroups.length === 0" class="empty-state">
            Nessuna macchina corrisponde alla ricerca.
          </div>

          <div v-else class="vm-groups">
            <section v-for="group in vmGroups" :key="group.vmid" class="vm-group">
              <header class="vm-group-head">
                <div>
                  <div class="vm-group-title">{{ group.vm_name }}</div>
                  <div class="vm-group-meta">
                    {{ group.vm_type === 'lxc' ? 'LXC' : 'QEMU' }}
                    · VMID {{ group.vmid }}
                    · {{ group.versions.length }} backup
                  </div>
                </div>
              </header>

              <ol class="date-chain">
                <li
                  v-for="(ver, idx) in group.versions"
                  :key="backupKey(ver)"
                  class="date-chain-item"
                  :class="{ latest: idx === 0 }"
                >
                  <div class="date-chain-when">
                    <span class="date-label">{{ formatBackupTime(ver.backup_time) }}</span>
                    <span v-if="idx === 0" class="badge badge-success badge-xs">più recente</span>
                  </div>
                  <div class="date-chain-size">{{ formatSize(ver.size) }}</div>
                  <button class="btn btn-xs btn-primary" @click="openRestore(ver)">
                    Restore
                  </button>
                </li>
              </ol>
            </section>
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
          <div><strong>Data backup:</strong> {{ formatBackupTime(restoreBackup.backup_time) }}</div>
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

interface VmBackupGroup {
  vmid: number
  vm_name: string
  vm_type: string
  versions: PBSBackupEntry[]
}

const toast = useToast()

const pbsNodes = ref<Node[]>([])
const pveNodes = ref<Node[]>([])
const backups = ref<PBSBackupEntry[]>([])
const datastoreLabel = ref('')
const loading = ref(false)
const error = ref('')
const search = ref('')

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
  if (!q) return backups.value
  return backups.value.filter(b => {
    const name = (b.vm_name || '').toLowerCase()
    const vmid = String(b.vmid ?? '')
    return name.includes(q) || vmid.includes(q)
  })
})

const vmGroups = computed((): VmBackupGroup[] => {
  const map = new Map<number, VmBackupGroup>()
  for (const b of filteredBackups.value) {
    if (b.vmid == null) continue
    let group = map.get(b.vmid)
    if (!group) {
      group = {
        vmid: b.vmid,
        vm_name: b.vm_name || `VM #${b.vmid}`,
        vm_type: b.vm_type || 'qemu',
        versions: [],
      }
      map.set(b.vmid, group)
    }
    if (b.vm_name && group.vm_name.startsWith('VM #')) {
      group.vm_name = b.vm_name
    }
    group.versions.push(b)
  }

  for (const group of map.values()) {
    group.versions.sort((a, b) => (b.backup_time || 0) - (a.backup_time || 0))
  }

  return [...map.values()].sort((a, b) => {
    const ta = a.versions[0]?.backup_time || 0
    const tb = b.versions[0]?.backup_time || 0
    return tb - ta
  })
})

const totalVersions = computed(() =>
  vmGroups.value.reduce((n, g) => n + g.versions.length, 0)
)

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
  const when = formatBackupTime(restoreBackup.value.backup_time)
  if (!await confirmDangerous(
    `Avviare il restore di ${restoreBackup.value.vm_name || bid} del ${when}?`
  )) return

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
.filters-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 1rem;
  align-items: end;
}

.filter-actions .btn {
  width: 100%;
}

.vm-groups {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.vm-group {
  border: 1px solid var(--border-color, rgba(255, 255, 255, 0.08));
  border-radius: 8px;
  overflow: hidden;
}

.vm-group-head {
  padding: 0.75rem 1rem;
  background: rgba(255, 255, 255, 0.03);
  border-bottom: 1px solid var(--border-color, rgba(255, 255, 255, 0.06));
}

.vm-group-title {
  font-weight: 600;
  font-size: 1rem;
}

.vm-group-meta {
  font-size: 0.8rem;
  color: var(--text-secondary, #9ca3af);
  margin-top: 0.15rem;
}

.date-chain {
  list-style: none;
  margin: 0;
  padding: 0;
}

.date-chain-item {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 1rem;
  align-items: center;
  padding: 0.55rem 1rem;
  border-bottom: 1px solid var(--border-color, rgba(255, 255, 255, 0.04));
}

.date-chain-item:last-child {
  border-bottom: none;
}

.date-chain-item.latest {
  background: rgba(34, 197, 94, 0.06);
}

.date-chain-when {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.date-label {
  font-variant-numeric: tabular-nums;
}

.date-chain-size {
  font-size: 0.85rem;
  color: var(--text-secondary, #9ca3af);
  white-space: nowrap;
}

.badge-xs {
  font-size: 0.65rem;
  padding: 0.1rem 0.35rem;
}

.restore-form .grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

@media (max-width: 640px) {
  .date-chain-item {
    grid-template-columns: 1fr;
    gap: 0.35rem;
  }

  .restore-form .grid-2 {
    grid-template-columns: 1fr;
  }
}
</style>
