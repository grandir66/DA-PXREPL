<template>
  <div v-if="visible" class="jm-overlay">
    <div class="jm-modal">
      <header class="jm-head">
        <div class="jm-head-title">
          <span class="jm-mode" :class="`jm-mode-${form.kind}`">{{ modeLabel }}</span>
          <h2>{{ isEdit ? 'Modifica' : 'Nuova' }} {{ kindLabel }}</h2>
        </div>
        <button class="jm-close" @click="onClose" aria-label="Chiudi">×</button>
      </header>

      <nav class="jm-steps">
        <button
          v-for="(s, i) in steps"
          :key="s.id"
          type="button"
          class="jm-step"
          :class="{ active: currentStep === i, done: i < currentStep }"
          @click="goTo(i)"
          :disabled="!canJumpTo(i)"
        >
          <span class="jm-step-num">{{ i + 1 }}</span>
          <span class="jm-step-label">{{ s.label }}</span>
        </button>
      </nav>

      <section class="jm-body">
        <!-- ===== Step 1: Identità & sorgente ===== -->
        <div v-show="currentStep === 0" class="jm-section">
          <h3>Origine</h3>

          <div class="jm-grid">
            <div class="field field-full">
              <label>Nome job</label>
              <input
                v-model="form.name"
                type="text"
                class="form-input"
                placeholder="auto se vuoto"
                :disabled="isEdit && lockSource"
              />
            </div>

            <div class="field" v-if="!isEdit">
              <label>Modalità</label>
              <select v-model="form.kind" class="form-input" :disabled="isEdit">
                <option value="syncoid">Replica ZFS (Syncoid)</option>
                <option value="backup_pbs">Backup verso PBS</option>
                <option value="recovery_pbs">Replica via PBS (backup + restore)</option>
              </select>
            </div>

            <div class="field">
              <label>Nodo sorgente (PVE)</label>
              <select
                v-model.number="form.source_node_id"
                class="form-input"
                :disabled="isEdit && lockSource"
                @change="onSourceNodeChange"
              >
                <option :value="null">— seleziona —</option>
                <option v-for="n in store.pveNodes" :key="n.id" :value="n.id">
                  {{ n.name }} <span v-if="!n.is_online">(offline)</span>
                </option>
              </select>
            </div>

            <div class="field field-full">
              <label>Macchina virtuale</label>
              <div class="jm-vm-pick">
                <input
                  v-model="vmFilter"
                  type="text"
                  class="form-input"
                  placeholder="cerca per VMID o nome…"
                  :disabled="isEdit && lockSource"
                />
                <button
                  type="button"
                  class="btn btn-secondary btn-sm"
                  @click="reloadVMs"
                  :disabled="!form.source_node_id"
                >
                  ↻ Aggiorna
                </button>
              </div>

              <div class="jm-vm-list" v-if="filteredVMs.length">
                <button
                  v-for="vm in filteredVMs"
                  :key="String(vm.vmid)"
                  type="button"
                  class="jm-vm-item"
                  :class="{ active: String(form.vm_id) === String(vm.vmid) }"
                  @click="selectVM(vm)"
                  :disabled="isEdit && lockSource"
                >
                  <span class="jm-vm-id">#{{ vm.vmid }}</span>
                  <span class="jm-vm-name">{{ vm.name }}</span>
                  <span class="jm-vm-type" :class="`type-${vm.type}`">{{ vm.type }}</span>
                  <span class="jm-vm-status" :class="`s-${vm.status}`">{{ vm.status }}</span>
                </button>
              </div>
              <div v-else-if="form.source_node_id && !loadingDisks" class="jm-empty">
                Nessuna VM trovata. Aggiorna o seleziona un altro nodo.
              </div>
            </div>

            <div class="field field-full" v-if="form.vm_id">
              <label>Dischi della VM</label>
              <div v-if="loadingDisks" class="jm-empty">Caricamento dischi…</div>
              <table v-else-if="vmDisks.length" class="jm-disks">
                <thead>
                  <tr>
                    <th>Disco</th>
                    <th>Storage</th>
                    <th>Dataset/Volume</th>
                    <th class="num">Dimensione</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="d in vmDisks" :key="d.disk_name">
                    <td><code>{{ d.disk_name }}</code></td>
                    <td>
                      <span class="badge badge-outline">{{ d.storage || '—' }}</span>
                    </td>
                    <td><code class="muted">{{ d.dataset || d.volume || '—' }}</code></td>
                    <td class="num">{{ humanBytes(d.size_bytes) }}</td>
                  </tr>
                </tbody>
              </table>
              <div v-else class="jm-empty">Nessun disco rilevato (la VM potrebbe non esistere o avere storage non supportato).</div>
            </div>
          </div>
        </div>

        <!-- ===== Step 2: Destinazione ===== -->
        <div v-show="currentStep === 1" class="jm-section">
          <h3>Destinazione</h3>
          <div class="jm-grid">
            <div class="field" v-if="form.kind !== 'backup_pbs'">
              <label>Nodo destinazione (PVE)</label>
              <select v-model.number="form.dest_node_id" class="form-input">
                <option :value="null">— seleziona —</option>
                <option
                  v-for="n in pveDestNodes"
                  :key="n.id"
                  :value="n.id"
                >
                  {{ n.name }}
                </option>
              </select>
            </div>

            <div class="field" v-if="form.kind !== 'syncoid'">
              <label>Server PBS</label>
              <select v-model.number="form.pbs_node_id" class="form-input">
                <option :value="null">— seleziona —</option>
                <option v-for="n in store.pbsNodes" :key="n.id" :value="n.id">
                  {{ n.name }}
                </option>
              </select>
            </div>

            <div class="field" v-if="form.kind === 'syncoid'">
              <label>Storage ZFS destinazione</label>
              <StoragePicker
                v-model="form.dest_pool"
                :node-id="form.dest_node_id"
                :node-name="destNodeName"
                type="zfs"
              />
            </div>

            <div class="field" v-if="form.kind === 'syncoid'">
              <label>Sotto-cartella (opzionale)</label>
              <input
                v-model="form.dest_subfolder"
                type="text"
                class="form-input"
                placeholder="replica"
              />
              <small>I dataset finali saranno <code>{{ form.dest_pool || '<pool>' }}/{{ form.dest_subfolder || '' }}/vm-XXX-disk-N</code>.</small>
            </div>

            <div class="field field-full" v-if="form.kind !== 'syncoid'">
              <label>Datastore PBS</label>
              <input
                v-model="form.pbs_datastore"
                type="text"
                class="form-input"
                placeholder="lascia vuoto per usare il datastore di default del nodo PBS"
              />
            </div>

            <!-- recovery_pbs: anche storage di restore lato dest PVE -->
            <div class="field field-full" v-if="form.kind === 'recovery_pbs'">
              <label>Storage di restore (sul nodo PVE destinazione)</label>
              <StoragePicker
                v-model="form.restore_storage"
                :node-id="form.dest_node_id"
                :node-name="destNodeName"
                type="any"
              />
              <small>Nel restore via PBS lo storage può essere di qualunque tipo (ZFS, LVM, dir, …).</small>
            </div>
          </div>
        </div>

        <!-- ===== Step 3: Registrazione VM ===== -->
        <div v-show="currentStep === 2" class="jm-section">
          <h3>Registrazione VM sulla destinazione</h3>
          <p class="jm-help">
            Dopo ogni replica/backup-restore la VM viene creata sul nodo destinazione.
            Il valore di default è <strong>attivo</strong>.
          </p>
          <VMRegistrationFields
            v-model="form.registration"
            :dest-node-id="form.dest_node_id"
            :dest-node-name="destNodeName"
            :source-vmid="form.vm_id"
            :source-vm-name="form.vm_name"
            :storage-type="form.kind === 'syncoid' ? 'zfs' : 'any'"
            :show-start-vm="form.kind === 'recovery_pbs'"
            :show-overwrite="form.kind === 'recovery_pbs'"
          />
        </div>

        <!-- ===== Step 4: Pianificazione ===== -->
        <div v-show="currentStep === 3" class="jm-section">
          <h3>Pianificazione</h3>
          <ScheduleEditor v-model="form.schedule_config" @cron="form.schedule = $event" />
        </div>

        <!-- ===== Step 5: Avanzate & Notifiche ===== -->
        <div v-show="currentStep === 4" class="jm-section">
          <h3>Avanzate</h3>
          <div class="jm-grid">
            <template v-if="form.kind === 'syncoid'">
              <div class="field">
                <label>Compressione</label>
                <select v-model="form.compress" class="form-input">
                  <option value="lz4">lz4 (consigliato)</option>
                  <option value="zstd">zstd</option>
                  <option value="gzip">gzip</option>
                  <option value="none">nessuna</option>
                </select>
              </div>
              <div class="field">
                <label>mbuffer</label>
                <input v-model="form.mbuffer_size" class="form-input" placeholder="128M" />
              </div>
              <div class="field field-checkbox">
                <label class="checkbox-row">
                  <input type="checkbox" v-model="form.recursive" />
                  <span>Replica ricorsiva (incluse i dataset figli)</span>
                </label>
              </div>
              <div class="field">
                <label>Snapshot da mantenere su destinazione</label>
                <input
                  v-model.number="form.keep_snapshots"
                  type="number"
                  min="0"
                  max="365"
                  class="form-input"
                />
                <small>0 = solo l'ultima.</small>
              </div>
            </template>

            <template v-if="form.kind === 'backup_pbs' || form.kind === 'recovery_pbs'">
              <div class="field">
                <label>Modalità backup</label>
                <select v-model="form.backup_mode" class="form-input">
                  <option value="snapshot">snapshot (a caldo)</option>
                  <option value="suspend">suspend</option>
                  <option value="stop">stop</option>
                </select>
              </div>
              <div class="field">
                <label>Compressione backup</label>
                <select v-model="form.backup_compress" class="form-input">
                  <option value="zstd">zstd</option>
                  <option value="lzo">lzo</option>
                  <option value="gzip">gzip</option>
                  <option value="none">nessuna</option>
                </select>
              </div>
              <div class="field">
                <label>keep_last</label>
                <input v-model.number="form.keep_last" type="number" min="1" class="form-input" />
              </div>
            </template>
          </div>

          <h3 class="jm-h3-spaced">Notifiche</h3>
          <div class="jm-grid">
            <div class="field">
              <label>Quando notificare</label>
              <select v-model="form.notify_mode" class="form-input">
                <option value="daily">Riepilogo giornaliero</option>
                <option value="always">Ogni esecuzione</option>
                <option value="failure">Solo fallimenti</option>
                <option value="never">Mai</option>
              </select>
            </div>
            <div class="field">
              <label>Oggetto email (opzionale)</label>
              <input v-model="form.notify_subject" type="text" class="form-input" />
            </div>
          </div>
        </div>
      </section>

      <footer class="jm-foot">
        <div class="jm-foot-left">
          <span v-if="form.schedule" class="jm-summary-chip">
            <strong>Schedule:</strong>
            <code>{{ form.schedule }}</code>
          </span>
          <span v-if="form.vm_id" class="jm-summary-chip">
            <strong>VM:</strong> #{{ form.vm_id }} {{ form.vm_name || '' }}
          </span>
        </div>
        <div class="jm-foot-actions">
          <button class="btn btn-secondary" @click="onClose">Annulla</button>
          <button class="btn btn-secondary" :disabled="currentStep === 0" @click="prev">Indietro</button>
          <button
            v-if="currentStep < steps.length - 1"
            class="btn btn-primary"
            :disabled="!canAdvance"
            @click="next"
          >
            Avanti
          </button>
          <button v-else class="btn btn-primary" :disabled="!canSubmit || saving" @click="submit">
            <span v-if="saving">Salvataggio…</span>
            <span v-else>{{ isEdit ? 'Salva modifiche' : 'Crea job' }}</span>
          </button>
        </div>
      </footer>

      <div v-if="submitError" class="jm-error">
        {{ submitError }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useReplicationStore, type JobKind, type UnifiedJob } from '../../stores/replication'
