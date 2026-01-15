<template>
  <div class="migration-jobs-page">
    <div class="page-header">
        <h1 class="page-title">🚚 Migrazioni</h1>
        <p class="page-subtitle">Spostamento e copia VM tra i nodi</p>
        <div style="display: flex; align-items: center; gap: 12px; margin-top: 12px;">
            <button class="btn btn-secondary btn-sm" @click="loadJobs" :disabled="loading">
                <span v-if="loading" class="spinner-sm"></span>
                <span v-else>🔄 Aggiorna</span>
            </button>
            <button class="btn btn-primary btn-sm" @click="showCreateModal = true">
                + Nuova Migrazione
            </button>
        </div>
    </div>

    <div class="card">
        <div class="table-container">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Nome</th>
                        <th>VM</th>
                        <th>Path (Source → Dest)</th>
                        <th>Tipo</th>
                        <th>Schedule</th>
                        <th>Stato</th>
                        <th>Azioni</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="job in jobs" :key="job.id">
                        <td>
                            <strong>{{ job.name }}</strong>
                        </td>
                        <td>
                            <span class="badge badge-info">{{ job.vm_type }} {{ job.vm_id }}</span>
                            <div class="text-xs mt-1">{{ job.vm_name }}</div>
                        </td>
                        <td class="text-sm">
                            {{ job.source_node_name || job.source_node_id }} 
                            <span>→</span> 
                            {{ job.dest_node_name || job.dest_node_id }}
                            <div v-if="job.dest_vm_id" class="text-xs text-secondary">
                                New ID: {{ job.dest_vm_id }}
                            </div>
                        </td>
                        <td>
                            <span class="badge" :class="job.migration_type === 'move' ? 'badge-warning' : 'badge-primary'">
                                {{ job.migration_type }}
                            </span>
                        </td>
                        <td>
                             <code v-if="job.schedule">{{ job.schedule }}</code>
                             <span v-else class="text-secondary">-</span>
                        </td>
                        <td>
                            <span class="badge" :class="getStatusClass(job.last_status)">
                                {{ job.last_status || 'Never' }}
                            </span>
                             <div v-if="job.last_run" class="text-xs text-secondary mt-1">
                                {{ formatDate(job.last_run) }}
                            </div>
                        </td>
                        <td>
                            <div class="btn-group">
                                <button class="btn btn-primary btn-xs" @click="runJob(job)" :disabled="job.last_status === 'running'">
                                    ▶️ Run
                                </button>
                                <button class="btn btn-secondary btn-xs" @click="toggleJob(job)">
                                    {{ job.is_active ? '⏸️' : '▶️' }}
                                </button>
                                <button class="btn btn-danger btn-xs" @click="deleteJob(job)">🗑️</button>
                            </div>
                        </td>
                    </tr>
                     <tr v-if="jobs.length === 0 && !loading">
                         <td colspan="7" class="empty-state-cell">Nessun job di migrazione configurato</td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import migrationJobsService, { type MigrationJob } from '../../services/migrationJobs';

const jobs = ref<MigrationJob[]>([]);
const loading = ref(false);
const showCreateModal = ref(false);

onMounted(() => {
    loadJobs();
});

const loadJobs = async () => {
    loading.value = true;
    try {
        const res = await migrationJobsService.getJobs();
        jobs.value = res.data;
    } catch (e) {
        console.error('Error loading migration jobs', e);
    } finally {
        loading.value = false;
    }
};

const runJob = async (job: MigrationJob) => {
    if (!confirm(`Avviare migrazione ${job.name}?`)) return;
    try {
        const res = await migrationJobsService.runJob(job.id);
        if (res.data.requires_confirmation) {
             if (confirm(res.data.message)) {
                 await migrationJobsService.runJob(job.id, true);
             }
        }
        loadJobs();
    } catch (e) {
        alert('Errore avvio migrazione');
    }
};

const toggleJob = async (job: MigrationJob) => {
    try {
        await migrationJobsService.toggleJob(job.id);
        job.is_active = !job.is_active;
    } catch (e) {
        alert('Errore modifica stato job');
    }
}

const deleteJob = async (job: MigrationJob) => {
    if (!confirm('Eliminare questo job di migrazione?')) return;
    try {
        await migrationJobsService.deleteJob(job.id);
        loadJobs();
    } catch (e) {
        alert('Errore eliminazione job');
    }
};

const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString();
};

const getStatusClass = (status?: string) => {
    if (status === 'success' || status === 'OK') return 'badge-success';
    if (status === 'error' || status === 'failed') return 'badge-danger';
    if (status === 'running') return 'badge-warning';
    return 'badge-secondary';
};
</script>

<style scoped>
.text-xs { font-size: 0.75em; }
.mt-1 { margin-top: 4px; }
.text-sm { font-size: 0.85em; }
.btn-group { display: flex; gap: 4px; }
.btn-xs { padding: 4px 8px; font-size: 0.75rem; }
.badge-info { background: rgba(0, 212, 255, 0.15); color: #00d4ff; }
.badge-success { background: rgba(0, 184, 148, 0.15); color: #00b894; }
.badge-danger { background: rgba(255, 82, 82, 0.15); color: #ff5252; }
.badge-warning { background: rgba(255, 179, 0, 0.15); color: #ffb300; }
.badge-primary { background: rgba(108, 92, 231, 0.15); color: #6c5ce7; }
.empty-state-cell { text-align: center; padding: 40px; color: var(--text-secondary); }
.spinner-sm {
    display: inline-block;
    width: 12px; height: 12px;
    border: 2px solid currentColor;
    border-top-color: transparent;
    border-radius: 50%;
    animation: spin 1s linear infinite;
}
</style>
