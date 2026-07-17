<script setup lang="ts">
import { reactive, ref } from 'vue'
import { fileEndpointsApi, type FileEndpoint } from '../../services/fileEndpoints'

const emit = defineEmits<{ saved: [endpoint: FileEndpoint] }>()

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

function onTypeChange() {
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
  try {
    const { data } = await fileEndpointsApi.create({ ...form })
    emit('saved', data)
    testMsg.value = ''
    testOk.value = null
  } finally {
    saving.value = false
  }
}

async function testSaved(id: number) {
  testing.value = true
  testMsg.value = ''
  try {
    const { data } = await fileEndpointsApi.test(id)
    testOk.value = data.success
    testMsg.value = data.message
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <div class="card mb-4">
    <div class="card-header"><h3>Nuovo endpoint</h3></div>
    <div class="card-body grid-2">
      <div class="form-group">
        <label>Nome</label>
        <input v-model="form.name" class="form-input" />
      </div>
      <div class="form-group">
        <label>Tipo</label>
        <select v-model="form.endpoint_type" class="form-input" @change="onTypeChange">
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
        <input v-model="form.host" class="form-input" placeholder="192.168.1.10" />
      </div>
      <div class="form-group">
        <label>Porta</label>
        <input v-model.number="form.port" type="number" class="form-input" />
      </div>
      <div class="form-group">
        <label>Utente</label>
        <input v-model="form.username" class="form-input" />
      </div>
      <div class="form-group">
        <label>Password</label>
        <input v-model="form.password" type="password" class="form-input" />
      </div>
      <div v-if="form.endpoint_type === 'linux' || form.endpoint_type === 'windows'" class="form-group">
        <label>Chiave SSH (Linux/OpenSSH)</label>
        <input v-model="form.ssh_key_path" class="form-input" placeholder="/root/.ssh/id_rsa" />
      </div>
      <div v-if="form.endpoint_type === 'windows'" class="form-group">
        <label>Dominio SMB</label>
        <input v-model="form.domain" class="form-input" />
      </div>
      <div class="form-group span-2">
        <button class="btn btn-primary" :disabled="saving" @click="save">
          {{ saving ? 'Salvataggio…' : 'Salva endpoint' }}
        </button>
      </div>
      <p v-if="testMsg" :class="testOk ? 'text-success' : 'text-danger'">{{ testMsg }}</p>
    </div>
  </div>
</template>

<style scoped>
.span-2 { grid-column: 1 / -1; }
</style>
