
import axios from '../services/api';

export default {
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
}
