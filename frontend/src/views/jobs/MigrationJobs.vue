<template>
  <div class="migration-jobs-page">
    <PageHeader title="Migrazioni" subtitle="Spostamento e copia VM tra i nodi" icon="arrow-right-left">
      <template #actions>
        <button class="btn btn-secondary btn-sm" @click="loadJobs" :disabled="loading">
          <span v-if="loading" class="spinner-sm"></span>
          <span v-else>Aggiorna</span>
        </button>
        <button class="btn btn-primary btn-sm" @click="openCreateModal">
          + Nuova Migrazione
        </button>
      </template>
    </PageHeader>

    <div class="card">
      <div class="table-container">
        <table class="data-table">
          <thead>
            <tr>
              <th>Nome</th>
              <th>VM</th>
              <th>Path (Source → Dest)</th>
              <th>Tipo</th>
              <th>Schedule</th>
              <th>Stato</th>
              <th>Azioni</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="job in jobs" :key="job.id">
              <td><strong>{{ job.name }}</strong></td>
              <td>
                <span class="badge badge-info">{{ job.vm_type }} {{ job.vm_id }}</span>
                <div class="text-xs mt-1">{{ job.vm_name }}</div>
              </td>
              <td class="text-sm">
                {{ job.source_node_name || job.source_node_id }}
                <span>→</span>
                {{ job.dest_node_name || job.dest_node_id }}
                <div v-if="job.dest_vm_id" class="text-xs text-secondary">New ID: {{ job.dest_vm_id }}</div>
              </td>
              <td>
                <span class="badge" :class="job.migration_type === 'move' ? 'badge-warning' : 'badge-primary'">
                  {{ job.migration_type }}
                </span>
              </td>
              <td>
                <code v-if="job.schedule">{{ job.schedule }}</code>
                <span v-else class="text-secondary">-</span>
              </td>
              <td>
                <span class="badge" :class="getStatusClass(job.last_status)">
                  {{ job.last_status || 'Never' }}
                </span>
                <div v-if="job.last_run" class="text-xs text-secondary mt-1">{{ formatDate(job.last_run) }}</div>
              </td>
              <td>
                <div class="btn-group">
                  <button class="btn btn-primary btn-xs" @click="runJob(job)" :disabled="job.last_status === 'running'">
                    <Icon name="play" :size="14" /> Run
                  </button>
                  <button class="btn btn-secondary btn-xs" @click="toggleJob(job)" :title="job.is_active ? 'Disattiva' : 'Attiva'">
                    {{ job.is_active ? '⏸' : '▶' }}
                  </button>
                  <button class="btn btn-danger btn-xs" @click="deleteJob(job)"><Icon name="trash" :size="14" /></button>
                </div>
              </td>
            </tr>
            <tr v-if="jobs.length === 0 && !loading">
              <td colspan="7" class="empty-state-cell">Nessun job di migrazione configurato</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <ModalDialog
      :visible="showCreateModal"
      title="Nuova migrazione"
      width="640px"
      @update:visible="showCreateModal = $event"
      @close="showCreateModal = false"
    >
      <div class="form-group">
        <label>Nome job</label>
        <input v-model="form.name" class="form-input" placeholder="es. Migrazione VM 100 → nodo2" />
      </div>
      <div class="grid-2">
        <div class="form-group">
          <label>Nodo sorgente</label>
          <select v-model.number="form.source_node_id" class="form-input" @change="onSourceChange">
            <option :value="0" disabled>Seleziona…</option>
            <option v-for="n in pveNodes" :key="n.id" :value="n.id">{{ n.name }}</option>
          </select>
        </div>
        <div class="form-group">
          <label>Nodo destinazione</label>
          <select v-model.number="form.dest_node_id" class="form-input">
            <option :value="0" disabled>Seleziona…</option>
            <option v-for="n in pveNodes" :key="n.id" :value="n.id">{{ n.name }}</option>
          </select>
        </div>
      </div>
      <div class="grid-2">
        <div class="form-group">
          <label>VM</label>
          <select v-model.number="form.vm_id" class="form-input" :disabled="!form.source_node_id || vmsLoading">
            <option :value="0" disabled>{{ vmsLoading ? 'Caricamento…' : 'Seleziona VM…' }}</option>
            <option v-for="vm in sourceVms" :key="vm.vmid" :value="vm.vmid">
              {{ vm.type }} {{ vm.vmid }} — {{ vm.name }}
            </option>
          </select>
        </div>
        <div class="form-group">
          <label>Tipo migrazione</label>
          <select v-model="form.migration_type" class="form-input">
            <option value="copy">copy (mantiene sorgente)</option>
            <option value="move">move (rimuove da sorgente)</option>
          </select>
        </div>
      </div>
      <div class="grid-2">
        <div class="form-group">
          <label>VMID destinazione (opzionale)</label>
          <input v-model.number="form.dest_vm_id" type="number" class="form-input" placeholder="Auto" min="100" />
        </div>
        <div class="form-group">
          <label>Schedule cron (opzionale)</label>
          <input v-model="form.schedule" class="form-input" placeholder="es. 0 2 * * *" />
        </div>
      </div>
      <template #footer>
        <button class="btn btn-secondary btn-sm" @click="showCreateModal = false">Annulla</button>
        <button class="btn btn-primary btn-sm" @click="submitCreate" :disabled="saving || !canSubmit">
          {{ saving ? 'Salvataggio…' : 'Crea job' }}
        </button>
      </template>
    </ModalDialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, watch } from 'vue'
