<script setup lang="ts">
import axios from 'axios'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  vmSnapshotsApi,
  type VmIndexEntry,
  type VmSnapshotJob,
  type VmTargetRef,
} from '../../services/vmSnapshots'

const props = defineProps<{
  job?: VmSnapshotJob | null
  existingJobs?: VmSnapshotJob[]
}>()

const emit = defineEmits<{ saved: []; close: [] }>()

const isEdit = computed(() => !!props.job?.id)
const step = ref(1)
const saving = ref(false)
const errorMsg = ref('')

const vmIndex = ref<VmIndexEntry[]>([])
const indexLoading = ref(false)
const indexError = ref('')
const vmFilter = ref('')
const preview = ref<VmIndexEntry[]>([])
const previewLoading = ref(false)

const form = reactive({
  name: '',
  description: '',
  label: 'daily',
  keep: 7,
  include_vmstate: false,
  targets: [] as VmTargetRef[],
  sel_tags: [] as string[],
  sel_node_ids: [] as number[],
  sel_exclude: '',
  schedule: '0 3 * * *',
  is_active: true,
  notify_mode: 'failure' as 'never' | 'failure' | 'always' | 'daily',
  notify_subject: '',
})

const labelValid = computed(() => /^[a-z][a-z0-9]{1,15}$/.test(form.label))
const labelConflict = computed(() => {
  const others = (props.existingJobs || []).filter(
    (j) => j.label === form.label && j.is_active && j.id !== props.job?.id,
  )
  return others.map((j) => j.name)
})

const allTags = computed(() => {
  const tags = new Set<string>()
  vmIndex.value.forEach((vm) => vm.tags.forEach((t) => tags.add(t)))
  return [...tags].sort()
})
const allNodes = computed(() => {
  const nodes = new Map<number, string>()
  vmIndex.value.forEach((vm) => nodes.set(vm.node_id, vm.node_name))
  return [...nodes.entries()].map(([id, name]) => ({ id, name }))
})
const vmsByNode = computed(() => {
  const filter = vmFilter.value.trim().toLowerCase()
  const groups = new Map<string, VmIndexEntry[]>()
  for (const vm of vmIndex.value) {
    if (
      filter &&
      !String(vm.vmid).includes(filter) &&
      !vm.name.toLowerCase().includes(filter) &&
      !vm.tags.some((t) => t.toLowerCase().includes(filter))
    )
      continue
    const list = groups.get(vm.node_name) || []
    list.push(vm)
    groups.set(vm.node_name, list)
  }
  return groups
})

function targetKey(vm: { node_id: number; vmid: number }) {
  return `${vm.node_id}:${vm.vmid}`
}
const selectedKeys = computed(() => new Set(form.targets.map(targetKey)))

function toggleTarget(vm: VmIndexEntry) {
  const key = targetKey(vm)
  if (selectedKeys.value.has(key)) {
    form.targets = form.targets.filter((t) => targetKey(t) !== key)
  } else {
    form.targets = [
      ...form.targets,
      { node_id: vm.node_id, vmid: vm.vmid, vm_type: vm.vm_type, name: vm.name, node_name: vm.node_name },
    ]
  }
}

function toggleNodeAll(vms: VmIndexEntry[]) {
  const allSelected = vms.every((vm) => selectedKeys.value.has(targetKey(vm)))
  if (allSelected) {
    const keys = new Set(vms.map(targetKey))
    form.targets = form.targets.filter((t) => !keys.has(targetKey(t)))
  } else {
    const missing = vms.filter((vm) => !selectedKeys.value.has(targetKey(vm)))
    form.targets = [
      ...form.targets,
      ...missing.map((vm) => ({
        node_id: vm.node_id, vmid: vm.vmid, vm_type: vm.vm_type,
        name: vm.name, node_name: vm.node_name,
      })),
    ]
  }
}

