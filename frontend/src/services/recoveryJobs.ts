import apiClient from './api'

/** Allineato a RecoveryJobResponse (backend/routers/recovery_jobs.py) */
export interface RecoveryJob {
  id: number
  name: string
  source_node_id: number
  pbs_node_id: number
  dest_node_id: number
  vm_id: number
  vm_type: string
  vm_name?: string
  schedule?: string
  is_active: boolean
  backup_mode?: string
  backup_compress?: string
  created_at?: string
  source_node_name?: string
  pbs_node_name?: string
  dest_node_name?: string
  last_backup_duration?: number
  last_restore_duration?: number
  last_run?: string
  last_status?: string
  dest_vm_id?: number
  dest_vm_name_suffix?: string
  dest_storage?: string
}

export default {
  getJobs() {
    return apiClient.get<RecoveryJob[]>('/recovery-jobs/')
  },

  createJob(job: Record<string, unknown>) {
    return apiClient.post('/recovery-jobs/', job)
  },

  updateJob(id: number | string, job: Record<string, unknown>) {
    return apiClient.put(`/recovery-jobs/${id}`, job)
  },

  deleteJob(id: number | string) {
    return apiClient.delete(`/recovery-jobs/${id}`)
  },

  runJob(id: number | string) {
    return apiClient.post(`/recovery-jobs/${id}/run`)
  },
}
