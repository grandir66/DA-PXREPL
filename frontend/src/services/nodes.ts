import apiClient from './api'

export interface Node {
    id: number;
    name: string;
    hostname: string;
    is_online: boolean;
    node_type?: string; // 'pve' | 'pbs'
    storage_type?: string; // 'zfs' | 'btrfs'
    cpu?: {
        cores?: number;
    };
    memory?: {
        total_gb?: number;
        used_gb?: number;
    };
    storage_total_gb?: number;
    storage_used_gb?: number;
    vm_count?: number;
    running_vm_count?: number;
    temperature_highest_c?: number;
    proxmox_version?: string;
    // PBS specific
    pbs_datastore?: string;
    pbs_fingerprint?: string;
    pbs_username?: string;
    pbs_available?: boolean;
    pbs_version?: string;
}

export interface HostDetails {
    // Add specific details interface if needed based on /nodes/{node_id}/host-details
    [key: string]: any;
}

export default {
    getNodes() {
        return apiClient.get<Node[]>('/nodes/');
    },

    getHostDetails(nodeId: string) {
        return apiClient.get<HostDetails>(`/nodes/${nodeId}/host-details`);
    },

    createNode(data: any) {
        return apiClient.post('/nodes/', data);
    },

    updateNode(id: number | string, data: any) {
        return apiClient.put(`/nodes/${id}`, data);
    },

    deleteNode(id: number | string) {
        return apiClient.delete(`/nodes/${id}`);
    },

    testNode(id: number | string) {
        return apiClient.post(`/nodes/${id}/test`);
    },

    installSanoid(id: number | string) {
        return apiClient.post(`/nodes/${id}/install-sanoid`);
    },

    refreshNode(id: number | string) {
        return apiClient.post(`/nodes/${id}/refresh`);
    },

    updateSanoid(id: number | string) {
        return apiClient.post(`/nodes/${id}/update-sanoid`);
    },


    // Get list of storages for a specific node
    getStorages(nodeId: number | string) {
        return apiClient.get<{ storages: any[] }>(`/nodes/${nodeId}/storages`);
    },

    // Trigger sanoid snapshot immediately
    runSanoid(nodeId: number | string) {
        return apiClient.post(`/nodes/${nodeId}/run-sanoid`);
    },

    // Get ZFS datasets from a node
    getNodeDatasets(nodeId: number | string, refresh: boolean = false) {
        return apiClient.get<any[]>(`/nodes/${nodeId}/datasets?refresh=${refresh}`);
    },

    // Get PBS datastores
    getPBSDatastores(nodeId: number | string) {
        return apiClient.get<{ datastores: string[] }>(`/nodes/${nodeId}/pbs-datastores`);
    },

    // Get VMs for a node (cached)
    getNodeVMs(nodeId: number | string, refresh: boolean = false) {
        return apiClient.get<any[]>(`/nodes/${nodeId}/vms?refresh=${refresh}`);
    },

    // Refresh global cache
    refreshAllCache() {
        return apiClient.post('/nodes/refresh-cache');
    }
}