import vmsService, { type VM } from '../../services/vms'
import apiClient from '../../services/api'
import syncJobsService from '../../services/syncJobs'
import backupJobsService from '../../services/backupJobs'
import recoveryJobsService from '../../services/recoveryJobs'
import type { ScheduleConfig } from '../../services/schedule'
import StoragePicker from './StoragePicker.vue'
import VMRegistrationFields, { type VMRegistration } from './VMRegistrationFields.vue'
import ScheduleEditor from './ScheduleEditor.vue'

interface DiskInfo {
  disk_name: string
  storage?: string
  dataset?: string
  volume?: string
  size_bytes?: number
}

interface FormState {
  kind: JobKind
  name: string
  source_node_id: number | null
  vm_id: number | null
  vm_name: string | null
  vm_type: 'qemu' | 'lxc'

  dest_node_id: number | null
  pbs_node_id: number | null
  dest_pool: string | null         // syncoid
  dest_subfolder: string | null    // syncoid
  pbs_datastore: string | null     // backup/recovery
  restore_storage: string | null   // recovery_pbs

  registration: VMRegistration
  schedule_config: ScheduleConfig | null
  schedule: string | null

  // syncoid advanced
  compress: string
  mbuffer_size: string
  recursive: boolean
  keep_snapshots: number

