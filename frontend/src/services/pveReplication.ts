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
    last_sync: string | null;
    duration: number | null;
    fail_count: number | null;
    error: string | null;
    next_sync: string | null;
}

export const pveReplicationService = {
    async getJobs(): Promise<PVEReplicationJob[]> {
        const response = await apiClient.get('/pve-replication/');
        return response.data;
    },

    async deleteJob(id: string): Promise<void> {
        await apiClient.delete(`/pve-replication/${id}`);
    },

    async runJob(id: string): Promise<{ message: string; output: string }> {
        const response = await apiClient.post(`/pve-replication/${id}/run`);
        return response.data;
    }
};