function buildSelectors() {
  return {
    tags: form.sel_tags,
    node_ids: form.sel_node_ids,
    exclude_vmids: form.sel_exclude
      .split(',')
      .map((s) => parseInt(s.trim(), 10))
      .filter((n) => !Number.isNaN(n)),
  }
}

const hasSelection = computed(
  () => form.targets.length > 0 || form.sel_tags.length > 0 || form.sel_node_ids.length > 0,
)

async function refreshPreview() {
  if (!hasSelection.value) {
    preview.value = []
    return
  }
  previewLoading.value = true
  try {
    const { data } = await vmSnapshotsApi.resolvePreview(form.targets, buildSelectors())
    preview.value = data
  } catch {
    preview.value = []
  } finally {
    previewLoading.value = false
  }
}

watch(
  () => [form.targets, form.sel_tags, form.sel_node_ids, form.sel_exclude],
  () => { void refreshPreview() },
  { deep: true },
)

async function loadIndex() {
  indexLoading.value = true
  indexError.value = ''
  try {
    const { data } = await vmSnapshotsApi.vmIndex()
    vmIndex.value = data
  } catch (e: unknown) {
    indexError.value = axios.isAxiosError(e)
      ? String(e.response?.data?.detail || e.message)
      : 'Errore caricamento VM'
  } finally {
    indexLoading.value = false
  }
}

function loadFromJob(job: VmSnapshotJob) {
  form.name = job.name
  form.description = job.description || ''
  form.label = job.label
  form.keep = job.keep
  form.include_vmstate = job.include_vmstate
  form.targets = [...(job.targets || [])]
  form.sel_tags = [...(job.selectors?.tags || [])]
  form.sel_node_ids = [...(job.selectors?.node_ids || [])]
  form.sel_exclude = (job.selectors?.exclude_vmids || []).join(', ')
  form.schedule = job.schedule || ''
  form.is_active = job.is_active
  form.notify_mode = (job.notify_mode as typeof form.notify_mode) || 'failure'
  form.notify_subject = job.notify_subject || ''
  step.value = 1
  errorMsg.value = ''
}

function resetForm() {
  form.name = ''
  form.description = ''
  form.label = 'daily'
  form.keep = 7
  form.include_vmstate = false
  form.targets = []
  form.sel_tags = []
  form.sel_node_ids = []
  form.sel_exclude = ''
  form.schedule = '0 3 * * *'
  form.is_active = true
  form.notify_mode = 'failure'
  form.notify_subject = ''
  step.value = 1
  errorMsg.value = ''
}

async function submit() {
  if (!form.name || !labelValid.value || !hasSelection.value) return
  saving.value = true
  errorMsg.value = ''
  try {
    const payload = {
      name: form.name,
      description: form.description || null,
      label: form.label,
      keep: form.keep,
      include_vmstate: form.include_vmstate,
      targets: form.targets,
      selectors: buildSelectors(),
      schedule: form.schedule || null,
      is_active: form.is_active,
      notify_mode: form.notify_mode,
      notify_subject: form.notify_subject.trim() || null,
    }
    if (isEdit.value && props.job) {
      await vmSnapshotsApi.update(props.job.id, payload)
    } else {
      await vmSnapshotsApi.create(payload)
    }
    emit('saved')
    if (!isEdit.value) resetForm()
  } catch (e: unknown) {
    if (axios.isAxiosError(e)) {
      const detail = e.response?.data?.detail
      errorMsg.value = typeof detail === 'string' ? detail : JSON.stringify(detail || e.message)
    } else {
      errorMsg.value = e instanceof Error ? e.message : 'Salvataggio fallito'
    }
  } finally {
    saving.value = false
  }
}

watch(
  () => props.job,
  (job) => {
    if (job) loadFromJob(job)
    else resetForm()
    void refreshPreview()
  },
  { immediate: true },
)

onMounted(loadIndex)
</script>

