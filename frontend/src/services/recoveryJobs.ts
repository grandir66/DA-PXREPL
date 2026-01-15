import apiClient from './api'

export interface RecoveryJob {
    id: string;
    name: string;
    source_node_id: string;
    pbs_node_id: string;
    dest_node_id: string;
    vm_id: string;
    vm_type: string;
    vm_name: string;
    schedule: string;
    enabled: boolean;
    backup_mode: string;
    backup_compress: string;
    created_at: string;
    source_node_name?: string;
    pbs_node_name?: string;
    dest_node_name?: string;
    last_backup_duration?: number;
    last_restore_duration?: number;
    last_run?: string;
    last_status?: string;
    last_duration?: string;
    dest_vm_id?: string;
    dest_vm_name_suffix?: string;
    dest_storage?: string;
}

export default {
    getJobs() {
        return apiClient.get<RecoveryJob[]>('/recovery-jobs/');
    },

    createJob(job: Partial<RecoveryJob>) {
        return apiClient.post('/recovery-jobs/', job);
    },

    deleteJob(id: string) {
        return apiClient.delete(`/recovery-jobs/${id}`);
    },

    runJob(id: string) {
        return apiClient.post(`/recovery-jobs/${id}/run`);
    },

    updateJob(id: string, job: Partial<RecoveryJob>) {
        return apiClient.put(`/recovery-jobs/${id}`, job);
    }
}
