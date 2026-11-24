<script setup lang="ts">
import axios from 'axios'
import { computed, reactive, ref, watch } from 'vue'
import { fileEndpointsApi, type FileEndpoint } from '../../services/fileEndpoints'
import { nasSyncApi, type EndpointCapabilities } from '../../services/nasSync'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

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
  verify_ssl: false,
  use_https: false,
  ssh_port: 22,
  rsync_module: '',
  rsync_user: '',
  rsync_password: '',
  rsync_port: 873,
})

const saving = ref(false)
const testing = ref(false)
const testMsg = ref('')
const testOk = ref<boolean | null>(null)
const errorMsg = ref('')
const caps = ref<EndpointCapabilities | null>(null)

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
  form.verify_ssl = false
  form.use_https = false
  form.ssh_port = 22
  form.rsync_module = ''
  form.rsync_user = ''
  form.rsync_password = ''
  form.rsync_port = 873
  testMsg.value = ''
  testOk.value = null
  errorMsg.value = ''
  caps.value = null
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
  const extra = (ep.extra_config || {}) as {
    verify_ssl?: boolean
    use_https?: boolean
    ssh_port?: number
    rsync_module?: string
    rsync_user?: string
    rsync_port?: number
  }
  form.verify_ssl = Boolean(extra.verify_ssl)
  form.use_https = Boolean(extra.use_https)
  form.ssh_port = extra.ssh_port ?? 22
  form.rsync_module = extra.rsync_module ?? ''
  form.rsync_user = extra.rsync_user ?? ''
  form.rsync_port = extra.rsync_port ?? 873
  form.rsync_password = ''
  testMsg.value = ep.last_test_message || ''
  testOk.value = ep.last_test_status === 'success' ? true : ep.last_test_status === 'failed' ? false : null
  errorMsg.value = ''
}

async function loadCaps(id: number) {
  const { data } = await nasSyncApi.capabilities(id)
  caps.value = data
}

watch(
  () => props.endpoint,
  (ep) => {
    if (ep) {
      loadFromEndpoint(ep)
      if (ep.id) loadCaps(ep.id)
    } else {
      resetForm()
    }
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
  const d = defaults[form.endpoint_type]!
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
    if (form.endpoint_type === 'synology' || form.endpoint_type === 'qnap') {
      const existingExtra =
        isEdit.value && props.endpoint ? { ...(props.endpoint.extra_config || {}) } : {}
      payload.extra_config = {
        ...existingExtra,
        verify_ssl: form.verify_ssl,
        ...(form.endpoint_type === 'qnap' ? { use_https: form.use_https } : {}),
      }
    }
    if (form.password) payload.password = form.password

    let data: FileEndpoint
    if (isEdit.value && props.endpoint) {
      ;({ data } = await fileEndpointsApi.update(props.endpoint.id, payload))
    } else {
      payload.endpoint_type = form.endpoint_type
      if (!form.password) {
        errorMsg.value = t('endpoint.servePassword')
        return
      }
      payload.password = form.password
      ;({ data } = await fileEndpointsApi.create(payload))
    }
    if (form.endpoint_type !== 'windows') {
      await nasSyncApi.setRsyncConfig(data.id, {
        ssh_port: form.ssh_port || null,
        rsync_module: form.rsync_module || null,
        rsync_user: form.rsync_user || null,
        rsync_password: form.rsync_password || null,
        rsync_port: form.rsync_port || null,
      })
    }
    await loadCaps(data.id)
    emit('saved', data)
    if (!isEdit.value) resetForm()
  } catch (e: unknown) {
    if (axios.isAxiosError(e)) {
      const detail = e.response?.data?.detail
      errorMsg.value = typeof detail === 'string' ? detail : e.message
    } else {
      errorMsg.value = e instanceof Error ? e.message : t('comune.erroreSalvataggio')
    }
  } finally {
    saving.value = false
  }
}

