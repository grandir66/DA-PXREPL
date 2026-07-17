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
  last_run_error?: string | null
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
  run: (id: number) => apiClient.post(`/file-replication/${id}/run`),
  toggle: (id: number) => apiClient.post<FileReplicationJob>(`/file-replication/${id}/toggle`),
  logs: (id: number) => apiClient.get(`/file-replication/${id}/logs`),
  progress: (id: number) => apiClient.get(`/file-replication/${id}/progress`),
  stats: () => apiClient.get<{ total: number; active: number; running: number; failed: number }>(
    '/file-replication/stats/summary',
  ),
}
