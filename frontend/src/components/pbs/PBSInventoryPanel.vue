<template>
  <div class="pbs-inv-panel">
    <div class="info-banner mb-6">
      <div class="icon">📦</div>
      <div class="content">
        <strong>Inventario backup su PBS</strong>
        <p>
          Esplora backup esistenti (Proxmox, dapx o manuali). Per replica automatica verso un altro nodo
          usa <router-link :to="{ name: 'replication', query: { tab: 'recovery_pbs' } }">Repliche → Replica via PBS</router-link>.
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
            <option v-for="n in pveNodes" :key="n.id" :value="n.id">{{ n.name }}</option>
          </select>
        </div>
        <div class="form-group">
          <label>Storage PBS su PVE</label>
          <input v-model="filters.pbsStorage" class="form-input" placeholder="es. PBS-BACK" />
        </div>
        <div class="form-group">
          <label>Filtra VMID</label>
          <input v-model.number="filters.vmId" type="number" min="100" class="form-input" placeholder="Tutte" />
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
          <span v-if="datastoreLabel" class="text-secondary text-sm font-normal"> — {{ datastoreLabel }}</span>
        </h3>
        <span class="badge badge-purple">{{ filteredVmSummaries.length }} VM · {{ totalVersions }} date</span>
      </div>
      <div class="card-body">
        <div v-if="!filters.pbsNodeId" class="empty-state">Seleziona un nodo PBS.</div>
        <div v-else-if="loading" class="empty-state">Caricamento…</div>
        <div v-else-if="error" class="alert alert-danger">{{ error }}</div>
        <div v-else-if="vmSummaries.length === 0" class="empty-state">Nessun backup trovato.</div>
        <template v-else>
          <div class="mb-4">
            <input v-model="search" class="form-input" placeholder="Cerca VMID o nome…" />
          </div>
          <div v-if="filteredVmSummaries.length === 0" class="empty-state">Nessuna corrispondenza.</div>
          <div v-else class="vm-groups">
            <section
              v-for="group in filteredVmSummaries"
              :key="group.vmid"
              class="vm-group"
              :class="{ expanded: isVmExpanded(group.vmid) }"
            >
              <button type="button" class="vm-group-head" @click="toggleVm(group)">
                <span class="vm-group-chevron">{{ isVmExpanded(group.vmid) ? '▾' : '▸' }}</span>
                <div class="vm-group-summary">
                  <div class="vm-group-title">{{ group.vm_name }}</div>
                  <div class="vm-group-meta">
                    {{ group.vm_type === 'lxc' ? 'LXC' : 'QEMU' }} · VMID {{ group.vmid }} · {{ group.backup_count }} backup
                  </div>
                </div>
                <div v-if="!isVmExpanded(group.vmid)" class="vm-group-latest">
                  <span class="text-secondary text-sm">Ultimo:</span>
                  <span>{{ formatBackupTime(group.latest_backup_time) }}</span>
                </div>
              </button>
              <div v-if="isVmExpanded(group.vmid)" class="date-chain-wrap">
                <div v-if="isVmLoading(group.vmid)" class="date-chain-loading">Caricamento…</div>
                <div v-else-if="vmVersionsError(group.vmid)" class="date-chain-error">{{ vmVersionsError(group.vmid) }}</div>
                <ol v-else class="date-chain">
                  <li
                    v-for="(ver, idx) in getVmVersions(group.vmid)"
                    :key="backupKey(ver)"
                    class="date-chain-item"
                    :class="{ latest: idx === 0 }"
                  >
                    <div class="date-chain-when">
                      <span>{{ formatBackupTime(ver.backup_time) }}</span>
                      <span v-if="idx === 0" class="badge badge-success badge-xs">più recente</span>
                    </div>
                    <div class="date-chain-size">{{ formatSize(ver.size) }}</div>
                    <button class="btn btn-xs btn-primary" @click="openRestore(ver)">Restore</button>
                  </li>
                </ol>
              </div>
            </section>
          </div>
        </template>
      </div>
    </div>

    <ModalDialog
      v-model:visible="restoreVisible"
      :title="`Restore — ${restoreBackup?.vm_name || restoreBackup?.vmid || ''}`"
      width="720px"
    >
      <div v-if="restoreBackup" class="restore-form space-y-4">
        <div class="p-3 bg-dark-soft rounded text-sm">
          <div><strong>Data:</strong> {{ formatBackupTime(restoreBackup.backup_time) }}</div>
        </div>
        <div class="form-group">
          <label>Nodo PVE destinazione</label>
          <select v-model.number="restoreForm.destNodeId" class="form-input" @change="loadStorages">
            <option :value="null" disabled>— Seleziona —</option>
            <option v-for="n in pveNodes" :key="n.id" :value="n.id">{{ n.name }}</option>
          </select>
        </div>
        <div class="grid-2 gap-4">
          <div class="form-group">
            <label>VMID destinazione</label>
            <input v-model.number="restoreForm.destVmid" type="number" min="100" class="form-input" />
          </div>
          <div class="form-group">
            <label>Storage</label>
            <select v-model="restoreForm.destStorage" class="form-input">
              <option value="">Default</option>
              <option v-for="s in targetStorages" :key="s.name" :value="s.name">
                {{ s.name }} ({{ s.type }})
              </option>
            </select>
          </div>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-secondary" @click="restoreVisible = false">Annulla</button>
        <button class="btn btn-primary" :disabled="restoring || !restoreForm.destNodeId" @click="executeRestore">
          {{ restoring ? 'Restore…' : 'Avvia restore' }}
        </button>
      </template>
    </ModalDialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import ModalDialog from '../ModalDialog.vue'
