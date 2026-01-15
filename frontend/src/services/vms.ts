import apiClient from './api'

export interface VM {
    vmid: number | string;
    name: string;
    node: string;
    node_id?: number;
    status: string;
    type: string; // 'qemu' | 'lxc'

    // Resource metrics
    cpu?: number; // CPU usage 0-1 (e.g. 0.05 for 5%)
    cpu_percent?: number;
    maxcpu?: number;
    mem?: number; // Used bytes
    maxmem?: number; // Total bytes
    disk?: number; // Used bytes
    maxdisk?: number; // Total bytes
    uptime?: number;

    // Network
    net0_ip?: string;
    lock?: string;

    // UI helpers
    loading?: boolean;
    backupCount?: number;
}

export interface Snapshot {
    name: string;
    snaptime: number;
    description: string;
    parent: string;
    vmstate: number;
}

export interface Backup {
    volid: string; // e.g. "backup/vm/100/2024-01-01T00:00:00Z"
    "backup-time": number;
    "backup-type": string;
    size: number;
    files: string[];
    notes?: string;
    storage_id?: string;
}

export interface SanoidConfig {
    enable: boolean;
    template: string;
    autosnap: boolean;
    autoprune: boolean;
    hourly: number;
    daily: number;
    weekly: number;
    monthly: number;
    yearly: number;
    datasets: string[];
}

export interface ZFSSnapshot {
    name: string;
    dataset: string;
    creation?: string;
    used?: string;
}

export default {
    getVMs() {
        return apiClient.get<VM[]>('/dashboard/vms');
    },

    getVMDetails(node: number | string, vmid: number | string) {
        return apiClient.get(`/vms/node/${node}/vm/${vmid}/full-details`);
    },

    // Lifecycle
    manageState(node: number | string, vmid: number | string, action: 'start' | 'stop' | 'shutdown' | 'reboot' | 'suspend' | 'resume') {
        return apiClient.post(`/vms/node/${node}/vm/${vmid}/status/${action}`);
    },

    // Snapshots
    createSnapshot(node: number | string, vmid: number | string, snapname: string, description: string = '', vmstate: boolean = false) {
        return apiClient.post(`/vms/node/${node}/vm/${vmid}/snapshot`, { snapname, description, vmstate });
    },

    rollbackSnapshot(node: number | string, vmid: number | string, snapname: string, start_vm: boolean = false) {
        return apiClient.post(`/vms/node/${node}/vm/${vmid}/snapshot/${snapname}/rollback?start_vm=${start_vm}`);
    },

    deleteSnapshot(node: number | string, vmid: number | string, snapname: string) {
        return apiClient.delete(`/vms/node/${node}/vm/${vmid}/snapshot/${snapname}`);
    },

    // Sanoid & ZFS
    getSanoidConfig(node: number | string, vmid: number | string) {
        return apiClient.get<SanoidConfig>(`/vms/node/${node}/vm/${vmid}/sanoid-config`);
    },

    updateSanoidConfig(node: number | string, vmid: number | string, config: SanoidConfig) {
        return apiClient.post(`/vms/node/${node}/vm/${vmid}/sanoid-config`, config);
    },

    getZFSSnapshots(node: number | string, vmid: number | string) {
        return apiClient.get<ZFSSnapshot[]>(`/vms/node/${node}/vm/${vmid}/zfs-snapshots`);
    },

    restoreZFSSnapshot(node: number | string, vmid: number | string, snapshot_name: string, action: 'rollback' | 'clone', new_vmid?: number) {
        return apiClient.post(`/vms/node/${node}/vm/${vmid}/zfs-restore`, { snapshot_name, action, new_vmid });
    },

    deleteZfsSnapshot(node: number | string, vmid: number | string, snapshot_name: string) {
        return apiClient.delete(`/vms/node/${node}/vm/${vmid}/zfs-snapshots`, { data: { snapshot_name } });
    },

    snapshotNow(node: number | string, vmid: number | string) {
        return apiClient.post<{ message: string, snapshot_name: string }>(`/vms/node/${node}/vm/${vmid}/snapshot-now`);
    },

    // Backups
    getBackups(node: number | string, vmid: number | string) {
        return apiClient.get<Backup[]>(`/vms/node/${node}/vm/${vmid}/backups`);
    },

    restoreBackup(node: number, vmid: number, backup_id: string, pbs_storage: string, dest_storage: string | null = null, start_vm: boolean = false, target_node_id: number | null = null) {
        return apiClient.post(`/vms/node/${node}/vm/${vmid}/restore`, {
            backup_id,
            pbs_storage,
            dest_storage,
            start_vm,
            target_node_id
        });
    },

    // Get VMs on a specific node
    getNodeVMs(nodeId: number | string) {
        return apiClient.get<VM[]>(`/nodes/${nodeId}/vms`);
    },

    // Get next available VMID on a node
    getNextVmid(nodeId: number | string) {
        return apiClient.get<{ next_vmid: number }>(`/vms/node/${nodeId}/next-vmid`);
    }
}
