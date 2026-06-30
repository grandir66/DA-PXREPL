<template>
  <div class="sanoid-syncoid-page">
    <PageHeader
      title="Sanoid / Syncoid"
      subtitle="Versioni installate sui nodi PVE e confronto con l'ultima release GitHub"
      icon="archive"
    >
      <template #actions>
        <button class="btn btn-secondary btn-sm" @click="loadToolStatus(true)" :disabled="toolsLoading">
          <Icon name="refresh" :size="14" :class="{ spin: toolsLoading }" />
          {{ toolsLoading ? 'Verifica…' : 'Verifica versioni' }}
        </button>
        <button
          v-if="authStore.isOperator && toolStatus && (toolStatus.summary.outdated + toolStatus.summary.missing) > 0"
          class="btn btn-primary btn-sm"
          @click="updateAllOutdated"
          :disabled="bulkUpdating"
        >
          {{ bulkUpdating ? 'Aggiornamento…' : `Aggiorna tutti (${toolStatus.summary.outdated + toolStatus.summary.missing})` }}
        </button>
      </template>
    </PageHeader>

    <div class="card upstream-card">
      <div class="card-header">
        <h3>Release upstream</h3>
      </div>
      <div class="card-body">
        <div v-if="toolsLoading && !toolStatus" class="loading-msg">Recupero versioni…</div>
        <div v-else-if="toolStatus?.upstream?.version" class="upstream-info">
          <div>
            <span class="label">Ultima versione GitHub:</span>
            <a :href="toolStatus.upstream.release_url" target="_blank" rel="noopener" class="version-link">
              v{{ toolStatus.upstream.version }}
            </a>
          </div>
          <div class="text-secondary text-sm">
            Repository:
            <a :href="toolStatus.upstream.source_url" target="_blank" rel="noopener">jimsalterjrs/sanoid</a>
            · aggiornato {{ formatUpstreamTime(toolStatus.upstream.fetched_at) }}
          </div>
        </div>
        <div v-else-if="toolStatus?.upstream?.error" class="error-msg">{{ toolStatus.upstream.error }}</div>
        <div v-else class="text-secondary">Premi «Verifica versioni» per controllare GitHub e i nodi.</div>
      </div>
    </div>

    <div v-if="toolStatus" class="summary-grid">
      <div class="summary-card ok"><span class="num">{{ toolStatus.summary.ok }}</span><span class="lbl">Aggiornati</span></div>
      <div class="summary-card warn"><span class="num">{{ toolStatus.summary.outdated }}</span><span class="lbl">Obsoleti</span></div>
      <div class="summary-card danger"><span class="num">{{ toolStatus.summary.missing }}</span><span class="lbl">Mancanti</span></div>
      <div class="summary-card muted"><span class="num">{{ toolStatus.summary.offline }}</span><span class="lbl">Offline</span></div>
    </div>

    <div class="card" v-if="toolStatus">
      <div class="card-header">
        <h3>Nodi PVE</h3>
      </div>
      <div class="table-container">
        <table class="data-table">
          <thead>
            <tr>
              <th>Nodo</th>
              <th>Hostname</th>
              <th>Sanoid</th>
              <th>Syncoid</th>
              <th>Stato</th>
              <th v-if="authStore.isOperator">Azioni</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in toolStatus.nodes" :key="row.node_id">
              <td><strong>{{ row.node_name }}</strong></td>
              <td>{{ row.hostname }}</td>
              <td>{{ formatToolVersion(row.sanoid_installed, row.sanoid_version) }}</td>
              <td>{{ formatToolVersion(row.syncoid_installed, row.syncoid_version) }}</td>
              <td>
                <span class="badge" :class="toolStatusClass(row.status)">{{ toolStatusLabel(row.status) }}</span>
                <span v-if="row.error" class="text-secondary text-xs block">{{ row.error }}</span>
              </td>
              <td v-if="authStore.isOperator">
                <button
                  v-if="row.status === 'outdated' || row.status === 'missing'"
                  class="btn btn-warning btn-sm"
                  @click="updateNodeTools(row.node_id)"
                  :disabled="updatingNodeId === row.node_id"
                >
                  {{ updatingNodeId === row.node_id ? '…' : (row.status === 'missing' ? 'Installa' : 'Aggiorna') }}
                </button>
                <span v-else class="text-secondary">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '../components/ui/PageHeader.vue'
