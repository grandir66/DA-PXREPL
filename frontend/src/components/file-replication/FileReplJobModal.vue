<script setup lang="ts">
import axios from 'axios'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import FolderBrowser from './FolderBrowser.vue'
import QnapImmutabilityHint from './QnapImmutabilityHint.vue'
import { fileEndpointsApi, type FileEndpoint } from '../../services/fileEndpoints'
import { fileReplicationApi, type FileReplicationJob } from '../../services/fileReplication'

const props = defineProps<{
  job?: FileReplicationJob | null
}>()

const emit = defineEmits<{ saved: []; close: [] }>()

const isEdit = computed(() => !!props.job?.id)

const step = ref(1)
const endpoints = ref<FileEndpoint[]>([])
const saving = ref(false)
const errorMsg = ref('')

const form = reactive({
  name: '',
  source_endpoint_id: null as number | null,
  dest_endpoint_id: null as number | null,
  source_paths: [] as string[],
  dest_staging_path: '/share/staging/archivio',
  delete_on_dest: true,
  exclude_presets: ['nas_snapshots', 'system_files'] as string[],
  exclude_patterns: '',
  schedule: '0 2 * * *',
  snapshot_schedule: '0 3 * * *',
  expiration_days: 30,
  max_snapshots: 10,
  notify_mode: 'daily',
})

const sourceEndpoints = computed(() =>
  endpoints.value.filter((e) => e.role === 'source' || e.role === 'both'),
)
const destEndpoints = computed(() =>
  endpoints.value.filter(
    (e) => (e.role === 'destination' || e.role === 'both') && e.endpoint_type === 'qnap',
  ),
)

function resetForm() {
  form.name = ''
  form.source_endpoint_id = null
  form.dest_endpoint_id = null
  form.source_paths = []
  form.dest_staging_path = '/share/staging/archivio'
  form.delete_on_dest = true
  form.exclude_presets = ['nas_snapshots', 'system_files']
  form.exclude_patterns = ''
  form.schedule = '0 2 * * *'
  form.snapshot_schedule = '0 3 * * *'
  form.expiration_days = 30
  form.max_snapshots = 10
  form.notify_mode = 'daily'
  step.value = 1
  errorMsg.value = ''
}

function loadFromJob(job: FileReplicationJob) {
  const hint = (job.snapshot_policy_hint || {}) as Record<string, unknown>
  form.name = job.name
  form.source_endpoint_id = job.source_endpoint_id
  form.dest_endpoint_id = job.dest_endpoint_id
  form.source_paths = [...(job.source_paths || [])]
  form.dest_staging_path = job.dest_staging_path
  form.delete_on_dest = job.delete_on_dest
  form.exclude_presets = [...(job.exclude_presets || ['nas_snapshots', 'system_files'])]
  form.exclude_patterns = (job.exclude_patterns || []).join('\n')
  form.schedule = job.schedule || ''
  form.snapshot_schedule = String(hint.schedule || '0 3 * * *')
  form.expiration_days = Number(hint.expiration_days || 30)
  form.max_snapshots = Number(hint.max_snapshots || 10)
  form.notify_mode = job.notify_mode || 'daily'
  step.value = 1
  errorMsg.value = ''
}

function buildPayload(): Record<string, unknown> {
  return {
    name: form.name,
    source_paths: form.source_paths,
    dest_staging_path: form.dest_staging_path,
    delete_on_dest: form.delete_on_dest,
    exclude_presets: form.exclude_presets,
    exclude_patterns: form.exclude_patterns
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean),
    schedule: form.schedule || null,
    notify_mode: form.notify_mode,
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
}

async function submit() {
  if (!form.source_endpoint_id || !form.dest_endpoint_id || !form.source_paths.length) return
  saving.value = true
  errorMsg.value = ''
  try {
    const payload = buildPayload()
    if (isEdit.value && props.job) {
      await fileReplicationApi.update(props.job.id, payload)
    } else {
      await fileReplicationApi.create({
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
        <h2>{{ isEdit ? 'Modifica job replica file' : 'Nuovo job replica file' }}</h2>
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
          Synology → QNAP: sync <strong>diretto</strong> (stream, non riempie il disco dapx).
          Path es. <code>/Comune/AArchivio</code> — share <code>Comune</code>, cartella <code>AArchivio</code>.
          Staging QNAP: <code>/share/DATI/archivio</code> (DATI solo in destinazione).
        </p>
      </div>

      <div v-show="step === 3" class="modal-body">
        <div class="form-group">
          <label>Endpoint QNAP destinazione</label>
          <select v-model="form.dest_endpoint_id" class="form-input" :disabled="isEdit">
            <option :value="null" disabled>— seleziona —</option>
            <option v-for="ep in destEndpoints" :key="ep.id" :value="ep.id">
              {{ ep.name }}
            </option>
          </select>
          <small v-if="isEdit" class="text-muted">L'endpoint destinazione non è modificabile in modifica job.</small>
        </div>
        <div class="form-group">
          <label>Path staging su QNAP</label>
          <input v-model="form.dest_staging_path" class="form-input" placeholder="/share/DATI/archivio" />
          <small class="text-muted">
            Per rsync via SSH usa il prefisso <code>/share/</code>, es. <code>/share/DATI/archivio</code>
            (non solo <code>/DATI/...</code>).
          </small>
        </div>
      </div>

      <div v-show="step === 4" class="modal-body">
        <label class="checkbox-label">
          <input v-model="form.delete_on_dest" type="checkbox" />
          Elimina file rimossi dalla sorgente (solo staging mutabile)
        </label>
        <div class="form-group mt-3">
          <label>Cron sync dapx</label>
          <input v-model="form.schedule" class="form-input" placeholder="0 2 * * *" />
        </div>
        <div class="form-group">
          <label>Pattern exclude aggiuntivi (uno per riga)</label>
          <textarea v-model="form.exclude_patterns" class="form-input" rows="3" />
        </div>
        <QnapImmutabilityHint
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
.text-muted { opacity: 0.75; font-size: 0.85rem; display: block; margin-top: 4px; }
</style>