  // pbs advanced
  backup_mode: 'snapshot' | 'stop' | 'suspend'
  backup_compress: 'zstd' | 'lzo' | 'gzip' | 'none'
  keep_last: number

  // notifiche
  notify_mode: 'daily' | 'always' | 'failure' | 'never'
  notify_subject: string | null
}

interface PresetVm {
  vmid: number | string
  name?: string | null
  type?: 'qemu' | 'lxc' | string
  node_id?: number | string
}

const props = withDefaults(
  defineProps<{
    visible: boolean
    mode?: JobKind             // create mode iniziale
    job?: UnifiedJob | null    // se presente -> edit
    presetVm?: PresetVm | null // pre-compila step "Origine" da una VM
  }>(),
  {
    mode: 'syncoid',
    job: null,
    presetVm: null,
  }
)
const emit = defineEmits<{
  (e: 'update:visible', v: boolean): void
  (e: 'saved', job: any): void
}>()

const store = useReplicationStore()

const isEdit = computed(() => !!props.job)
const lockSource = computed(() => isEdit.value)

const steps = [
  { id: 'source', label: 'Origine' },
  { id: 'dest', label: 'Destinazione' },
  { id: 'reg', label: 'Registrazione VM' },
  { id: 'sched', label: 'Pianificazione' },
  { id: 'adv', label: 'Avanzate' },
]
const currentStep = ref(0)

