import apiClient from './api'

export interface BackupJob {
    id: string;
    job_name: string;
    node_id: string;
    vmid: string;
    pbs_node_id: string;
    datastore: string;
    schedule: string; // 'manual' or cron
    retention: string;
    mode: string; // 'snapshot', 'stop', 'suspend'
    compression: string; // 'zstd', 'lzo', 'gzip'
    last_run?: string;
    last_status?: string;
    last_duration?: string;
    enabled: boolean;
}

export default {
    getJobs() {
        return apiClient.get<BackupJob[]>('/backup-jobs');
    },

    createJob(job: Partial<BackupJob>) {
        return apiClient.post('/backup-jobs', job);
    },

    deleteJob(id: string) {
        return apiClient.delete(`/backup-jobs/${id}`);
    },

    runJob(id: string) {
        return apiClient.post(`/backup-jobs/${id}/run`);
    }
}