import { useToast, errorMessage } from '../../stores/toast'
import Icon from '../../components/ui/Icon.vue'
import { confirmDangerous, confirmDelete } from '../../stores/confirm'
import PageHeader from '../../components/ui/PageHeader.vue'
import ModalDialog from '../../components/ModalDialog.vue'
import migrationJobsService, { type MigrationJob } from '../../services/migrationJobs'
import nodesService, { type Node } from '../../services/nodes'
import vmsService from '../../services/vms'

const toast = useToast()

const jobs = ref<MigrationJob[]>([])
const loading = ref(false)
const showCreateModal = ref(false)
const saving = ref(false)
const pveNodes = ref<Node[]>([])
const sourceVms = ref<{ vmid: number; name: string; type: string }[]>([])
const vmsLoading = ref(false)

const form = ref({
  name: '',
  source_node_id: 0,
  dest_node_id: 0,
  vm_id: 0,
  vm_type: 'qemu',
  migration_type: 'copy',
  dest_vm_id: undefined as number | undefined,
  schedule: '',
})

const canSubmit = computed(() =>
  form.value.name.trim() &&
  form.value.source_node_id > 0 &&
  form.value.dest_node_id > 0 &&
  form.value.vm_id > 0 &&
  form.value.source_node_id !== form.value.dest_node_id
)

onMounted(() => {
  loadJobs()
  loadNodes()
})

watch(() => form.value.vm_id, (id) => {
  const vm = sourceVms.value.find(v => v.vmid === id)
  if (vm) form.value.vm_type = vm.type === 'lxc' ? 'lxc' : 'qemu'
})

async function loadNodes() {
  try {
    const res = await nodesService.getNodes()
    pveNodes.value = (res.data || []).filter(n => n.node_type === 'pve' || !n.node_type)
  } catch (e) {
    toast.error('Errore caricamento nodi', errorMessage(e))
  }
}

async function onSourceChange() {
  form.value.vm_id = 0
  sourceVms.value = []
  if (!form.value.source_node_id) return
  vmsLoading.value = true
  try {
    const res = await vmsService.getNodeVMs(form.value.source_node_id)
    const list = Array.isArray(res.data) ? res.data : []
    sourceVms.value = list.map((v: { vmid: number; name?: string; type?: string }) => ({
      vmid: v.vmid,
      name: v.name || `VM-${v.vmid}`,
      type: v.type || 'qemu',
    }))
  } catch (e) {
    toast.error('Errore caricamento VM', errorMessage(e))
  } finally {
    vmsLoading.value = false
  }
}

