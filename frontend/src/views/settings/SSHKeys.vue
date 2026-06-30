<template>
  <div class="ssh-keys-page">
    <div class="card-header">
      <h3>Chiavi SSH</h3>
      <button class="btn btn-secondary btn-sm" @click="loadInfo" :disabled="loading">
        {{ loading ? 'Caricamento…' : 'Aggiorna' }}
      </button>
    </div>

    <div class="card-body" v-if="info">
      <div class="status-row">
        <span>Chiave locale:</span>
        <span :class="info.exists ? 'text-success' : 'text-danger'">
          {{ info.exists ? 'Presente' : 'Assente' }}
        </span>
      </div>
      <div v-if="info.exists" class="key-meta">
        <div><strong>Tipo:</strong> {{ info.key_type }}</div>
        <div><strong>Fingerprint:</strong> <code>{{ info.fingerprint }}</code></div>
        <div><strong>Commento:</strong> {{ info.comment }}</div>
        <div class="pub-key" v-if="info.public_key">
          <label>Chiave pubblica</label>
          <textarea readonly class="form-input" rows="3">{{ info.public_key }}</textarea>
        </div>
      </div>
      <p v-else class="help-text">Genera una chiave per abilitare connessioni SSH passwordless verso i nodi Proxmox.</p>

      <div class="actions-row">
        <button class="btn btn-primary btn-sm" @click="generateKey(false)" :disabled="working">
          {{ info.exists ? 'Rigenera chiave' : 'Genera chiave' }}
        </button>
        <button
          v-if="info.exists"
          class="btn btn-secondary btn-sm"
          @click="distribute"
          :disabled="working"
        >
          Distribuisci a tutti i nodi
        </button>
        <button
          v-if="info.exists"
          class="btn btn-secondary btn-sm"
          @click="testAll"
          :disabled="working"
        >
          Test connessioni
        </button>
      </div>

      <div v-if="testResults.length" class="test-results">
        <h4>Risultati test</h4>
        <table class="data-table">
          <thead>
            <tr>
              <th>Nodo</th>
              <th>Host</th>
              <th>Esito</th>
              <th>Messaggio</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in testResults" :key="i">
              <td>{{ r.node_name || r.node_id || '—' }}</td>
              <td>{{ r.host }}</td>
              <td>
                <span :class="r.success ? 'text-success' : 'text-danger'">
                  {{ r.success ? 'OK' : 'Fallito' }}
                </span>
              </td>
              <td>{{ r.message }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-else-if="loading" class="loading-state">Caricamento…</div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import sshKeysService, { type SSHKeyInfo, type SSHTestResult } from '../../services/sshKeys'
import { useToast, errorMessage } from '../../stores/toast'
import { confirmDangerous } from '../../stores/confirm'

const toast = useToast()
const info = ref<SSHKeyInfo | null>(null)
const testResults = ref<SSHTestResult[]>([])
const loading = ref(false)
const working = ref(false)

async function loadInfo() {
  loading.value = true
  try {
    const res = await sshKeysService.getInfo()
    info.value = res.data
  } catch (e) {
    toast.error('Errore caricamento chiavi SSH', errorMessage(e))
  } finally {
    loading.value = false
  }
}

async function generateKey(overwrite: boolean) {
  if (info.value?.exists && !overwrite) {
    const ok = await confirmDangerous(
      'Rigenerare la chiave SSH?',
      'Le connessioni esistenti potrebbero smettere di funzionare finché non ridistribuisci la chiave.',
      'Rigenera'
    )
    if (!ok) return
    overwrite = true
  }
  working.value = true
  try {
    await sshKeysService.generate(overwrite)
    toast.success('Chiave SSH generata')
    await loadInfo()
  } catch (e) {
    toast.error('Errore generazione chiave', errorMessage(e))
  } finally {
    working.value = false
  }
}

async function distribute() {
  working.value = true
  try {
    const res = await sshKeysService.distribute()
    const results = Array.isArray(res.data) ? res.data : []
    const ok = results.filter(r => r.success).length
    toast.success('Distribuzione completata', `${ok}/${results.length} nodi aggiornati`)
  } catch (e) {
    toast.error('Errore distribuzione', errorMessage(e))
  } finally {
    working.value = false
  }
}

async function testAll() {
  working.value = true
  testResults.value = []
  try {
    const res = await sshKeysService.testConnections()
    testResults.value = res.data
    const ok = res.data.filter(r => r.success).length
    toast.info('Test completato', `${ok}/${res.data.length} connessioni riuscite`)
  } catch (e) {
    toast.error('Errore test connessioni', errorMessage(e))
  } finally {
    working.value = false
  }
}

onMounted(loadInfo)
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.status-row {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.key-meta {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}
.pub-key textarea {
  font-family: monospace;
  font-size: 0.75rem;
}
.actions-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 16px;
}
.test-results {
  margin-top: 24px;
}
.text-success { color: #00b894; }
.text-danger { color: #ff5252; }
.help-text {
  color: var(--text-secondary);
  font-size: 0.9rem;
}
.loading-state {
  padding: 24px;
  color: var(--text-secondary);
}
</style>
