import apiClient from './api'

/** Allineato a SyncJobResponse (backend/routers/sync_jobs.py) */
export interface SyncJob {
  id: number
  name: string
  sync_method?: string
  source_node_id: number
  source_dataset: string
  dest_node_id: number
  dest_dataset: string
  dest_subfolder?: string
  recursive: boolean
  compress?: string
  schedule?: string
  schedule_config?: Record<string, unknown>
  is_active: boolean
  register_vm?: boolean
  resync_dopo_migrazione?: boolean
  richiede_replica_completa?: boolean
  vm_id?: number
  dest_vm_id?: number
  vm_type?: string
  vm_name?: string
  vm_group_id?: string
  disk_name?: string
  source_storage?: string
  dest_storage?: string
  last_run?: string
  last_status?: string
  current_status?: string
  last_duration?: number
  last_transferred?: string
  run_count?: number
  error_count?: number
  source_node_name?: string
  dest_node_name?: string
}

export default {
  getJobs() {
    return apiClient.get<SyncJob[]>('/sync-jobs')
  },

  updateJob(id: number | string, job: Record<string, unknown>) {
    return apiClient.put(`/sync-jobs/${id}`, job)
  },

  deleteJob(id: number | string) {
    return apiClient.delete(`/sync-jobs/${id}`)
  },

  // replicaCompleta (3.23.0): syncoid con --force-delete per QUESTA corsa —
  // ricrea la destinazione se non ha snapshot in comune (dopo una migrazione live).
  runJob(id: number | string, replicaCompleta = false) {
    return apiClient.post(`/sync-jobs/${id}/run${replicaCompleta ? '?replica_completa=true' : ''}`)
  },

  runVmGroup(groupId: string, replicaCompleta = false) {
    return apiClient.post(`/sync-jobs/vm-group/${groupId}/run${replicaCompleta ? '?replica_completa=true' : ''}`)
  },

  toggleJob(id: number | string) {
    return apiClient.post(`/sync-jobs/${id}/toggle`)
  },

  createVMReplica(data: Record<string, unknown>) {
    return apiClient.post('/sync-jobs/vm-replica', data)
  },
}
