<script setup lang="ts">
import axios from 'axios'
import { computed, reactive, ref, watch } from 'vue'
import { fileEndpointsApi, type FileEndpoint } from '../../services/fileEndpoints'

const props = defineProps<{
  endpoint?: FileEndpoint | null
}>()

const emit = defineEmits<{ saved: [endpoint: FileEndpoint]; cancel: [] }>()

const isEdit = computed(() => !!props.endpoint?.id)

const form = reactive({
  name: '',
  endpoint_type: 'synology' as FileEndpoint['endpoint_type'],
  role: 'source',
  host: '',
  port: 5001,
  protocol: 'api',
  username: '',
  password: '',
  ssh_key_path: '',
  domain: '',
  base_path: '',
})

const saving = ref(false)
const testing = ref(false)
const testMsg = ref('')
const testOk = ref<boolean | null>(null)
const errorMsg = ref('')

function resetForm() {
  form.name = ''
  form.endpoint_type = 'synology'
  form.role = 'source'
  form.host = ''
  form.port = 5001
  form.protocol = 'api'
  form.username = ''
  form.password = ''
  form.ssh_key_path = ''
  form.domain = ''
  form.base_path = ''
  testMsg.value = ''
  testOk.value = null
  errorMsg.value = ''
}

function loadFromEndpoint(ep: FileEndpoint) {
  form.name = ep.name
  form.endpoint_type = ep.endpoint_type
  form.role = ep.role
  form.host = ep.host
  form.port = ep.port
  form.protocol = ep.protocol
  form.username = ep.username
  form.password = ''
  form.ssh_key_path = ep.ssh_key_path || ''
  form.domain = ep.domain || ''
  form.base_path = ep.base_path || ''
  testMsg.value = ep.last_test_message || ''
  testOk.value = ep.last_test_status === 'success' ? true : ep.last_test_status === 'failed' ? false : null
  errorMsg.value = ''
}

watch(
  () => props.endpoint,
  (ep) => {
    if (ep) loadFromEndpoint(ep)
    else resetForm()
  },
  { immediate: true },
)

function onTypeChange() {
  if (isEdit.value) return
  const defaults: Record<string, { port: number; protocol: string }> = {
    synology: { port: 5001, protocol: 'api' },
    qnap: { port: 8080, protocol: 'api' },
    linux: { port: 22, protocol: 'ssh' },
    windows: { port: 445, protocol: 'smb' },
  }
  const d = defaults[form.endpoint_type]
  form.port = d.port
  form.protocol = d.protocol
}

async function save() {
  saving.value = true
  errorMsg.value = ''
  try {
    const payload: Record<string, unknown> = {
      name: form.name,
      role: form.role,
      host: form.host,
      port: form.port,
      protocol: form.protocol,
      username: form.username,
      ssh_key_path: form.ssh_key_path || null,
      domain: form.domain || null,
      base_path: form.base_path || null,
    }
    if (form.password) payload.password = form.password

    let data: FileEndpoint
    if (isEdit.value && props.endpoint) {
      ;({ data } = await fileEndpointsApi.update(props.endpoint.id, payload))
    } else {
      payload.endpoint_type = form.endpoint_type
      if (!form.password) {
        errorMsg.value = 'Password obbligatoria per un nuovo endpoint'
        return
      }
      payload.password = form.password
      ;({ data } = await fileEndpointsApi.create(payload))
    }
    emit('saved', data)
    if (!isEdit.value) resetForm()
  } catch (e: unknown) {
    if (axios.isAxiosError(e)) {
      const detail = e.response?.data?.detail
      errorMsg.value = typeof detail === 'string' ? detail : e.message
    } else {
      errorMsg.value = e instanceof Error ? e.message : 'Errore salvataggio'
    }
  } finally {
    saving.value = false
  }
}

async function testConnection() {
  const id = props.endpoint?.id
  if (!id) {
    errorMsg.value = 'Salva l\'endpoint prima di testare la connessione'
    return
  }
  testing.value = true
  testMsg.value = ''
  errorMsg.value = ''
  try {
    const { data } = await fileEndpointsApi.test(id)
    testOk.value = data.success
    testMsg.value = data.message
  } catch (e: unknown) {
    testOk.value = false
    if (axios.isAxiosError(e)) {
      const detail = e.response?.data?.detail
      testMsg.value = typeof detail === 'string' ? detail : e.message
    } else {
      testMsg.value = e instanceof Error ? e.message : 'Test fallito'
    }
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <div class="card mb-4">
    <div class="card-header ep-header">
      <h3>{{ isEdit ? 'Modifica endpoint' : 'Nuovo endpoint' }}</h3>
      <button type="button" class="btn btn-sm btn-secondary" @click="emit('cancel')">Chiudi</button>
    </div>
    <div class="card-body grid-2">
      <div class="form-group">
        <label>Nome</label>
        <input v-model="form.name" class="form-input" required />
      </div>
      <div class="form-group">
        <label>Tipo</label>
        <select
          v-model="form.endpoint_type"
          class="form-input"
          :disabled="isEdit"
          @change="onTypeChange"
        >
          <option value="synology">Synology DSM</option>
          <option value="qnap">QNAP QuTS hero</option>
          <option value="linux">Linux / VM Linux</option>
          <option value="windows">Windows (SMB)</option>
        </select>
      </div>
      <div class="form-group">
        <label>Ruolo</label>
        <select v-model="form.role" class="form-input">
          <option value="source">Sorgente</option>
          <option value="destination">Destinazione QNAP</option>
          <option value="both">Entrambi</option>
        </select>
      </div>
      <div class="form-group">
        <label>Host</label>
        <input v-model="form.host" class="form-input" placeholder="192.168.1.10" required />
        <small class="text-muted">Deve essere raggiungibile dal server dapx, non solo dal tuo PC.</small>
      </div>
      <div class="form-group">
        <label>Porta</label>
        <input v-model.number="form.port" type="number" class="form-input" />
      </div>
      <div class="form-group">
        <label>Utente</label>
        <input v-model="form.username" class="form-input" required />
      </div>
      <div class="form-group">
        <label>Password</label>
        <input
          v-model="form.password"
          type="password"
          class="form-input"
          :placeholder="isEdit ? 'Lascia vuoto per non cambiare' : ''"
        />
      </div>
      <div v-if="form.endpoint_type === 'linux'" class="form-group">
        <label>Chiave SSH (Linux/OpenSSH)</label>
        <input v-model="form.ssh_key_path" class="form-input" placeholder="/root/.ssh/id_rsa" />
      </div>
      <div v-if="form.endpoint_type === 'windows'" class="form-group">
        <label>Dominio SMB</label>
        <input v-model="form.domain" class="form-input" />
      </div>
      <div class="form-group span-2 ep-actions">
        <button class="btn btn-primary" :disabled="saving" @click="save">
          {{ saving ? 'Salvataggio…' : isEdit ? 'Salva modifiche' : 'Salva endpoint' }}
        </button>
        <button
          v-if="isEdit"
          class="btn btn-secondary"
          type="button"
          :disabled="testing"
          @click="testConnection"
        >
          {{ testing ? 'Test…' : 'Test connessione' }}
        </button>
      </div>
      <p v-if="errorMsg" class="span-2 text-danger">{{ errorMsg }}</p>
      <p v-if="testMsg" class="span-2" :class="testOk ? 'text-success' : 'text-danger'">{{ testMsg }}</p>
    </div>
  </div>
</template>

<style scoped>
.span-2 { grid-column: 1 / -1; }
.ep-header { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.ep-actions { display: flex; gap: 8px; flex-wrap: wrap; }
</style>
