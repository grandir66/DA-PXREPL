import apiClient from './api';

export interface PVEReplicationJob {
    id: string;
    target: string;
    vm: number | null;
    jobnum: number | null;
    schedule: string;
    rate: number | null;
    comment: string | null;
    enabled: boolean;
    source: string | null;
    vm_name: string | null;
    vm_type: string | null;
    last_sync: string | null;
    duration: number | null;
    fail_count: number | null;
    error: string | null;
    next_sync: string | null;
    managed_by: string;
    dapx_link: string;
    dapx_jobs: Array<{ kind: string; id: number; name: string }>;
    source_node_id: number | null;
    target_node_id: number | null;
    import_hint: string | null;
    suggested_dapx_kind: string | null;
}

export interface PVEReplicationSummary {
    total: number;
    unlinked: number;
    failed: number;
    enabled: number;
}

export const pveReplicationService = {
    async getJobs(): Promise<PVEReplicationJob[]> {
        const response = await apiClient.get('/pve-replication/');
        return response.data;
    },

    async getSummary(): Promise<PVEReplicationSummary> {
        const response = await apiClient.get('/pve-replication/summary');
        return response.data;
    },

    async deleteJob(id: string): Promise<void> {
        await apiClient.delete(`/pve-replication/${id}`);
    },

    async runJob(id: string): Promise<{ message: string; output: string }> {
        const response = await apiClient.post(`/pve-replication/${id}/run`);
        return response.data;
    },
};
