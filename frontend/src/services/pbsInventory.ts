import apiClient from './api'

export interface PBSBackupEntry {
  'backup-id'?: string
  backup_id?: string
  restore_path?: string
  vmid?: number
  vm_name?: string
  vm_type?: string
  backup_time?: number
  size?: number
  volid?: string
}

export interface PBSVmSummary {
  vmid: number
  vm_name: string
  vm_type: string
  backup_count: number
  latest_backup_time: number
  latest_size: number
}

export interface PBSVmListResponse {
  datastore: string
  vms: PBSVmSummary[]
  vm_count: number
  total_versions: number
}

export interface PBSVmVersionsResponse {
  datastore: string
  vmid: number
  versions: PBSBackupEntry[]
  count: number
}

export interface PBSBackupListResponse {
  datastore: string
  backups: PBSBackupEntry[]
  count: number
}

export interface DirectRestoreRequest {
  pbs_node_id: number
  backup_id: string
  dest_node_id: number
  dest_vmid?: number | null
  dest_storage?: string | null
  vm_type?: 'qemu' | 'lxc'
}

export interface InventoryParams {
  vm_id?: number
  datastore?: string
  pve_node_id?: number
  pbs_storage?: string
  force_refresh?: boolean
}

export default {
  listVmSummaries(pbsNodeId: number | string, params?: InventoryParams) {
    return apiClient.get<PBSVmListResponse>(
      `/recovery-jobs/pbs-nodes/${pbsNodeId}/backups/vms`,
      { params }
    )
  },

  listVmVersions(pbsNodeId: number | string, vmId: number, params?: InventoryParams) {
    return apiClient.get<PBSVmVersionsResponse>(
      `/recovery-jobs/pbs-nodes/${pbsNodeId}/backups/vms/${vmId}`,
      { params }
    )
  },

  listBackups(pbsNodeId: number | string, params?: InventoryParams) {
    return apiClient.get<PBSBackupListResponse>(
      `/recovery-jobs/pbs-nodes/${pbsNodeId}/backups`,
      { params }
    )
  },

  directRestore(payload: DirectRestoreRequest) {
    return apiClient.post('/recovery-jobs/restore', payload)
  },
}