const form = ref<FormState>(emptyForm(props.mode))

const vmFilter = ref('')
const vmDisks = ref<DiskInfo[]>([])
const loadingDisks = ref(false)
const saving = ref(false)
const submitError = ref<string | null>(null)

function emptyForm(kind: JobKind): FormState {
  return {
    kind,
    name: '',
    source_node_id: null,
    vm_id: null,
    vm_name: null,
    vm_type: 'qemu',
    dest_node_id: null,
    pbs_node_id: null,
    dest_pool: null,
    dest_subfolder: 'replica',
    pbs_datastore: null,
    restore_storage: null,
    registration: {
      register_vm: true,
      dest_vm_id: null,
      dest_vm_name: null,
      dest_vm_name_suffix: null,
      dest_storage: null,
      bridge: null,
      vlan: null,
      force_cpu_host: true,
      start_vm: false,
      overwrite_existing: true,
    },
    schedule_config: { kind: 'manual' },
    schedule: null,
    compress: 'lz4',
    mbuffer_size: '128M',
    recursive: false,
    keep_snapshots: 0,
    backup_mode: 'snapshot',
    backup_compress: 'zstd',
    keep_last: 7,
    notify_mode: 'daily',
    notify_subject: null,
  }
}

function hydrateFromJob(j: UnifiedJob) {
  const f = emptyForm(j.kind)
  f.name = j.name || ''
  f.source_node_id = (j.source_node_id ?? null) as any
  f.vm_id = (j.vm_id == null ? null : Number(j.vm_id)) as any
  f.vm_name = j.vm_name || null
  f.vm_type = (j.vm_type as any) || 'qemu'
  f.dest_node_id = (j.dest_node_id ?? null) as any
  f.pbs_node_id = (j.pbs_node_id ?? null) as any
  f.pbs_datastore = j.pbs_datastore ?? null

  // Da raw, gli specifici per tipo
  const r = j.raw || {}
  if (j.kind === 'syncoid') {
    f.dest_pool = r.dest_dataset?.split('/')[0] || null
    f.dest_subfolder = r.dest_subfolder || null
    f.compress = r.compress || 'lz4'
    f.mbuffer_size = r.mbuffer_size || '128M'
    f.recursive = !!r.recursive
    f.keep_snapshots = r.keep_snapshots ?? 0
    f.registration.dest_storage = r.dest_storage ?? null
    f.registration.dest_vm_id = r.dest_vm_id ?? null
    f.registration.dest_vm_name_suffix = r.dest_vm_name_suffix ?? null
    f.registration.register_vm = r.register_vm ?? true
    f.registration.force_cpu_host = r.force_cpu_host ?? true
  } else if (j.kind === 'backup_pbs') {
    f.backup_mode = r.backup_mode || 'snapshot'
    f.backup_compress = r.backup_compress || 'zstd'
    f.keep_last = r.keep_last ?? 7
  } else if (j.kind === 'recovery_pbs') {
    f.backup_mode = r.backup_mode || 'snapshot'
    f.backup_compress = r.backup_compress || 'zstd'
    f.restore_storage = r.dest_storage ?? null
    f.registration.dest_vm_id = r.dest_vm_id ?? null
    f.registration.dest_vm_name_suffix = r.dest_vm_name_suffix ?? null
    f.registration.start_vm = !!r.restore_start_vm
    f.registration.overwrite_existing = r.overwrite_existing !== false
  }

  f.schedule = j.schedule ?? null
  f.schedule_config =
    j.schedule_config && j.schedule_config.kind
      ? (j.schedule_config as ScheduleConfig)
      : { kind: 'manual' }
  f.notify_mode = r.notify_mode || 'daily'
  f.notify_subject = r.notify_subject ?? null
  return f
}

