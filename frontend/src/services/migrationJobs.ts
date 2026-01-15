import apiClient from './api'

export interface MigrationJob {
    id: string;
    name: string;
    source_node_id: string;
    source_node_name?: string;
    vm_id: string;
    vm_type: string;
    vm_name?: string;
    dest_node_id: string;
    dest_node_name?: string;
    dest_vm_id?: string;
    migration_type: string; // 'copy', 'move'
    schedule?: string;
    is_active: boolean;
    last_run?: string;
    last_status?: string;
    last_duration?: number;
}

export default {
    getJobs() {
        return apiClient.get<MigrationJob[]>('/migration-jobs');
    },

    createJob(job: Partial<MigrationJob>) {
        return apiClient.post('/migration-jobs', job);
    },

    deleteJob(id: string) {
        return apiClient.delete(`/migration-jobs/${id}`);
    },

    runJob(id: string, force = false) {
        return apiClient.post(`/migration-jobs/${id}/run`, null, { params: { force } });
    },

    toggleJob(id: string) {
        return apiClient.post(`/migration-jobs/${id}/toggle`);
    }
}
