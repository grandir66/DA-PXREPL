<script setup lang="ts">
import axios from 'axios'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import FolderBrowser from '../file-replication/FolderBrowser.vue'
import FileReplPathMapping from '../file-replication/FileReplPathMapping.vue'
import QnapImmutabilityHint from '../file-replication/QnapImmutabilityHint.vue'
import { fileEndpointsApi, type FileEndpoint } from '../../services/fileEndpoints'
import {
  nasSyncApi,
  type EndpointCapabilities,
  type NasSyncJob,
  type PreflightCheck,
} from '../../services/nasSync'
import { normalizeQnapDestShare, normalizeQnapStagingPath } from '../../utils/qnapPath'
import { compactSourcePaths } from '../../utils/pathSelection'

const props = defineProps<{
  job?: NasSyncJob | null
}>()

const emit = defineEmits<{ saved: []; close: [] }>()

const isEdit = computed(() => !!props.job?.id)

const step = ref(1)
const endpoints = ref<FileEndpoint[]>([])
const endpointCaps = ref<Record<number, EndpointCapabilities>>({})
const saving = ref(false)
const errorMsg = ref('')

const preflightChecks = ref<PreflightCheck[]>([])
const preflightRunning = ref(false)

const form = reactive({
  name: '',
  source_endpoint_id: null as number | null,
  dest_endpoint_id: null as number | null,
  source_paths: [] as string[],
  dest_base_path: '/share/DATI',
  sync_method: 'auto' as 'auto' | 'direct_rsync' | 'rclone_smb',
  delete_on_dest: false,
  rclone_size_only: false,
  exclude_presets: ['nas_snapshots', 'system_files'] as string[],
  exclude_patterns: '',
  bandwidth_limit_kb: null as number | null,
  schedule: '0 2 * * *',
  snapshot_schedule: '0 3 * * *',
  expiration_days: 30,
  max_snapshots: 10,
  notify_mode: 'daily' as 'daily' | 'always' | 'failure' | 'never',
  notify_subject: '',
})

const sourceEndpoints = computed(() =>
  endpoints.value.filter((e) => e.role === 'source' || e.role === 'both'),
)
const destEndpoints = computed(() =>
  endpoints.value.filter((e) => {
    if (e.role !== 'destination' && e.role !== 'both') return false
    const caps = endpointCaps.value[e.id]
    return !!caps && (caps.rsync_dest || caps.smb)
  }),
)

const destShare = computed(() => normalizeQnapDestShare(form.dest_base_path))

const sourceEndpointName = computed(
  () => sourceEndpoints.value.find((e) => e.id === form.source_endpoint_id)?.name || null,
)
const destEndpointName = computed(
  () => destEndpoints.value.find((e) => e.id === form.dest_endpoint_id)?.name || null,
)
const destEndpointType = computed(
  () => endpoints.value.find((e) => e.id === form.dest_endpoint_id)?.endpoint_type || null,
)

const destBasePaths = computed({
  get: () => (form.dest_base_path ? [form.dest_base_path] : []),
  set: (paths: string[]) => {
    form.dest_base_path = paths[0] ? normalizeQnapStagingPath(paths[0]) : '/share/DATI'
  },
})

const engineHint = computed(() => {
  const src = endpointCaps.value[form.source_endpoint_id ?? -1]
  const dst = endpointCaps.value[form.dest_endpoint_id ?? -1]
  if (!src || !dst) return ''
  if (form.sync_method === 'auto') {
    if (src.rsync_source && dst.rsync_dest)
      return 'Verrà usato il motore diretto rsync: i dati non passano dal server dapx.'
    return (
      'Verrà usato rclone SMB (fallback): ' +
      (src.reasons.rsync_source || dst.reasons.rsync_dest || '')
    )
  }
  return ''
})

function resetForm() {
  form.name = ''
  form.source_endpoint_id = null
  form.dest_endpoint_id = null
  form.source_paths = []
  form.dest_base_path = '/share/DATI'
  form.sync_method = 'auto'
  form.delete_on_dest = false
  form.rclone_size_only = false
  form.exclude_presets = ['nas_snapshots', 'system_files']
  form.exclude_patterns = ''
  form.bandwidth_limit_kb = null
  form.schedule = '0 2 * * *'
  form.snapshot_schedule = '0 3 * * *'
  form.expiration_days = 30
  form.max_snapshots = 10
  form.notify_mode = 'daily'
  form.notify_subject = ''
  step.value = 1
  errorMsg.value = ''
  preflightChecks.value = []
}