watch(
  () => props.visible,
  v => {
    if (!v) return
    submitError.value = null
    currentStep.value = 0
    if (props.job) {
      form.value = hydrateFromJob(props.job)
    } else {
      form.value = emptyForm(props.mode)
      if (props.presetVm && props.presetVm.node_id != null && props.presetVm.vmid != null) {
        form.value.source_node_id = Number(props.presetVm.node_id) as any
        form.value.vm_id = Number(props.presetVm.vmid) as any
        form.value.vm_name = props.presetVm.name || null
        form.value.vm_type = (props.presetVm.type as any) || 'qemu'
      }
    }
    if (form.value.source_node_id) reloadVMs()
    if (form.value.vm_id && form.value.source_node_id) loadDisks()
  }
)

const filteredVMs = computed(() => {
  const list = form.value.source_node_id
    ? store.vmsByNode(form.value.source_node_id)
    : []
  const q = vmFilter.value.trim().toLowerCase()
  if (!q) return list.slice(0, 50)
  return list
    .filter(
      v =>
        String(v.vmid).includes(q) ||
        (v.name || '').toLowerCase().includes(q)
    )
    .slice(0, 50)
})

const pveDestNodes = computed(() =>
  store.pveNodes.filter(n => n.id !== form.value.source_node_id)
)
const destNodeName = computed(
  () => store.nodeById(form.value.dest_node_id || undefined)?.name || ''
)

const modeLabel = computed(() => {
  switch (form.value.kind) {
    case 'syncoid':
      return 'ZFS / syncoid'
    case 'backup_pbs':
      return 'PBS · backup'
    case 'recovery_pbs':
      return 'PBS · backup + restore'
  }
})
const kindLabel = computed(() => {
  switch (form.value.kind) {
    case 'syncoid':
      return 'replica ZFS'
    case 'backup_pbs':
      return 'backup PBS'
    case 'recovery_pbs':
      return 'replica PBS'
  }
})

const canAdvance = computed(() => {
  if (currentStep.value === 0) {
    return !!(form.value.source_node_id && form.value.vm_id)
  }
  if (currentStep.value === 1) {
    if (form.value.kind === 'syncoid')
      return !!(form.value.dest_node_id && form.value.dest_pool)
    if (form.value.kind === 'backup_pbs') return !!form.value.pbs_node_id
    if (form.value.kind === 'recovery_pbs')
      return !!(form.value.dest_node_id && form.value.pbs_node_id)
  }
  return true
})
const canSubmit = computed(() => canAdvance.value && !!form.value.vm_id)

function canJumpTo(i: number) {
  if (i <= currentStep.value) return true
  // permetti di saltare avanti solo se i step precedenti sono validi
  return canAdvance.value
}

function next() {
  if (!canAdvance.value) return
  currentStep.value = Math.min(steps.length - 1, currentStep.value + 1)
}
function prev() {
  currentStep.value = Math.max(0, currentStep.value - 1)
}
function goTo(i: number) {
  if (canJumpTo(i)) currentStep.value = i
}

async function reloadVMs() {
  if (!form.value.source_node_id) return
  try {
    await store.fetchNodes()
    const r = await vmsService.getNodeVMs(form.value.source_node_id)
    // L'endpoint /nodes/{id}/vms NON include node_id nel payload — va aggiunto
    // qui altrimenti vmsByNode() del store le scarta tutte (filtra per node_id).
    const nodeId = Number(form.value.source_node_id)
    const fresh = (r.data as VM[]).map(v => ({ ...v, node_id: nodeId }))
    const others = store.vms.filter(v => Number(v.node_id || 0) !== nodeId)
    store.$patch({ vms: [...others, ...fresh] })
  } catch (e) {
    // ignore: il filtro mostrerà semplicemente lista vuota
  }
}

function selectVM(vm: VM) {
  form.value.vm_id = Number(vm.vmid)
  form.value.vm_name = vm.name || null
  form.value.vm_type = (vm.type as any) || 'qemu'
  loadDisks()
}

