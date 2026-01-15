import apiClient from './api'

export interface SyncJob {
    id: string;
    job_name: string;
    source_node_id: string;
    source_dataset: string;
    dest_node_id: string;
    dest_dataset: string;
    source_node_name?: string;
    dest_node_name?: string;
    schedule: string;
    recursive: boolean;
    compress: string;
    last_run?: string;
    last_duration_seconds?: number;
    last_transfer_size_bytes?: number;
    last_status?: string; // 'success', 'error', 'running'
    enabled: boolean;
    vm_id?: string;
    vm_name?: string;
}

export default {
    getJobs() {
        return apiClient.get<SyncJob[]>('/sync-jobs');
    },

    createJob(job: Partial<SyncJob>) {
        return apiClient.post('/sync-jobs', job);
    },

    updateJob(id: string, job: Partial<SyncJob>) {
        return apiClient.put(`/sync-jobs/${id}`, job); // Backend usually expects PUT for updates
    },

    deleteJob(id: string) {
        return apiClient.delete(`/sync-jobs/${id}`);
    },

    runJob(id: string) {
        return apiClient.post(`/sync-jobs/${id}/run`);
    },

    toggleJob(id: string, enabled: boolean) {
        return apiClient.put(`/sync-jobs/${id}/enable`, { enabled });
    },

    createVMReplica(data: any) {
        return apiClient.post('/sync-jobs/vm-replica', data);
    }
}
