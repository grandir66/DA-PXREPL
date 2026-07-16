import apiClient from './api'

export interface PBSBackupEntry {
  'backup-id'?: string
  backup_id?: string
  vmid?: number
  vm_name?: string
  vm_type?: string
  backup_time?: number
  size?: number
  volid?: string
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

export default {
  listBackups(
    pbsNodeId: number | string,
    params?: {
      vm_id?: number
      datastore?: string
      pve_node_id?: number
      pbs_storage?: string
    }
  ) {
    return apiClient.get<PBSBackupListResponse>(
      `/recovery-jobs/pbs-nodes/${pbsNodeId}/backups`,
      { params }
    )
  },

  directRestore(payload: DirectRestoreRequest) {
    return apiClient.post('/recovery-jobs/restore', payload)
  },
}
