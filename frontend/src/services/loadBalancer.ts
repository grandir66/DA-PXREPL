
import axios from '../services/api';

export interface LoadBalancerConfig {
    saved: any;
    effective: any;
}

export interface AnalysisResult {
    data: any;
    log: string[];
}

export default {
    async analyzeCluster(clusterId?: number) {
        const config: any = {};
        if (clusterId) config.params = { cluster_id: clusterId };
        return axios.get('/load-balancer/analyze', config);
    },

    async executeBalancing(dryRun: boolean = true, config: any = null, clusterId?: number) {
        const params: any = {};
        if (clusterId) params.cluster_id = clusterId;

        return axios.post('/load-balancer/execute', {
            dry_run: dryRun,
            config: config
        }, { params });
    },

    async getConfig() {
        return axios.get('/load-balancer/config');
    },

    async updateConfig(config: any) {
        return axios.post('/load-balancer/config', config);
    },

    // Migration History
    async getMigrationHistory(limit: number = 100, status?: string) {
        const params = new URLSearchParams();
        params.append('limit', limit.toString());
        if (status) params.append('status', status);
        return axios.get(`/load-balancer/migrations?${params.toString()}`);
    },

    async getMigration(id: number) {
        return axios.get(`/load-balancer/migrations/${id}`);
    }
}