function loadFromJob(job: NasSyncJob) {
  const hint = (job.snapshot_policy_hint || {}) as Record<string, unknown>
  form.name = job.name
  form.source_endpoint_id = job.source_endpoint_id
  form.dest_endpoint_id = job.dest_endpoint_id
  form.source_paths = compactSourcePaths([...(job.source_paths || [])])
  form.dest_base_path = normalizeQnapStagingPath(job.dest_base_path)
  form.sync_method = job.sync_method || 'auto'
  form.delete_on_dest = job.delete_on_dest
  form.rclone_size_only = Boolean(job.rclone_size_only)
  form.exclude_presets = [...(job.exclude_presets || ['nas_snapshots', 'system_files'])]
  form.exclude_patterns = (job.exclude_patterns || []).join('\n')
  form.bandwidth_limit_kb = job.bandwidth_limit_kb ?? null
  form.schedule = job.schedule || ''
  form.snapshot_schedule = String(hint.schedule || '0 3 * * *')
  form.expiration_days = Number(hint.expiration_days || 30)
  form.max_snapshots = Number(hint.max_snapshots || 10)
  form.notify_mode = (job.notify_mode as typeof form.notify_mode) || 'daily'
  form.notify_subject = job.notify_subject || ''
  step.value = 1
  errorMsg.value = ''
  preflightChecks.value = []
}

function buildPayload(): Record<string, unknown> {
  return {
    name: form.name,
    source_paths: compactSourcePaths(form.source_paths),
    dest_base_path: form.dest_base_path,
    sync_method: form.sync_method,
    delete_on_dest: form.delete_on_dest,
    rclone_size_only: form.rclone_size_only,
    exclude_presets: form.exclude_presets,
    exclude_patterns: form.exclude_patterns
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean),
    bandwidth_limit_kb: form.bandwidth_limit_kb,
    schedule: form.schedule || null,
    notify_mode: form.notify_mode,
    notify_subject: form.notify_subject.trim() || null,
    snapshot_policy_hint: {
      schedule: form.snapshot_schedule,
      expiration_days: form.expiration_days,
      max_snapshots: form.max_snapshots,
      only_if_modified: true,
      protection: 'prohibit_recycle_and_delete_until_expired',
      retention_mode: 'smart_versioning',
    },
  }
}

async function loadEndpoints() {
  const { data } = await fileEndpointsApi.list()
  endpoints.value = data
  await Promise.all(
    data.map(async (ep) => {
      try {
        const { data: caps } = await nasSyncApi.capabilities(ep.id)
        endpointCaps.value[ep.id] = caps
      } catch {
        /* endpoint senza capacità: escluso dai filtri */
      }
    }),
  )
}

async function runPreflight() {
  if (!props.job?.id) return
  preflightRunning.value = true
  try {
    const { data } = await nasSyncApi.preflight(props.job.id)
    preflightChecks.value = data
  } finally {
    preflightRunning.value = false
  }
}