async function testConnection() {
  const id = props.endpoint?.id
  if (!id) {
    errorMsg.value = t('endpoint.primaSalva')
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
      testMsg.value = e instanceof Error ? e.message : t('endpoint.provaFallita')
    }
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <div class="card mb-4">
    <div class="card-header ep-header">
      <h3>{{ isEdit ? t('endpoint.modifica') : t('endpoint.nuovo') }}</h3>
      <button type="button" class="btn btn-sm btn-secondary" @click="emit('cancel')">{{ t('comune.chiudi') }}</button>
    </div>
    <div class="card-body grid-2">
      <div class="form-group">
        <label>{{ t('comune.nome') }}</label>
        <input v-model="form.name" class="form-input" required />
      </div>
      <div class="form-group">
        <label>{{ t('comune.tipo') }}</label>
        <select
          v-model="form.endpoint_type"
          class="form-input"
          :disabled="isEdit"
          @change="onTypeChange"
        >
          <option value="synology">Synology DSM</option>
          <option value="qnap">QNAP QuTS hero</option>
          <option value="linux">{{ t('endpoint.linux') }}</option>
          <option value="windows">Windows (SMB)</option>
        </select>
      </div>
      <div class="form-group">
        <label>{{ t('comune.ruolo') }}</label>
        <select v-model="form.role" class="form-input">
          <option value="source">{{ t('endpoint.rOrigine') }}</option>
          <option value="destination">{{ t('nasEndpoint.rDest') }}</option>
          <option value="both">{{ t('endpoint.rEntrambi') }}</option>
        </select>
      </div>
      <div class="form-group">
        <label>{{ t('comune.host') }}</label>
        <input v-model="form.host" class="form-input" placeholder="192.168.1.10" required />
        <small class="text-muted">{{ t('endpoint.hostNota') }}</small>
      </div>
      <div class="form-group">
        <label>{{ t('comune.porta') }}</label>
        <input v-model.number="form.port" type="number" class="form-input" />
        <small v-if="form.endpoint_type === 'qnap'" class="text-muted">
          {{ t('endpoint.portaQnap') }}
        </small>
        <small v-else-if="form.endpoint_type === 'synology'" class="text-muted">
          {{ t('endpoint.portaDsm') }}
        </small>
      </div>
      <div class="form-group">
        <label>{{ t('endpoint.utente') }}</label>
        <input v-model="form.username" class="form-input" required />
      </div>
      <div class="form-group">
        <label>{{ t('comune.password') }}</label>
        <input
          v-model="form.password"
          type="password"
          class="form-input"
          :placeholder="isEdit ? t('endpoint.nonCambiare') : ''"
        />
      </div>
      <fieldset v-if="form.endpoint_type !== 'windows'" class="span-2 caps-box">
        <legend>{{ t('nasEndpoint.ssh') }}</legend>
        <div class="form-group">
          <label>{{ t('nasEndpoint.portaSsh') }}</label>
          <input v-model.number="form.ssh_port" type="number" class="form-input" placeholder="22" />
          <small class="text-muted">{{ t('nasEndpoint.sshNota') }}</small>
        </div>
      </fieldset>
      <fieldset v-if="form.role !== 'source'" class="span-2 caps-box">
        <legend>{{ t('nasEndpoint.rsync') }}</legend>
        <div class="grid-2">
          <div class="form-group">
            <label>{{ t('nasEndpoint.modulo') }}</label>
            <input v-model="form.rsync_module" class="form-input" placeholder="DATI" />
            <small class="text-muted">
              {{ t('nasEndpoint.moduloNota') }}
            </small>
          </div>
          <div class="form-group">
            <label>{{ t('comune.porta') }}</label>
            <input v-model.number="form.rsync_port" type="number" class="form-input" placeholder="873" />
          </div>
          <div class="form-group">
            <label>{{ t('nasEndpoint.utenteRsync') }}</label>
            <input v-model="form.rsync_user" class="form-input" />
          </div>
          <div class="form-group">
            <label>{{ t('nasEndpoint.passwordRsync') }}</label>
            <input v-model="form.rsync_password" type="password" class="form-input"
                   :placeholder="isEdit ? t('endpoint.nonCambiare') : ''" />
          </div>
        </div>
      </fieldset>
      <div v-if="form.endpoint_type === 'qnap'" class="form-group span-2">
        <label class="checkbox-label">
          <input v-model="form.use_https" type="checkbox" />
          {{ t('endpoint.https') }}
        </label>
      </div>
      <div v-if="form.endpoint_type === 'synology' || form.endpoint_type === 'qnap'" class="form-group span-2">
        <label class="checkbox-label">
          <input v-model="form.verify_ssl" type="checkbox" />
          {{ t('endpoint.verifica') }}
        </label>
      </div>
      <div v-if="form.endpoint_type === 'linux'" class="form-group">
        <label>{{ t('endpoint.chiave') }}</label>
        <input v-model="form.ssh_key_path" class="form-input" placeholder="/root/.ssh/id_rsa" />
      </div>
      <div v-if="form.endpoint_type === 'windows'" class="form-group">
        <label>{{ t('endpoint.dominio') }}</label>
        <input v-model="form.domain" class="form-input" />
      </div>
      <div class="form-group span-2 ep-actions">
        <button class="btn btn-primary" :disabled="saving" @click="save">
          {{ saving ? t('comune.salvataggio') : isEdit ? t('comune.salvaModifiche') : t('endpoint.salva') }}
        </button>
        <button
          v-if="isEdit"
          class="btn btn-secondary"
          type="button"
          :disabled="testing"
          @click="testConnection"
        >
          {{ testing ? t('endpoint.provaInCorso') : t('endpoint.prova') }}
        </button>
      </div>
      <p v-if="caps" class="span-2 caps-badges">
        <span class="badge" :class="caps.rsync_source ? 'badge-ok' : 'badge-off'"
              :title="caps.reasons.rsync_source || ''">{{ t('nasEndpoint.rsyncOrigine') }} {{ caps.rsync_source ? '✓' : '✗' }}</span>
        <span class="badge" :class="caps.rsync_dest ? 'badge-ok' : 'badge-off'"
              :title="caps.reasons.rsync_dest || ''">{{ t('nasEndpoint.rsyncDest') }} {{ caps.rsync_dest ? '✓' : '✗' }}</span>
        <span class="badge" :class="caps.smb ? 'badge-ok' : 'badge-off'">SMB {{ caps.smb ? '✓' : '✗' }}</span>
      </p>
      <p v-if="errorMsg" class="span-2 text-danger">{{ errorMsg }}</p>
      <p v-if="testMsg" class="span-2" :class="testOk ? 'text-success' : 'text-danger'">{{ testMsg }}</p>
    </div>
  </div>
</template>

<style scoped>
.span-2 { grid-column: 1 / -1; }
.ep-header { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.ep-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.caps-box { border: 1px solid var(--border-color, #333); border-radius: 8px; padding: 10px 14px; }
.caps-badges { display: flex; gap: 8px; }
.badge-ok { background: rgba(46, 204, 113, .18); color: #2ecc71; }
.badge-off { background: rgba(255,255,255,.06); opacity: .6; }
</style>
