import apiClient from './api'

export interface JobStats {
    replica_zfs: number;
    replica_btrfs: number;
    backup_pbs: number;
    replica_pbs: number;
    migration: number;
    total: number;
}

export interface NodeMetrics {
    node_id: string;
    node_name: string;
    cpu: {
        usage_percent: number;
        load_1min: number;
        load_5min: number;
        load_15min: number;
    };
    memory: {
        used_gb: number;
        total_gb: number;
        usage_percent: number;
    };
    network: any;
    disk_io: any;
}

export default {
    getOverview() {
        return apiClient.get('/dashboard/overview');
    },

    getJobStats() {
        return apiClient.get<JobStats>('/dashboard/job-stats');
    },

    getNodes() {
        return apiClient.get('/dashboard/nodes');
    },

    getVMs() {
        return apiClient.get('/dashboard/vms');
    },

    getNodesMetrics() {
        return apiClient.get<NodeMetrics[]>('/dashboard/nodes-metrics');
    }
}