async function submit() {
  if (!form.source_endpoint_id || !form.dest_endpoint_id || !form.source_paths.length) return
  saving.value = true
  errorMsg.value = ''
  try {
    const payload = buildPayload()
    if (isEdit.value && props.job) {
      await nasSyncApi.update(props.job.id, payload)
    } else {
      await nasSyncApi.create({
        ...payload,
        source_endpoint_id: form.source_endpoint_id,
        dest_endpoint_id: form.dest_endpoint_id,
      })
    }
    emit('saved')
    if (!isEdit.value) resetForm()
  } catch (e: unknown) {
    if (axios.isAxiosError(e)) {
      const detail = e.response?.data?.detail
      errorMsg.value = typeof detail === 'string' ? detail : e.message
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
  },
  { immediate: true },
)

onMounted(loadEndpoints)
</script>

<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal-card">
      <header class="modal-head">
        <h2>{{ isEdit ? 'Modifica job Repliche dati' : 'Nuovo job Repliche dati' }}</h2>
        <button type="button" class="btn btn-sm" @click="$emit('close')">✕</button>
      </header>

      <nav class="steps">
        <span :class="{ active: step === 1 }">1. Sorgente</span>
        <span :class="{ active: step === 2 }">2. Cartelle</span>
        <span :class="{ active: step === 3 }">3. Destinazione</span>
        <span :class="{ active: step === 4 }">4. Regole</span>
      </nav>

      <div v-show="step === 1" class="modal-body">
        <div class="form-group">
          <label>Nome job</label>
          <input v-model="form.name" class="form-input" />
        </div>
        <div class="form-group">
          <label>Endpoint sorgente</label>
          <select v-model="form.source_endpoint_id" class="form-input" :disabled="isEdit">
            <option :value="null" disabled>— seleziona —</option>
            <option v-for="ep in sourceEndpoints" :key="ep.id" :value="ep.id">
              {{ ep.name }} ({{ ep.endpoint_type }})
            </option>
          </select>
          <small v-if="isEdit" class="text-muted">L'endpoint sorgente non è modificabile in modifica job.</small>
        </div>
      </div>

      <div v-show="step === 2" class="modal-body">
        <FolderBrowser
          v-model="form.source_paths"
          :endpoint-id="form.source_endpoint_id"
          :exclude-presets="form.exclude_presets"
        />
        <p class="text-muted mt-2">
          Seleziona le cartelle sorgente. La struttura sorgente viene replicata sotto il percorso
          base di destinazione. <strong>#snapshot</strong>, <strong>@Snapshot</strong>,
          <strong>#recycle</strong> e cartelle di sistema sono <strong>sempre escluse</strong> dal
          sync (nessuno storico dalla sorgente).
        </p>
        <p class="text-muted">
          Non schedulare le stesse cartelle sia qui che nel modulo «Replica file»: i due moduli
          non si coordinano tra loro.
        </p>
      </div>

      <div v-show="step === 3" class="modal-body">
        <div class="form-group">
          <label>Endpoint destinazione</label>
          <select v-model="form.dest_endpoint_id" class="form-input" :disabled="isEdit">
            <option :value="null" disabled>— seleziona —</option>
            <option v-for="ep in destEndpoints" :key="ep.id" :value="ep.id">
              {{ ep.name }}
            </option>
          </select>
          <small v-if="isEdit" class="text-muted">L'endpoint destinazione non è modificabile in modifica job.</small>
        </div>
        <div class="form-group">
          <label>Percorso base destinazione</label>
          <FolderBrowser
            v-model="destBasePaths"
            :endpoint-id="form.dest_endpoint_id"
            :exclude-presets="form.exclude_presets"
            mode="single"
            normalize-qnap-paths
            share-only
            hint="Seleziona solo la share di destinazione (es. DATI). Le sottocartelle ereditano il percorso sorgente."
          />
          <small class="text-muted">
            Scegli solo la share di destinazione. Le sottocartelle ereditano il percorso sorgente.
          </small>
        </div>
        <FileReplPathMapping
          v-if="form.source_paths.length"
          class="mt-2"
          show-header
          :source-paths="form.source_paths"
          :dest-share-path="destShare"
          :source-label="sourceEndpointName"
          :dest-label="destEndpointName"
        />
      </div>

      <div v-show="step === 4" class="modal-body">
        <div class="engine-panel">
          <h4>Motore di replica</h4>
          <select v-model="form.sync_method" class="form-input">
            <option value="auto">Automatico (consigliato)</option>
            <option value="direct_rsync">Diretto rsync (NAS→NAS)</option>
            <option value="rclone_smb">rclone SMB (via server dapx)</option>
          </select>
          <p v-if="engineHint" class="text-muted">{{ engineHint }}</p>
          <button
            v-if="isEdit"
            type="button"
            class="btn btn-sm btn-secondary mt-2"
            :disabled="preflightRunning"
            @click="runPreflight"
          >
            {{ preflightRunning ? 'Verifica…' : 'Verifica prerequisiti' }}
          </button>
          <ul v-if="preflightChecks.length" class="preflight-list">
            <li v-for="c in preflightChecks" :key="c.check"
                :class="c.ok ? 'text-success' : 'text-danger'">
              {{ c.ok ? '✓' : '✗' }} {{ c.message }}
              <small v-if="c.hint" class="d-block text-muted">{{ c.hint }}</small>
            </li>
          </ul>
        </div>

        <FileReplPathMapping
          v-if="form.source_paths.length"
          class="mb-2"
          compact
          show-header
          :source-paths="form.source_paths"
          :dest-share-path="destShare"
          :source-label="sourceEndpointName"
          :dest-label="destEndpointName"
        />
        <label class="checkbox-label">
          <input v-model="form.delete_on_dest" type="checkbox" />
          Elimina sulla destinazione i file non più presenti nella sorgente (mirror)
        </label>
        <p class="text-muted mt-2">
          Esclusioni automatiche (non disabilitabili): <code>#snapshot</code>, <code>@Snapshot</code>,
          <code>#recycle</code>, <code>@eaDir</code>, cestini e cartelle di sistema.
          Lo storico/versioning va configurato solo con gli <strong>snapshot</strong> del NAS di destinazione.
        </p>
        <template v-if="form.sync_method !== 'direct_rsync'">
          <label class="checkbox-label mt-2">
            <input v-model="form.rclone_size_only" type="checkbox" />
            Confronta solo la dimensione dei file (rclone --size-only, evita il calcolo hash)
          </label>
          <p class="text-muted mt-2">
            rclone usa <code>--no-traverse</code> e <code>--fast-list</code> per limitare le chiamate
            SMB su cartelle con molti file.
          </p>
        </template>
        <div class="form-group">
          <label>Limite banda (KB/s, vuoto = nessun limite)</label>
          <input v-model.number="form.bandwidth_limit_kb" type="number" class="form-input" />
        </div>
        <div class="form-group mt-3">
          <label>Cron sync dapx</label>
          <input v-model="form.schedule" class="form-input" placeholder="0 2 * * *" />
        </div>
        <div class="form-group">
          <label>Notifiche email</label>
          <select v-model="form.notify_mode" class="form-input">
            <option value="daily">Riepilogo giornaliero (max 1 OK/giorno) + errori</option>
            <option value="always">Ogni esecuzione</option>
            <option value="failure">Solo fallimenti</option>
            <option value="never">Mai</option>
          </select>
          <small class="text-muted">
            Richiede SMTP configurato in Impostazioni → Notifiche e «Notifica successi» attivo per le email OK.
          </small>
        </div>
        <div class="form-group">
          <label>Oggetto email (opzionale)</label>
          <input v-model="form.notify_subject" type="text" class="form-input" placeholder="Replica Comune → NAS" />
        </div>
        <div class="form-group">
          <label>Pattern exclude aggiuntivi (uno per riga)</label>
          <textarea v-model="form.exclude_patterns" class="form-input" rows="3" />
        </div>
        <QnapImmutabilityHint
          v-if="destEndpointType === 'qnap'"
          :snapshot-schedule="form.snapshot_schedule"
          :expiration-days="form.expiration_days"
          :max-snapshots="form.max_snapshots"
        />
      </div>

      <p v-if="errorMsg" class="modal-error">{{ errorMsg }}</p>

      <footer class="modal-foot">
        <button v-if="step > 1" type="button" class="btn btn-secondary" @click="step--">Indietro</button>
        <button v-if="step < 4" type="button" class="btn btn-primary" @click="step++">Avanti</button>
        <button
          v-else
          type="button"
          class="btn btn-primary"
          :disabled="saving || !form.name || !form.source_paths.length"
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
  width: min(720px, 94vw); max-height: 90vh; overflow: auto;
}
.modal-head, .modal-foot { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; }
.modal-body { padding: 0 20px 16px; }
.modal-error { padding: 0 20px 12px; color: var(--danger, #e74c3c); font-size: 0.875rem; }
.steps { display: flex; gap: 12px; padding: 0 20px 12px; font-size: 0.85rem; opacity: 0.7; }
.steps .active { opacity: 1; font-weight: 600; }
.mt-3 { margin-top: 12px; }
.mb-3 { margin-bottom: 12px; }
.text-muted { opacity: 0.75; font-size: 0.85rem; display: block; margin-top: 4px; }
.engine-panel { border: 1px solid var(--border-color, #333); border-radius: 8px; padding: 12px 16px; margin-bottom: 12px; }
.preflight-list { list-style: none; padding: 8px 0 0; margin: 0; font-size: .85rem; }
</style>