async function loadDisks() {
  if (!form.value.source_node_id || !form.value.vm_id) return
  loadingDisks.value = true
  try {
    // Endpoint /vms/node/{id}/vm/{vmid}/full-details ritorna anche dischi
    const r = await apiClient.get(
      `/vms/node/${form.value.source_node_id}/vm/${form.value.vm_id}/full-details?vm_type=${form.value.vm_type}`
    )
    const data: any = r.data || {}
    const disks: DiskInfo[] = (data.disks || data.disks_info || []).map((d: any) => ({
      disk_name: d.disk_name || d.name || d.disk,
      storage: d.storage,
      dataset: d.dataset,
      volume: d.volume,
      size_bytes: d.size_bytes ?? d.size,
    }))
    vmDisks.value = disks
  } catch {
    vmDisks.value = []
  } finally {
    loadingDisks.value = false
  }
}

function onSourceNodeChange() {
  form.value.vm_id = null
  form.value.vm_name = null
  vmDisks.value = []
  reloadVMs()
}

function humanBytes(v: any) {
  if (v == null) return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v)
  const u = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB']
  let i = 0
  let x = n
  while (x >= 1024 && i < u.length - 1) {
    x /= 1024
    i++
  }
  return `${x.toFixed(x < 10 && i > 0 ? 1 : 0)} ${u[i]}`
}

function buildSyncoidPayload() {
  return {
    vm_id: form.value.vm_id,
    vm_type: form.value.vm_type,
    vm_name: form.value.vm_name,
    source_node_id: form.value.source_node_id,
    dest_node_id: form.value.dest_node_id,
    dest_pool: form.value.dest_pool,
    dest_subfolder: form.value.dest_subfolder || '',
    dest_storage: form.value.registration.dest_storage,
    dest_vm_id: form.value.registration.dest_vm_id,
    dest_vm_name_suffix: form.value.registration.dest_vm_name_suffix,
    schedule: form.value.schedule,
    schedule_config: form.value.schedule_config,
    compress: form.value.compress,
    recursive: form.value.recursive,
    register_vm: form.value.registration.register_vm,
    keep_snapshots: form.value.keep_snapshots,
    sync_method: 'syncoid',
  }
}

function buildBackupPayload() {
  return {
    name: form.value.name || `backup-${form.value.vm_id}`,
    source_node_id: form.value.source_node_id,
    vm_id: form.value.vm_id,
    vm_type: form.value.vm_type,
    vm_name: form.value.vm_name,
    pbs_node_id: form.value.pbs_node_id,
    pbs_datastore: form.value.pbs_datastore,
    backup_mode: form.value.backup_mode,
    backup_compress: form.value.backup_compress,
    include_all_disks: true,
    keep_last: form.value.keep_last,
    schedule: form.value.schedule,
    schedule_config: form.value.schedule_config,
    is_active: true,
    notify_on_each_run: form.value.notify_mode === 'always',
    notify_on_failure: form.value.notify_mode !== 'never',
  }
}

function buildRecoveryPayload() {
  return {
    name: form.value.name || `recovery-${form.value.vm_id}`,
    source_node_id: form.value.source_node_id,
    vm_id: form.value.vm_id,
    vm_type: form.value.vm_type,
    vm_name: form.value.vm_name,
    pbs_node_id: form.value.pbs_node_id,
    pbs_datastore: form.value.pbs_datastore,
    dest_node_id: form.value.dest_node_id,
    dest_vm_id: form.value.registration.dest_vm_id,
    dest_vm_name_suffix: form.value.registration.dest_vm_name_suffix,
    dest_storage: form.value.restore_storage,
    backup_mode: form.value.backup_mode,
    backup_compress: form.value.backup_compress,
    include_all_disks: true,
    restore_start_vm: !!form.value.registration.start_vm,
    restore_unique: true,
    overwrite_existing: form.value.registration.overwrite_existing !== false,
    schedule: form.value.schedule,
    schedule_config: form.value.schedule_config,
    is_active: true,
    notify_on_each_run: form.value.notify_mode === 'always',
  }
}

