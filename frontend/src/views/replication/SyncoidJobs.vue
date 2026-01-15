<template>
    <div class="table-container">
        <table class="data-table">
            <thead>
                <tr>
                    <th>Nome Job</th>
                    <th>Sorgente → Destinazione</th>
                    <th>VM</th>
                    <th>Schedule</th>
                    <th>Ultimo Run</th>
                    <th>Stato</th>
                    <th>Azioni</th>
                </tr>
            </thead>
            <tbody>
                <tr v-for="job in jobs" :key="job.id">
                    <td>
                        <strong>{{ job.job_name }}</strong>
                        <div class="text-xs text-secondary">{{ job.id }}</div>
                    </td>
                    <td class="text-sm">
                        <div>{{ job.source_node_name }} : {{ job.source_dataset }}</div>
                        <div style="text-align: center; color: var(--text-secondary);">↓</div>
                        <div>{{ job.dest_node_name }} : {{ job.dest_dataset }}</div>
                    </td>
                    <td>
                        <div v-if="job.vm_id">
                            <span class="badge badge-info">{{ job.vm_name || 'VM' }} ({{ job.vm_id }})</span>
                        </div>
                        <span v-else class="text-secondary">-</span>
                    </td>
                    <td>
                            <code v-if="job.schedule">{{ job.schedule }}</code>
                            <span v-else class="text-secondary">Manuale</span>
                    </td>
                    <td class="text-sm">
                        <div v-if="job.last_run">{{ formatDate(job.last_run) }}</div>
                        <div v-if="job.last_duration_seconds" class="text-secondary">
                            {{ formatDuration(job.last_duration_seconds) }}
                        </div>
                    </td>
                    <td>
                        <span class="badge" :class="getStatusClass(job.last_status)">
                            {{ job.last_status || 'Never' }}
                        </span>
                    </td>
                    <td>
                        <div class="btn-group">
                            <button class="btn btn-primary btn-xs" @click="runJob(job)" :disabled="job.last_status === 'running'">
                                ▶️ Run
                            </button>
                            <button class="btn btn-secondary btn-xs" @click="selectedJobForLogs = job">📜 Logs</button>
                            <button class="btn btn-secondary btn-xs" @click="$emit('edit', job)">✏️</button>
                            <button class="btn btn-danger btn-xs" @click="deleteJob(job)" title="Elimina">🗑️</button>
                        </div>
                    </td>
                </tr>
                    <tr v-if="jobs.length === 0 && !loading">
                        <td colspan="7" class="empty-state-cell">Nessun job di replica configurato</td>
                </tr>
            </tbody>
        </table>
    </div>


    <!-- Job Logs Viewer -->
    <JobLogViewer 
        v-if="selectedJobForLogs" 
        :job-id="selectedJobForLogs.id" 
        :job-name="selectedJobForLogs.job_name"
        job-type="sync"
        @close="selectedJobForLogs = null" 
    />
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import syncJobsService, { type SyncJob } from '../../services/syncJobs';
import JobLogViewer from '../components/JobLogViewer.vue';

const jobs = ref<SyncJob[]>([]);
const loading = ref(false);
const selectedJobForLogs = ref<SyncJob | null>(null);

onMounted(() => {
    loadJobs();
});

const loadJobs = async () => {
    loading.value = true;
    try {
        const res = await syncJobsService.getJobs();
        jobs.value = res.data;
    } catch (e) {
        console.error('Error loading jobs', e);
    } finally {
        loading.value = false;
    }
};

const runJob = async (job: SyncJob) => {
    if (!confirm(`Avviare job ${job.job_name}?`)) return;
    try {
        await syncJobsService.runJob(job.id);
        loadJobs();
    } catch (e) {
        alert('Errore avvio job');
    }
};

const deleteJob = async (job: SyncJob) => {
    if (!confirm(`Eliminare job ${job.job_name}? Irreversibile.`)) return;
    try {
        await syncJobsService.deleteJob(job.id);
        loadJobs();
    } catch (e) {
        alert('Errore eliminazione job');
    }
};

const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString();
};

const formatDuration = (seconds: number) => {
    if (seconds < 60) return seconds + 's';
    return (seconds / 60).toFixed(1) + 'm';
};

const getStatusClass = (status?: string) => {
    if (status === 'success') return 'badge-success';
    if (status === 'error' || status === 'failed') return 'badge-danger';
    if (status === 'running') return 'badge-warning';
    return 'badge-secondary';
};



const emit = defineEmits(['edit']);
defineExpose({ loadJobs });
</script>

<style scoped>
.text-xs { font-size: 0.75em; }
.text-sm { font-size: 0.85em; }
.btn-group { display: flex; gap: 4px; }
.btn-xs { padding: 4px 8px; font-size: 0.75rem; }
.badge-success { background: rgba(0, 184, 148, 0.15); color: #00b894; }
.badge-danger { background: rgba(255, 82, 82, 0.15); color: #ff5252; }
.badge-warning { background: rgba(255, 179, 0, 0.15); color: #ffb300; }
.badge-info { background: rgba(0, 212, 255, 0.15); color: #00d4ff; }
.empty-state-cell { text-align: center; padding: 40px; color: var(--text-secondary); }
</style>
