<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal-card log-modal">
      <div class="modal-header">
        <h2>Job Logs: {{ jobName }}</h2>
        <button class="close-btn" @click="$emit('close')">&times;</button>
      </div>
      
      <div class="modal-body">
        <div v-if="loading" class="loading-state">Caricamento logs...</div>
        <div v-else-if="logs.length === 0" class="empty-state">Nessun log trovato per questo job.</div>
        
        <div v-else class="log-list">
          <div v-for="log in logs" :key="log.id" class="log-entry" :class="log.status">
            <div class="log-summary" @click="toggleExpand(log.id)">
              <div class="log-status-icon">
                <span v-if="log.status === 'success'">✅</span>
                <span v-else-if="log.status === 'failed'">❌</span>
                <span v-else>⏳</span>
              </div>
              <div class="log-info">
                <div class="log-time">{{ formatDate(log.started_at) }}</div>
                <div class="log-duration" v-if="log.duration">{{ formatDuration(log.duration) }}</div>
              </div>
               <div class="log-message">{{ log.message || log.status }}</div>
               <div class="log-expand-icon">{{ expandedLogs.includes(log.id) ? '▼' : '▶' }}</div>
            </div>
            
            <div v-if="expandedLogs.includes(log.id)" class="log-details">
                <div v-if="log.error" class="log-section error">
                    <h4>Error</h4>
                    <pre>{{ log.error }}</pre>
                </div>
                <div v-if="log.output" class="log-section output">
                    <h4>Output</h4>
                    <pre>{{ log.output }}</pre>
                </div>
                <div class="log-meta">
                    <span>Job Type: {{ log.job_type }}</span>
                    <span>Node: {{ log.node_name }}</span>
                    <span>Dataset: {{ log.dataset }}</span>
                    <span>Transferred: {{ log.transferred || 'N/A' }}</span>
                </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import logsService, { type JobLog } from '../../services/logs';

const props = defineProps<{
    jobId: number | string;
    jobName: string;
    jobType?: string;
}>();

const emit = defineEmits(['close']);

const logs = ref<JobLog[]>([]);
const loading = ref(true);
const expandedLogs = ref<number[]>([]);

const loadLogs = async () => {
    loading.value = true;
    try {
        const res = await logsService.getLogs({
            job_id: props.jobId, // Filter by job_id
            job_type: props.jobType
        });
        logs.value = res.data;
        // Auto-expand first log if it's an error
        if (logs.value.length > 0 && logs.value[0].status === 'failed') {
            expandedLogs.value.push(logs.value[0].id);
        }
    } catch (e) {
        console.error('Error loading logs', e);
    } finally {
        loading.value = false;
    }
};

const toggleExpand = (id: number) => {
    const index = expandedLogs.value.indexOf(id);
    if (index === -1) expandedLogs.value.push(id);
    else expandedLogs.value.splice(index, 1);
};

const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString();
};

const formatDuration = (seconds: number) => {
    return seconds < 60 ? `${seconds}s` : `${(seconds/60).toFixed(1)}m`;
};

onMounted(loadLogs);
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1100;
  backdrop-filter: blur(2px);
}

.log-modal {
  width: 900px;
  max-width: 95vw;
  height: 80vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
}

.modal-header {
  padding: 20px;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  background: var(--bg-secondary);
}

.log-entry {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  margin-bottom: 12px;
  overflow: hidden;
}

.log-entry.failed {
    border-left: 4px solid #ef4444;
}

.log-entry.success {
    border-left: 4px solid #10b981;
}

.log-summary {
  padding: 12px 16px;
  display: flex;
  align-items: center;
  gap: 16px;
  cursor: pointer;
  background: rgba(255, 255, 255, 0.02);
}

.log-summary:hover {
    background: rgba(255, 255, 255, 0.05);
}

.log-status-icon {
    font-size: 1.2rem;
}

.log-info {
    min-width: 150px;
}

.log-time {
    font-weight: 600;
    font-size: 0.9rem;
}

.log-duration {
    font-size: 0.8rem;
    color: var(--text-secondary);
}

.log-message {
    flex: 1;
    font-family: monospace;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--text-secondary);
}

.log-details {
    padding: 16px;
    border-top: 1px solid var(--border-color);
    background: #0d1117; /* Darker background for details */
}

.log-section {
    margin-bottom: 16px;
}

.log-section h4 {
    margin: 0 0 8px 0;
    color: var(--text-secondary);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.log-section pre {
    background: #010409;
    padding: 12px;
    border-radius: 6px;
    overflow-x: auto;
    font-family: 'Fira Code', monospace;
    font-size: 0.85rem;
    white-space: pre-wrap;
    word-break: break-all;
    border: 1px solid #30363d;
}

.log-section.error pre {
    color: #ff7b72;
    border-color: rgba(255, 123, 114, 0.3);
}

.log-section.output pre {
    color: #e6edf3;
}

.log-meta {
    display: flex;
    gap: 16px;
    font-size: 0.8rem;
    color: var(--text-secondary);
    border-top: 1px solid #30363d;
    padding-top: 12px;
}

.close-btn {
  background: transparent;
  border: none;
  font-size: 1.5rem;
  color: var(--text-secondary);
  cursor: pointer;
}
</style>
