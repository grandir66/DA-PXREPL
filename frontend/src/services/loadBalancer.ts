
import axios from '@/services/axios';

export interface LoadBalancerConfig {
    saved: any;
    effective: any;
}

export interface AnalysisResult {
    data: any;
    log: string[];
}

export default {
    async analyzeCluster() {
        return axios.get('/load-balancer/analyze');
    },

    async executeBalancing(dryRun: boolean = true, config: any = null) {
        return axios.post('/load-balancer/execute', {
            dry_run: dryRun,
            config: config
        });
    },

    async getConfig() {
        return axios.get('/load-balancer/config');
    },

    async updateConfig(config: any) {
        return axios.post('/load-balancer/config', config);
    }
}