import nodesService, { type Node, type NodeStorage } from '../../services/nodes'
import pbsInventoryService, { type PBSBackupEntry, type PBSVmSummary } from '../../services/pbsInventory'
import { useToast, errorMessage } from '../../stores/toast'
import { confirmDangerous } from '../../stores/confirm'

const toast = useToast()
const pbsNodes = ref<Node[]>([])
const pveNodes = ref<Node[]>([])
const vmSummaries = ref<PBSVmSummary[]>([])
const vmVersions = ref<Record<number, PBSBackupEntry[]>>({})
const vmVersionsErrors = ref<Record<number, string>>({})
const loadingVmids = ref<Set<number>>(new Set())
const totalVersions = ref(0)
const datastoreLabel = ref('')
const loading = ref(false)
const error = ref('')
const search = ref('')
const expandedVmids = ref<Set<number>>(new Set())

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

const selectedPbs = computed(() => pbsNodes.value.find(n => n.id === filters.pbsNodeId) ?? null)

const filteredVmSummaries = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return vmSummaries.value
  return vmSummaries.value.filter(v => {
    return (v.vm_name || '').toLowerCase().includes(q) || String(v.vmid ?? '').includes(q)
  })
})

function inventoryParams(forceRefresh = false): Record<string, string | number | boolean> {
  const params: Record<string, string | number | boolean> = {}
  if (filters.datastore.trim()) params.datastore = filters.datastore.trim()
  if (filters.pveNodeId) params.pve_node_id = filters.pveNodeId
  if (filters.pbsStorage.trim()) params.pbs_storage = filters.pbsStorage.trim()
  if (filters.vmId) params.vm_id = filters.vmId
  if (forceRefresh) params.force_refresh = true
  return params
}

onMounted(async () => {
  await loadNodes()
  if (pbsNodes.value.length === 1) {
    filters.pbsNodeId = pbsNodes.value[0].id
    if (pbsNodes.value[0].pbs_datastore) filters.datastore = pbsNodes.value[0].pbs_datastore
    await loadBackups()
  }
})

async function loadNodes() {
  const res = await nodesService.getNodes()
  const all = res.data || []
  pbsNodes.value = all.filter(n => n.node_type === 'pbs')
  pveNodes.value = all.filter(n => n.node_type !== 'pbs')
}

function onPbsChange() {
  const pbs = selectedPbs.value
  if (pbs?.pbs_datastore && !filters.datastore) filters.datastore = pbs.pbs_datastore
  vmSummaries.value = []
  vmVersions.value = {}
  expandedVmids.value = new Set()
  totalVersions.value = 0
  error.value = ''
}

function isVmExpanded(vmid: number) { return expandedVmids.value.has(vmid) }
function isVmLoading(vmid: number) { return loadingVmids.value.has(vmid) }
function getVmVersions(vmid: number) { return vmVersions.value[vmid] || [] }
function vmVersionsError(vmid: number) { return vmVersionsErrors.value[vmid] || '' }

