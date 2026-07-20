import apiClient from './api'

export interface VmBackupTarget {
  vm_id: number
  vm_type: string
  vm_name?: string | null
  source_node_id: number
}

/** Allineato a BackupJobResponse (backend/routers/backup_jobs.py) */
export interface BackupJob {
  id: number
  name: string
  source_node_id: number
  source_node_name?: string
  vm_id: number
  vm_type: string
  vm_name?: string
  vm_targets?: VmBackupTarget[]
  vm_count?: number
  vm_summary?: string
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

export interface ClusterPBSVmLabel {
  vm_id: number
  vm_name?: string | null
  vm_type?: string
  node?: string | null
}

export interface ClusterPBSBackupJob {
  id: string
  storage: string
  pbs_server?: string | null
  pbs_datastore?: string | null
  schedule?: string
  mode?: string
  compress?: string
  enabled: boolean
  node?: string | null
  maxfiles?: number | null
  vmids: number[]
  vm_count: number
  vm_labels: ClusterPBSVmLabel[]
  vm_selection?: string | null
  managed_by: string
  dapx_link: string
  dapx_jobs: Array<{ kind: string; id: number; name: string; vm_id?: number }>
  pbs_node_id?: number | null
  exec_node_id?: number | null
  import_hint?: string | null
  suggested_dapx_kind?: string | null
}

export interface ClusterPBSBackupSummary {
  total: number
  unlinked: number
  partial: number
  enabled: number
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

  getClusterJobs() {
    return apiClient.get<ClusterPBSBackupJob[]>('/backup-jobs/cluster-jobs')
  },

  getClusterSummary() {
    return apiClient.get<ClusterPBSBackupSummary>('/backup-jobs/cluster-jobs/summary')
  },

  runClusterJob(id: string) {
    return apiClient.post<{ message: string; output?: string }>(`/backup-jobs/cluster-jobs/${encodeURIComponent(id)}/run`)
  },

  deleteClusterJob(id: string) {
    return apiClient.delete(`/backup-jobs/cluster-jobs/${encodeURIComponent(id)}`)
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