<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal-card">
      <header class="modal-head">
        <h2>{{ isEdit ? 'Modifica job Snapshot VM' : 'Nuovo job Snapshot VM' }}</h2>
        <button type="button" class="btn btn-sm" @click="$emit('close')">✕</button>
      </header>

      <nav class="steps">
        <span :class="{ active: step === 1 }">1. Selezione VM</span>
        <span :class="{ active: step === 2 }">2. Politica</span>
        <span :class="{ active: step === 3 }">3. Schedule</span>
        <span :class="{ active: step === 4 }">4. Riepilogo</span>
      </nav>

      <div v-show="step === 1" class="modal-body">
        <div class="form-group">
          <label>Nome job</label>
          <input v-model="form.name" class="form-input" placeholder="Snapshot giornaliero prod" />
        </div>

        <p v-if="indexError" class="text-danger">{{ indexError }}</p>
        <p v-else-if="indexLoading" class="text-muted">Caricamento VM dai cluster…</p>

        <div class="form-group">
          <label>Cerca VM (id / nome / tag)</label>
          <input v-model="vmFilter" class="form-input" placeholder="filtra…" />
        </div>

        <div class="vm-picker">
          <div v-for="[nodeName, vms] in vmsByNode" :key="nodeName" class="vm-node-group">
            <div class="vm-node-head">
              <label class="checkbox-label">
                <input
                  type="checkbox"
                  :checked="vms.every((vm) => selectedKeys.has(`${vm.node_id}:${vm.vmid}`))"
                  @change="toggleNodeAll(vms)"
                />
                <strong>{{ nodeName }}</strong> ({{ vms.length }} VM)
              </label>
            </div>
            <label
              v-for="vm in vms"
              :key="`${vm.node_id}:${vm.vmid}`"
              class="checkbox-label vm-row"
            >
              <input
                type="checkbox"
                :checked="selectedKeys.has(`${vm.node_id}:${vm.vmid}`)"
                @change="toggleTarget(vm)"
              />
              <code>{{ vm.vmid }}</code> {{ vm.name }}
              <span class="badge vm-type">{{ vm.vm_type === 'lxc' ? 'CT' : 'VM' }}</span>
              <span class="badge" :class="vm.status === 'running' ? 'badge-ok' : 'badge-off'">
                {{ vm.status }}
              </span>
              <span v-for="tag in vm.tags" :key="tag" class="badge badge-tag">{{ tag }}</span>
              <span
                v-if="vm.has_pvesr"
                class="badge badge-warn"
                title="Questa VM ha una replica pvesr attiva: pvesr può rimuovere snapshot non suoi e un rollback può invalidare la replica"
              >⚠ pvesr</span>
            </label>
          </div>
        </div>

        <fieldset class="sel-box">
          <legend>Selettori dinamici (le VM nuove che corrispondono entrano da sole nel job)</legend>
          <div class="grid-2">
            <div class="form-group">
              <label>Tutte le VM con tag</label>
              <select v-model="form.sel_tags" multiple class="form-input" size="4">
                <option v-for="tag in allTags" :key="tag" :value="tag">{{ tag }}</option>
              </select>
            </div>
            <div class="form-group">
              <label>Tutte le VM dei nodi</label>
              <select v-model="form.sel_node_ids" multiple class="form-input" size="4">
                <option v-for="node in allNodes" :key="node.id" :value="node.id">{{ node.name }}</option>
              </select>
            </div>
          </div>
          <div class="form-group">
            <label>Escludi VMID (separati da virgola)</label>
            <input v-model="form.sel_exclude" class="form-input" placeholder="105, 210" />
          </div>
        </fieldset>

        <p class="text-muted preview-line">
          <template v-if="previewLoading">Calcolo anteprima…</template>
          <template v-else-if="hasSelection">
            <strong>{{ preview.length }}</strong> VM verranno processate da questo job.
            <span v-if="preview.some((vm) => vm.warning === 'not_found')" class="text-danger">
              Alcune VM selezionate non esistono più.
            </span>
          </template>
          <template v-else>Seleziona VM con le checkbox oppure con i selettori dinamici.</template>
        </p>
      </div>

      <div v-show="step === 2" class="modal-body">
        <div class="grid-2">
          <div class="form-group">
            <label>Label (classe snapshot)</label>
            <input v-model="form.label" class="form-input" placeholder="daily" />
            <small class="text-muted">
              Minuscolo, solo lettere/cifre (es. hourly, daily, weekly). Nome snapshot:
              <code>auto{{ labelValid ? form.label : '…' }}_AAAAMMGG_HHMMSS</code>
            </small>
            <small v-if="form.label && !labelValid" class="text-danger d-block">Label non valido.</small>
            <small v-if="labelConflict.length" class="text-warning d-block">
              ⚠ Label già usato dai job: {{ labelConflict.join(', ') }}. Se i job condividono VM,
              le retention si cancelleranno gli snapshot a vicenda.
            </small>
          </div>
          <div class="form-group">
            <label>Copie da mantenere (keep)</label>
            <input v-model.number="form.keep" type="number" min="1" max="100" class="form-input" />
            <small class="text-muted">
              A ogni run, gli snapshot <code>auto{{ form.label }}_*</code> oltre le {{ form.keep }}
              copie più recenti vengono eliminati. Snapshot manuali e di Sanoid non vengono mai toccati.
            </small>
          </div>
        </div>
        <label class="checkbox-label mt-2">
          <input v-model="form.include_vmstate" type="checkbox" />
          Includi RAM (vmstate) per le VM qemu accese
        </label>
        <p class="text-muted">
          Default consigliato: OFF. Con RAM lo snapshot è più lento e occupa più spazio;
          i container LXC non supportano vmstate (per loro è ignorato).
        </p>
        <div class="form-group mt-2">
          <label>Descrizione (opzionale)</label>
          <input v-model="form.description" class="form-input" />
        </div>
      </div>

      <div v-show="step === 3" class="modal-body">
        <div class="form-group">
          <label>Cron schedule (vuoto = solo manuale)</label>
          <input v-model="form.schedule" class="form-input" placeholder="0 3 * * *" />
          <small class="text-muted">Esempi: <code>0 * * * *</code> ogni ora · <code>0 3 * * *</code> ogni notte alle 3 · <code>0 3 * * 0</code> ogni domenica.</small>
        </div>
        <div class="preset-row">
          <button type="button" class="btn btn-sm btn-secondary" @click="form.schedule = '0 * * * *'">Ogni ora</button>
          <button type="button" class="btn btn-sm btn-secondary" @click="form.schedule = '0 3 * * *'">Ogni notte</button>
          <button type="button" class="btn btn-sm btn-secondary" @click="form.schedule = '0 3 * * 0'">Settimanale</button>
          <button type="button" class="btn btn-sm btn-secondary" @click="form.schedule = ''">Solo manuale</button>
        </div>
        <div class="form-group mt-3">
          <label>Notifiche email</label>
          <select v-model="form.notify_mode" class="form-input">
            <option value="failure">Solo fallimenti o esiti parziali (consigliato)</option>
            <option value="daily">Riepilogo giornaliero + errori</option>
            <option value="always">Ogni esecuzione</option>
            <option value="never">Mai</option>
          </select>
        </div>
        <div class="form-group">
          <label>Oggetto email (opzionale)</label>
          <input v-model="form.notify_subject" class="form-input" placeholder="Snapshot VM prod" />
        </div>
      </div>

      <div v-show="step === 4" class="modal-body">
        <ul class="summary-list">
          <li><strong>{{ preview.length }}</strong> VM selezionate
            ({{ form.targets.length }} esplicite<span v-if="form.sel_tags.length || form.sel_node_ids.length">
              + selettori {{ form.sel_tags.length ? 'tag: ' + form.sel_tags.join(', ') : '' }}
              {{ form.sel_node_ids.length ? 'nodi selezionati' : '' }}</span>)
          </li>
          <li>Label <code>{{ form.label }}</code> — mantieni <strong>{{ form.keep }}</strong> copie</li>
          <li>RAM/vmstate: <strong>{{ form.include_vmstate ? 'Sì (solo qemu)' : 'No' }}</strong></li>
          <li>Schedule: <code>{{ form.schedule || 'solo manuale' }}</code></li>
          <li v-if="preview.some((vm) => vm.has_pvesr)" class="text-warning">
            ⚠ {{ preview.filter((vm) => vm.has_pvesr).length }} VM hanno replica pvesr attiva:
            verrà segnalato un avviso a ogni run.
          </li>
        </ul>
        <p class="text-muted">
          Gli snapshot sono nativi Proxmox: visibili anche nella UI Proxmox e ripristinabili
          da qui col pulsante «Snapshot» del job. Nessuna interferenza con Sanoid/Syncoid
          (prefisso <code>auto{{ form.label }}_</code> ≠ <code>autosnap_</code>).
        </p>
      </div>

      <p v-if="errorMsg" class="modal-error">{{ errorMsg }}</p>

      <footer class="modal-foot">
        <button v-if="step > 1" type="button" class="btn btn-secondary" @click="step--">Indietro</button>
        <button
          v-if="step < 4"
          type="button"
          class="btn btn-primary"
          :disabled="step === 1 && (!form.name || !hasSelection)"
          @click="step++"
        >Avanti</button>
        <button
          v-else
          type="button"
          class="btn btn-primary"
          :disabled="saving || !form.name || !labelValid || !hasSelection"
          @click="submit"
        >
          {{ saving ? 'Salvataggio…' : isEdit ? 'Salva modifiche' : 'Crea job' }}
        </button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.55);
  display: flex; align-items: center; justify-content: center; z-index: 1000;
}
.modal-card {
  background: var(--bg-primary, #111); border-radius: 12px;
  width: min(760px, 94vw); max-height: 90vh; overflow: auto;
}
.modal-head, .modal-foot { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; }
.modal-body { padding: 0 20px 16px; }
.modal-error { padding: 0 20px 12px; color: var(--danger, #e74c3c); font-size: .875rem; }
.steps { display: flex; gap: 12px; padding: 0 20px 12px; font-size: .85rem; opacity: .7; }
.steps .active { opacity: 1; font-weight: 600; }
.vm-picker { max-height: 260px; overflow-y: auto; border: 1px solid var(--border-color, #333); border-radius: 8px; padding: 8px 12px; margin-bottom: 12px; }
.vm-node-group { margin-bottom: 8px; }
.vm-node-head { border-bottom: 1px solid var(--border-color, #333); padding-bottom: 4px; margin-bottom: 4px; }
.vm-row { display: flex; align-items: center; gap: 6px; padding: 2px 0 2px 18px; flex-wrap: wrap; }
.sel-box { border: 1px solid var(--border-color, #333); border-radius: 8px; padding: 10px 14px; margin-bottom: 8px; }
.badge { font-size: .7rem; padding: 1px 7px; border-radius: 10px; background: rgba(255,255,255,.08); }
.badge-ok { background: rgba(46, 204, 113, .18); color: #2ecc71; }
.badge-off { opacity: .6; }
.badge-tag { background: rgba(52, 152, 219, .18); color: #3498db; }
.badge-warn { background: rgba(241, 196, 15, .18); color: #f1c40f; }
.vm-type { background: rgba(155, 89, 182, .18); color: #9b59b6; }
.preview-line { margin-top: 4px; }
.preset-row { display: flex; gap: 8px; flex-wrap: wrap; }
.summary-list { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.mt-2 { margin-top: 8px; }
.mt-3 { margin-top: 12px; }
.d-block { display: block; }
.text-muted { opacity: .75; font-size: .85rem; display: block; margin-top: 4px; }
.text-warning { color: #f1c40f; }
</style>