function openCreateModal() {
  form.value = {
    name: '',
    source_node_id: 0,
    dest_node_id: 0,
    vm_id: 0,
    vm_type: 'qemu',
    migration_type: 'copy',
    dest_vm_id: undefined,
    schedule: '',
  }
  sourceVms.value = []
  showCreateModal.value = true
}

async function submitCreate() {
  if (!canSubmit.value) return
  saving.value = true
  try {
    const payload: Record<string, unknown> = {
      name: form.value.name.trim(),
      source_node_id: form.value.source_node_id,
      dest_node_id: form.value.dest_node_id,
      vm_id: form.value.vm_id,
      vm_type: form.value.vm_type,
      migration_type: form.value.migration_type,
    }
    if (form.value.dest_vm_id) payload.dest_vm_id = form.value.dest_vm_id
    if (form.value.schedule?.trim()) payload.schedule = form.value.schedule.trim()
    await migrationJobsService.createJob(payload)
    toast.success('Job di migrazione creato')
    showCreateModal.value = false
    await loadJobs()
  } catch (e) {
    toast.error('Errore creazione job', errorMessage(e))
  } finally {
    saving.value = false
  }
}

async function loadJobs() {
  loading.value = true
  try {
    const res = await migrationJobsService.getJobs()
    jobs.value = res.data
  } catch (e) {
    toast.error('Errore caricamento migrazioni', errorMessage(e))
  } finally {
    loading.value = false
  }
}

async function runJob(job: MigrationJob) {
  if (!await confirmDangerous(`Avviare migrazione ${job.name}?`)) return
  try {
    const res = await migrationJobsService.runJob(job.id)
    if (res.data.requires_confirmation) {
      if (await confirmDangerous(res.data.message, undefined, 'Forza')) {
        await migrationJobsService.runJob(job.id, true)
      }
    }
    loadJobs()
  } catch (e) {
    toast.error('Errore avvio migrazione', errorMessage(e))
  }
}

async function toggleJob(job: MigrationJob) {
  try {
    await migrationJobsService.toggleJob(job.id)
    job.is_active = !job.is_active
    toast.success(job.is_active ? 'Job attivato' : 'Job disattivato')
  } catch (e) {
    toast.error('Errore modifica stato job', errorMessage(e))
  }
}

async function deleteJob(job: MigrationJob) {
  if (!await confirmDelete(job.name, 'job di migrazione')) return
  try {
    await migrationJobsService.deleteJob(job.id)
    loadJobs()
  } catch (e) {
    toast.error('Errore eliminazione job', errorMessage(e))
  }
}

function formatDate(dateStr: string) {
  return new Date(dateStr).toLocaleString()
}

function getStatusClass(status?: string) {
  if (status === 'success' || status === 'OK') return 'badge-success'
  if (status === 'error' || status === 'failed') return 'badge-danger'
  if (status === 'running') return 'badge-warning'
  return 'badge-secondary'
}
</script>

<style scoped>
.text-xs { font-size: 0.75em; }
.mt-1 { margin-top: 4px; }
.text-sm { font-size: 0.85em; }
.btn-group { display: flex; gap: 4px; }
.btn-xs { padding: 4px 8px; font-size: 0.75rem; }
.badge-info { background: rgba(0, 212, 255, 0.15); color: #00d4ff; }
.badge-success { background: rgba(0, 184, 148, 0.15); color: #00b894; }
.badge-danger { background: rgba(255, 82, 82, 0.15); color: #ff5252; }
.badge-warning { background: rgba(255, 179, 0, 0.15); color: #ffb300; }
.badge-primary { background: rgba(108, 92, 231, 0.15); color: #6c5ce7; }
.empty-state-cell { text-align: center; padding: 40px; color: var(--text-secondary); }
.spinner-sm {
  display: inline-block;
  width: 12px; height: 12px;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.form-group { margin-bottom: 12px; }
.form-group label { display: block; margin-bottom: 4px; font-size: 0.85rem; color: var(--text-secondary); }
@media (max-width: 640px) { .grid-2 { grid-template-columns: 1fr; } }
</style>