async function submit() {
  saving.value = true
  submitError.value = null
  try {
    if (!isEdit.value) {
      // CREATE
      let r: any
      if (form.value.kind === 'syncoid') {
        r = await syncJobsService.createVMReplica(buildSyncoidPayload())
      } else if (form.value.kind === 'backup_pbs') {
        r = await apiClient.post('/backup-jobs', buildBackupPayload())
      } else {
        r = await recoveryJobsService.createJob(buildRecoveryPayload() as any)
      }
      emit('saved', r?.data)
    } else {
      // UPDATE
      const id = props.job!.id
      let r: any
      if (form.value.kind === 'syncoid') {
        // Edit del singolo job: aggiorna i campi modificabili.
        r = await syncJobsService.updateJob(String(id), {
          name: form.value.name,
          schedule: form.value.schedule,
          schedule_config: form.value.schedule_config,
          compress: form.value.compress,
          recursive: form.value.recursive,
          keep_snapshots: form.value.keep_snapshots,
          register_vm: form.value.registration.register_vm,
          dest_vm_id: form.value.registration.dest_vm_id,
          dest_vm_name_suffix: form.value.registration.dest_vm_name_suffix,
          dest_storage: form.value.registration.dest_storage,
          force_cpu_host: form.value.registration.force_cpu_host,
          notify_mode: form.value.notify_mode,
          notify_subject: form.value.notify_subject,
        } as any)
      } else if (form.value.kind === 'backup_pbs') {
        r = await apiClient.put(`/backup-jobs/${id}`, {
          name: form.value.name,
          schedule: form.value.schedule,
          schedule_config: form.value.schedule_config,
          backup_mode: form.value.backup_mode,
          backup_compress: form.value.backup_compress,
          keep_last: form.value.keep_last,
          notify_on_each_run: form.value.notify_mode === 'always',
          notify_on_failure: form.value.notify_mode !== 'never',
        })
      } else {
        r = await recoveryJobsService.updateJob(String(id), {
          name: form.value.name,
          schedule: form.value.schedule,
          schedule_config: form.value.schedule_config,
          backup_mode: form.value.backup_mode,
          backup_compress: form.value.backup_compress,
          dest_storage: form.value.restore_storage,
          dest_vm_id: form.value.registration.dest_vm_id,
          dest_vm_name_suffix: form.value.registration.dest_vm_name_suffix,
          restore_start_vm: !!form.value.registration.start_vm,
          overwrite_existing: form.value.registration.overwrite_existing !== false,
        } as any)
      }
      emit('saved', r?.data)
    }
    // Aggiorna lo store e chiudi
    await store.fetchJobs()
    onClose()
  } catch (e: any) {
    submitError.value =
      e?.response?.data?.detail || e?.message || 'Errore imprevisto durante il salvataggio.'
  } finally {
    saving.value = false
  }
}

async function onClose() {
  // Se l'utente ha toccato il form (vm selezionata o step > 0) chiediamo
  // conferma prima di chiudere — un Esc accidentale non deve perdere il
  // lavoro. In modalita' edit chiediamo sempre conferma.
  const dirty = isEdit.value || currentStep.value > 0 || !!form.value.vm_id
  if (dirty) {
    const { confirmDangerous } = await import('../../stores/confirm')
    const ok = await confirmDangerous(
      isEdit.value ? 'Annullare le modifiche?' : 'Annullare la creazione?',
      'I dati inseriti andranno persi.',
      'Annulla'
    )
    if (!ok) return
  }
  emit('update:visible', false)
}

// Esc per chiudere (con conferma se ci sono dati).
function onKeydown(e: KeyboardEvent) {
  if (!props.visible) return
  if (e.key === 'Escape') {
    e.preventDefault()
    onClose()
  }
}
import { onMounted, onUnmounted } from 'vue'
onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
.jm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  backdrop-filter: blur(6px);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
}
.jm-modal {
  width: min(960px, 96vw);
  max-height: 92vh;
  display: flex;
  flex-direction: column;
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}
.jm-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}
.jm-head-title {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.jm-head h2 {
  margin: 0;
  font-size: 1.1rem;
  color: var(--color-text-primary);
}
.jm-mode {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  color: var(--color-text-secondary);
}
.jm-mode-syncoid {
  border-color: var(--color-zfs);
  color: var(--color-zfs);
}
.jm-mode-backup_pbs,
.jm-mode-recovery_pbs {
  border-color: var(--color-pbs);
  color: var(--color-pbs);
}
.jm-close {
  background: none;
  border: 0;
  color: var(--color-text-secondary);
  font-size: 1.5rem;
  cursor: pointer;
  line-height: 1;
}
.jm-close:hover {
  color: var(--color-text-primary);
}
.jm-steps {
  display: flex;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-bg-body);
}
.jm-step {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-3);
  background: none;
  border: 0;
  color: var(--color-text-secondary);
  cursor: pointer;
  font-size: 0.82rem;
  border-bottom: 2px solid transparent;
}
.jm-step:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
.jm-step.active {
  color: var(--color-primary);
  border-bottom-color: var(--color-primary);
  background: var(--color-primary-dim);
}
.jm-step.done {
  color: var(--color-success-fg);
}
.jm-step-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 999px;
  background: var(--color-bg-element);
  font-size: 0.75rem;
  font-weight: 700;
}
.jm-step.active .jm-step-num {
  background: var(--color-primary);
  color: #0b1320;
}
.jm-step.done .jm-step-num {
  background: var(--color-success);
  color: #0b1320;
}