async function toggleVm(group: PBSVmSummary) {
  const vmid = group.vmid
  const next = new Set(expandedVmids.value)
  if (next.has(vmid)) { next.delete(vmid); expandedVmids.value = next; return }
  next.add(vmid)
  expandedVmids.value = next
  if (!vmVersions.value[vmid] && !loadingVmids.value.has(vmid)) await loadVmVersions(vmid)
}

async function loadVmVersions(vmid: number) {
  if (!filters.pbsNodeId) return
  loadingVmids.value = new Set([...loadingVmids.value, vmid])
  delete vmVersionsErrors.value[vmid]
  try {
    const res = await pbsInventoryService.listVmVersions(filters.pbsNodeId, vmid, inventoryParams())
    vmVersions.value = { ...vmVersions.value, [vmid]: res.data.versions || [] }
  } catch (e) {
    vmVersionsErrors.value = { ...vmVersionsErrors.value, [vmid]: errorMessage(e) }
  } finally {
    const done = new Set(loadingVmids.value)
    done.delete(vmid)
    loadingVmids.value = done
  }
}

async function loadBackups() {
  if (!filters.pbsNodeId) return
  loading.value = true
  error.value = ''
  try {
    const res = await pbsInventoryService.listVmSummaries(filters.pbsNodeId, inventoryParams(true))
    vmSummaries.value = res.data.vms || []
    totalVersions.value = res.data.total_versions || 0
    datastoreLabel.value = res.data.datastore || filters.datastore || ''
    vmVersions.value = {}
    expandedVmids.value = new Set()
  } catch (e) {
    error.value = errorMessage(e)
    vmSummaries.value = []
  } finally {
    loading.value = false
  }
}

function backupId(b: PBSBackupEntry) {
  return b.restore_path || b.backup_id || b['backup-id'] || b.volid || ''
}
function backupKey(b: PBSBackupEntry) { return `${backupId(b)}-${b.backup_time || 0}` }

function formatBackupTime(ts?: number) {
  if (!ts) return '—'
  const ms = ts > 1e12 ? ts : ts * 1000
  return new Date(ms).toLocaleString()
}

function formatSize(bytes?: number) {
  if (!bytes) return '—'
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  return `${(bytes / 1024 ** i).toFixed(1)} ${sizes[i]}`
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
  if (!restoreForm.destNodeId) { targetStorages.value = []; return }
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
  if (!bid) { toast.error('Backup ID mancante'); return }
  if (!await confirmDangerous(`Restore ${restoreBackup.value.vm_name || bid}?`)) return
  restoring.value = true
  try {
    await pbsInventoryService.directRestore({
      pbs_node_id: filters.pbsNodeId,
      backup_id: bid,
      dest_node_id: restoreForm.destNodeId,
      dest_vmid: restoreForm.destVmid || restoreBackup.value.vmid || undefined,
      dest_storage: restoreForm.destStorage || undefined,
      vm_type: restoreBackup.value.vm_type === 'lxc' ? 'lxc' : 'qemu',
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
.filter-actions .btn { width: 100%; }
.vm-groups { display: flex; flex-direction: column; gap: 1rem; }
.vm-group { border: 1px solid var(--color-border); border-radius: var(--radius-md); overflow: hidden; }
.vm-group-head {
  display: flex; align-items: center; gap: 0.75rem; width: 100%; padding: 0.75rem 1rem;
  background: var(--color-bg-element); border: none; color: inherit; cursor: pointer; text-align: left;
}
.vm-group-chevron { flex: 0 0 1rem; color: var(--color-text-secondary); }
.vm-group-summary { flex: 1; min-width: 0; }
.vm-group-title { font-weight: 600; }
.vm-group-meta { font-size: 0.8rem; color: var(--color-text-secondary); }
.date-chain { list-style: none; margin: 0; padding: 0; }
.date-chain-item {
  display: grid; grid-template-columns: 1fr auto auto; gap: 1rem; align-items: center;
  padding: 0.55rem 1rem; border-bottom: 1px solid var(--color-border);
}
.date-chain-item.latest { background: rgba(34, 197, 94, 0.06); }
.restore-form .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
</style>
