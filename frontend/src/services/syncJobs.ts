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

  runJob(id: number | string) {
    return apiClient.post(`/sync-jobs/${id}/run`)
  },

  runVmGroup(groupId: string) {
    return apiClient.post(`/sync-jobs/vm-group/${groupId}/run`)
  },

  toggleJob(id: number | string) {
    return apiClient.post(`/sync-jobs/${id}/toggle`)
  },

  createVMReplica(data: Record<string, unknown>) {
    return apiClient.post('/sync-jobs/vm-replica', data)
  },
}
