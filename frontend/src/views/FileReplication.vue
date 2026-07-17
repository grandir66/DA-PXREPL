<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import FileEndpointForm from '../components/file-replication/FileEndpointForm.vue'
import FileReplJobModal from '../components/file-replication/FileReplJobModal.vue'
import { fileEndpointsApi, type FileEndpoint } from '../services/fileEndpoints'
import { fileReplicationApi, type FileReplicationJob } from '../services/fileReplication'

const jobs = ref<FileReplicationJob[]>([])
const endpoints = ref<FileEndpoint[]>([])
const stats = ref({ total: 0, active: 0, running: 0, failed: 0 })
const showJobModal = ref(false)
const showEndpointForm = ref(false)
const loading = ref(false)

const activeCount = computed(() => stats.value.active)
const runningCount = computed(() => stats.value.running)
const failedCount = computed(() => stats.value.failed)

async function refresh() {
  loading.value = true
  try {
    const [j, e, s] = await Promise.all([
      fileReplicationApi.list(),
      fileEndpointsApi.list(),
      fileReplicationApi.stats(),
    ])
    jobs.value = j.data
    endpoints.value = e.data
    stats.value = s.data
  } finally {
    loading.value = false
  }
}

async function runJob(id: number) {
  await fileReplicationApi.run(id)
  await refresh()
}

async function toggleJob(id: number) {
  await fileReplicationApi.toggle(id)
  await refresh()
}

async function deleteJob(id: number) {
  if (!confirm('Eliminare il job?')) return
  await fileReplicationApi.delete(id)
  await refresh()
}

function onJobCreated() {
  showJobModal.value = false
  refresh()
}

function onEndpointSaved() {
  showEndpointForm.value = false
  refresh()
}

function formatDate(v?: string | null) {
  if (!v) return '—'
  return new Date(v).toLocaleString()
}

onMounted(refresh)
</script>

<template>
  <div class="repl-view">
    <header class="repl-head">
      <div class="repl-head-left">
        <h1>Replica file → QNAP WORM</h1>
        <p class="repl-sub">
          Sync monodirezionale da Synology, QNAP, Linux o Windows verso share staging QuTS hero h6.0.
          Immutabilità via snapshot nativi QNAP.
        </p>
      </div>
      <div class="repl-head-actions">
        <button class="btn btn-secondary mr-2" @click="showEndpointForm = !showEndpointForm">
          Endpoint
        </button>
        <button class="btn btn-primary" @click="showJobModal = true">+ Nuovo job</button>
      </div>
    </header>

    <section class="repl-stats">
      <div class="repl-stat">
        <span class="repl-stat-label">Job totali</span>
        <span class="repl-stat-val">{{ stats.total }}</span>
      </div>
      <div class="repl-stat">
        <span class="repl-stat-label">Attivi</span>
        <span class="repl-stat-val text-success">{{ activeCount }}</span>
      </div>
      <div class="repl-stat">
        <span class="repl-stat-label">In esecuzione</span>
        <span class="repl-stat-val text-warning">{{ runningCount }}</span>
      </div>
      <div class="repl-stat">
        <span class="repl-stat-label">Falliti</span>
        <span class="repl-stat-val text-danger">{{ failedCount }}</span>
      </div>
    </section>

    <FileEndpointForm v-if="showEndpointForm" @saved="onEndpointSaved" />

    <div class="card">
      <div class="card-header">
        <h3>Job configurati</h3>
        <button class="btn btn-sm btn-secondary" :disabled="loading" @click="refresh">Aggiorna</button>
      </div>
      <div class="card-body p-0">
        <table class="data-table" v-if="jobs.length">
          <thead>
            <tr>
              <th>Nome</th>
              <th>Sorgente</th>
              <th>Destinazione</th>
              <th>Schedule</th>
              <th>Ultimo run</th>
              <th>Stato</th>
              <th>Azioni</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="job in jobs" :key="job.id">
              <td>{{ job.name }}</td>
              <td>{{ job.source_endpoint_name }}</td>
              <td>{{ job.dest_endpoint_name }}<br /><small>{{ job.dest_staging_path }}</small></td>
              <td><code>{{ job.schedule || 'manuale' }}</code></td>
              <td>{{ formatDate(job.last_run_at) }}</td>
              <td>
                <span :class="job.last_run_status === 'success' ? 'text-success' : job.last_run_status === 'failed' ? 'text-danger' : ''">
                  {{ job.current_status || job.last_run_status || 'idle' }}
                </span>
              </td>
              <td class="actions">
                <button class="btn btn-sm btn-primary" @click="runJob(job.id)">Run</button>
                <button class="btn btn-sm btn-secondary" @click="toggleJob(job.id)">
                  {{ job.is_active ? 'Off' : 'On' }}
                </button>
                <button class="btn btn-sm btn-danger" @click="deleteJob(job.id)">Del</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="p-4">Nessun job. Crea un endpoint e un job per iniziare.</p>
      </div>
    </div>

    <div class="card mt-4">
      <div class="card-header"><h3>Endpoint registrati ({{ endpoints.length }})</h3></div>
      <ul class="endpoint-list">
        <li v-for="ep in endpoints" :key="ep.id">
          <strong>{{ ep.name }}</strong>
          <span class="badge">{{ ep.endpoint_type }}</span>
          <span class="muted">{{ ep.host }}:{{ ep.port }}</span>
          <span v-if="ep.last_test_status" :class="ep.last_test_status === 'success' ? 'text-success' : 'text-danger'">
            {{ ep.last_test_status }}
          </span>
        </li>
      </ul>
    </div>

    <FileReplJobModal v-if="showJobModal" @close="showJobModal = false" @created="onJobCreated" />
  </div>
</template>

<style scoped>
.repl-view { padding: 0; }
.repl-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; gap: 16px; }
.repl-sub { opacity: 0.75; margin-top: 4px; max-width: 640px; }
.repl-stats { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
.repl-stat { background: var(--bg-secondary, #1a1a2e); padding: 12px 20px; border-radius: 8px; min-width: 120px; }
.repl-stat-label { display: block; font-size: 0.75rem; opacity: 0.7; }
.repl-stat-val { font-size: 1.5rem; font-weight: 700; }
.actions { display: flex; gap: 6px; flex-wrap: wrap; }
.endpoint-list { list-style: none; padding: 12px 20px; margin: 0; }
.endpoint-list li { display: flex; gap: 12px; align-items: center; padding: 6px 0; flex-wrap: wrap; }
.badge { font-size: 0.75rem; background: #333; padding: 2px 8px; border-radius: 4px; }
.muted { opacity: 0.65; font-size: 0.85rem; }
.mr-2 { margin-right: 8px; }
.mt-4 { margin-top: 16px; }
.p-4 { padding: 16px; }
</style>