.jm-body {
  padding: var(--space-5);
  overflow-y: auto;
  flex: 1;
}
.jm-section h3 {
  margin: 0 0 var(--space-3);
  font-size: 0.95rem;
  color: var(--color-text-primary);
}
.jm-h3-spaced {
  margin-top: var(--space-5);
}
.jm-help {
  margin: 0 0 var(--space-3);
  font-size: 0.85rem;
  color: var(--color-text-secondary);
}
.jm-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.field-full {
  grid-column: 1 / -1;
}
.field-checkbox {
  grid-column: 1 / -1;
}
.field label {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--color-text-secondary);
}
.field small {
  font-size: 0.72rem;
  color: var(--color-text-secondary);
}
.checkbox-row {
  display: inline-flex !important;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
  font-weight: 500 !important;
  color: var(--color-text-primary) !important;
}

.jm-vm-pick {
  display: flex;
  gap: var(--space-2);
}
.jm-vm-list {
  margin-top: var(--space-2);
  display: flex;
  flex-direction: column;
  gap: 0;
  max-height: 240px;
  overflow-y: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-body);
}
.jm-vm-item {
  background: transparent;
  border: 0;
  border-bottom: 1px solid var(--color-border);
  display: grid;
  grid-template-columns: 70px 1fr 80px 90px;
  gap: var(--space-2);
  align-items: center;
  padding: var(--space-2) var(--space-3);
  text-align: left;
  cursor: pointer;
  color: var(--color-text-primary);
}
.jm-vm-item:last-child {
  border-bottom: 0;
}
.jm-vm-item:hover {
  background: var(--color-bg-hover);
}
.jm-vm-item.active {
  background: var(--color-primary-dim);
  border-left: 2px solid var(--color-primary);
}
.jm-vm-id {
  font-family: var(--font-mono);
  color: var(--color-text-secondary);
  font-size: 0.78rem;
}
.jm-vm-name {
  font-weight: 600;
  font-size: 0.88rem;
}
.jm-vm-type {
  font-size: 0.7rem;
  text-transform: uppercase;
  padding: 1px 6px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  color: var(--color-text-secondary);
}
.jm-vm-type.type-qemu {
  border-color: var(--color-info-fg);
  color: var(--color-info-fg);
}
.jm-vm-type.type-lxc {
  border-color: var(--color-zfs);
  color: var(--color-zfs);
}
.jm-vm-status {
  font-size: 0.7rem;
  text-align: right;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.jm-vm-status.s-running {
  color: var(--color-success-fg);
}
.jm-vm-status.s-stopped {
  color: var(--color-text-tertiary);
}

.jm-disks {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
}
.jm-disks th,
.jm-disks td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid var(--color-border);
}
.jm-disks th {
  color: var(--color-text-secondary);
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-weight: 600;
}
.jm-disks td.num,
.jm-disks th.num {
  text-align: right;
  font-family: var(--font-mono);
}
.jm-disks code {
  font-family: var(--font-mono);
  color: var(--color-text-primary);
}
.jm-disks code.muted {
  color: var(--color-text-secondary);
}

.jm-empty {
  padding: var(--space-3);
  text-align: center;
  color: var(--color-text-secondary);
  font-size: 0.82rem;
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-md);
}

.jm-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-5);
  border-top: 1px solid var(--color-border);
  gap: var(--space-3);
}
.jm-foot-left {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.jm-foot-actions {
  display: flex;
  gap: var(--space-2);
}
.jm-summary-chip {
  font-size: 0.78rem;
  padding: 4px 8px;
  background: var(--color-bg-element);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  color: var(--color-text-secondary);
}
.jm-summary-chip code {
  font-family: var(--font-mono);
  color: var(--color-text-primary);
  background: transparent;
  padding: 0;
}
.jm-summary-chip strong {
  color: var(--color-text-primary);
  margin-right: 4px;
}
.jm-error {
  margin: 0 var(--space-5) var(--space-4);
  padding: var(--space-2) var(--space-3);
  background: var(--color-danger-dim);
  color: var(--color-danger-fg);
  border-radius: var(--radius-md);
  font-size: 0.82rem;
}

@media (max-width: 720px) {
  .jm-grid {
    grid-template-columns: 1fr;
  }
  .jm-vm-item {
    grid-template-columns: 60px 1fr 70px;
  }
  .jm-vm-status {
    display: none;
  }
}
</style>