import Icon from '../components/ui/Icon.vue'
import nodesService, { type SanoidSyncoidStatusResponse } from '../services/nodes'
import { useAuthStore } from '../stores/auth'
import { useToast, errorMessage } from '../stores/toast'

const authStore = useAuthStore()
const toast = useToast()

const toolStatus = ref<SanoidSyncoidStatusResponse | null>(null)
const toolsLoading = ref(false)
const bulkUpdating = ref(false)
const updatingNodeId = ref<number | null>(null)

onMounted(() => loadToolStatus(false))

const loadToolStatus = async (refresh = false) => {
  toolsLoading.value = true
  try {
    const res = await nodesService.getSanoidSyncoidStatus(refresh)
    toolStatus.value = res.data
  } catch (e) {
    toast.error('Errore verifica Sanoid/Syncoid', errorMessage(e))
  } finally {
    toolsLoading.value = false
  }
}

const formatToolVersion = (installed: boolean, version: string | null) => {
  if (!installed) return '—'
  return version || 'installato'
}

const formatUpstreamTime = (iso: string) => {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })
  } catch {
    return ''
  }
}

const toolStatusClass = (status: string) => {
  switch (status) {
    case 'ok': return 'badge-success'
    case 'outdated': return 'badge-warning'
    case 'missing': return 'badge-danger'
    case 'offline': return 'badge-secondary'
    case 'error': return 'badge-danger'
    default: return 'badge-secondary'
  }
}

const toolStatusLabel = (status: string) => {
  const labels: Record<string, string> = {
    ok: 'Aggiornato',
    outdated: 'Obsoleto',
    missing: 'Mancante',
    offline: 'Offline',
    error: 'Errore',
    skipped: 'N/A',
  }
  return labels[status] || status
}

const updateNodeTools = async (nodeId: number) => {
  updatingNodeId.value = nodeId
  toast.info('Aggiornamento in corso…', 'Può richiedere alcuni minuti')
  try {
    const res = await nodesService.updateSanoid(nodeId)
    const v = res.data.sanoid_version || res.data.target_version
    toast.success(v ? `Aggiornato a ${v}` : 'Sanoid/Syncoid aggiornato')
    await loadToolStatus(true)
  } catch (e) {
    toast.error('Errore aggiornamento', errorMessage(e))
  } finally {
    updatingNodeId.value = null
  }
}

const updateAllOutdated = async () => {
  const n = (toolStatus.value?.summary.outdated || 0) + (toolStatus.value?.summary.missing || 0)
  if (!n) return
  bulkUpdating.value = true
  toast.info('Aggiornamento bulk avviato…', 'Può richiedere diversi minuti')
  try {
    const res = await nodesService.updateOutdatedSanoidSyncoid()
    const ok = res.data.updated
    const failed = res.data.results.filter(r => !r.success)
    if (ok > 0) {
      toast.success(`Aggiornati ${ok} nodi`)
    }
    if (failed.length) {
      toast.error(`${failed.length} nodi non aggiornati`, failed.map(f => f.node_name).join(', '))
    }
    if (!ok && !failed.length) {
      toast.warning('Nessun nodo da aggiornare')
    }
    await loadToolStatus(true)
  } catch (e) {
    toast.error('Errore aggiornamento bulk', errorMessage(e))
  } finally {
    bulkUpdating.value = false
  }
}
</script>

<style scoped>
.upstream-card .card-body {
  padding: 1rem 1.25rem;
}

.upstream-info {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.label {
  color: var(--text-secondary);
  margin-right: 0.5rem;
}

.version-link {
  font-weight: 600;
  font-size: 1.1rem;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.summary-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 0.75rem 1rem;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.summary-card .num {
  font-size: 1.5rem;
  font-weight: 700;
}

.summary-card .lbl {
  font-size: 0.75rem;
  color: var(--text-secondary);
}

.summary-card.ok .num { color: #00b894; }
.summary-card.warn .num { color: #fdcb6e; }
.summary-card.danger .num { color: #ff5252; }
.summary-card.muted .num { color: var(--text-secondary); }

.loading-msg {
  color: var(--text-secondary);
}

.error-msg {
  color: #ff5252;
}

.text-xs { font-size: 0.75rem; }
.block { display: block; margin-top: 0.25rem; }

@media (max-width: 768px) {
  .summary-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
