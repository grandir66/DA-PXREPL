import apiClient from './api'

export interface FileReplicationJob {
  id: number
  name: string
  description?: string | null
  source_endpoint_id: number
  dest_endpoint_id: number
  source_paths: string[]
  dest_staging_path: string
  sync_method: string
  delete_on_dest: boolean
  rclone_size_only?: boolean
  on_source_delete: string
  exclude_presets: string[]
  exclude_patterns: string[]
  bandwidth_limit_kb?: number | null
  immutability_strategy: string
  snapshot_policy_hint?: Record<string, unknown> | null
  schedule?: string | null
  is_active: boolean
  current_status?: string | null
  last_run_at?: string | null
  last_run_status?: string | null
  last_run_duration_sec?: number | null
  last_bytes_transferred?: number | null
  last_files_transferred?: number | null
  last_run_error?: string | null
  catalog_files_est?: number | null
  catalog_bytes_est?: number | null
  catalog_updated_at?: string | null
  catalog_folder_count?: number | null
  catalog_du_at?: string | null
  catalog_has_du?: boolean | null
  resume_step_index?: number | null
  resume_source_path?: string | null
  resume_from_path?: string | null
  resume_last_file?: string | null
  resume_paused_at?: string | null
  source_endpoint_name?: string | null
  dest_endpoint_name?: string | null
  notify_mode?: string
}

export const fileReplicationApi = {
  list: () => apiClient.get<FileReplicationJob[]>('/file-replication'),
  get: (id: number) => apiClient.get<FileReplicationJob>(`/file-replication/${id}`),
  create: (data: Record<string, unknown>) =>
    apiClient.post<FileReplicationJob>('/file-replication', data),
  update: (id: number, data: Record<string, unknown>) =>
    apiClient.put<FileReplicationJob>(`/file-replication/${id}`, data),
  delete: (id: number) => apiClient.delete(`/file-replication/${id}`),
  run: (id: number, fresh = false) =>
    apiClient.post(`/file-replication/${id}/run`, null, { params: { fresh } }),
  stop: (id: number) => apiClient.post(`/file-replication/${id}/stop`),
  refreshCatalog: (id: number) =>
    apiClient.post<{ ok: boolean; message: string }>(`/file-replication/${id}/refresh-catalog`),
  toggle: (id: number) => apiClient.post<FileReplicationJob>(`/file-replication/${id}/toggle`),
  logs: (id: number) => apiClient.get(`/file-replication/${id}/logs`),
  progress: (id: number) => apiClient.get(`/file-replication/${id}/progress`),
  stats: () =>
    apiClient.get<{ total: number; active: number; running: number; paused: number; failed: number }>(
      '/file-replication/stats/summary',
    ),
}
