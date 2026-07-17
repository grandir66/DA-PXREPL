import apiClient from './api'

/** Allineato a BackupJobResponse (backend/routers/backup_jobs.py) */
export interface BackupJob {
  id: number
  name: string
  source_node_id: number
  source_node_name?: string
  vm_id: number
  vm_type: string
  vm_name?: string
  pbs_node_id: number
  pbs_node_name?: string
  pbs_datastore?: string
  pbs_storage_id?: string
  backup_mode: string
  backup_compress: string
  include_all_disks: boolean
  schedule?: string
  schedule_config?: Record<string, unknown>
  is_active: boolean
  current_status?: string
  last_run?: string
  last_status?: string
  last_duration?: number
  run_count?: number
  error_count?: number
}

export default {
  getJobs() {
    return apiClient.get<BackupJob[]>('/backup-jobs')
  },

  getStats() {
    return apiClient.get<{ total: number; active: number; running: number; failed: number; scheduled: number }>(
      '/backup-jobs/stats',
    )
  },

  updateJob(id: number | string, job: Record<string, unknown>) {
    return apiClient.put(`/backup-jobs/${id}`, job)
  },

  deleteJob(id: number | string) {
    return apiClient.delete(`/backup-jobs/${id}`)
  },

  runJob(id: number | string) {
    return apiClient.post(`/backup-jobs/${id}/run`)
  },
}
