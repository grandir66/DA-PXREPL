import apiClient from './api'

export interface NasSyncJob {
  id: number
  name: string
  description?: string | null
  source_endpoint_id: number
  dest_endpoint_id: number
  source_paths: string[]
  dest_base_path: string
  sync_method: 'auto' | 'direct_rsync' | 'rclone_smb'
  resolved_engine?: 'direct_rsync' | 'rclone_smb' | null
  engine_reason?: string | null
  delete_on_dest: boolean
  rclone_size_only?: boolean
  exclude_presets: string[]
  exclude_patterns: string[]
  bandwidth_limit_kb?: number | null
  snapshot_policy_hint?: Record<string, unknown> | null
  schedule?: string | null
  is_active: boolean
  current_status?: string | null
  last_run_at?: string | null
  last_run_status?: string | null
  last_run_duration_sec?: number | null
  last_bytes_transferred?: number | null
  last_files_transferred?: number | null
  next_run_at?: string | null
  notify_mode?: string | null
  notify_subject?: string | null
  source_endpoint_name?: string | null
  dest_endpoint_name?: string | null
  last_run_error?: string | null
  catalog_bytes_est?: number | null
  catalog_files_est?: number | null
  catalog_updated_at?: string | null
  catalog_folder_count?: number | null
  catalog_has_du?: boolean | null
}

export interface PreflightCheck {
  check: string
  ok: boolean
  message: string
  hint?: string | null
}

export interface EndpointCapabilities {
  rsync_source: boolean
  rsync_dest: boolean
  smb: boolean
  reasons: Record<string, string>
}

export interface NasSyncStats {
  total: number
  active: number
  running: number
  paused: number
  failed: number
}

export const nasSyncApi = {
  list: () => apiClient.get<NasSyncJob[]>('/nas-sync'),
  get: (id: number) => apiClient.get<NasSyncJob>(`/nas-sync/${id}`),
  create: (data: Record<string, unknown>) => apiClient.post<NasSyncJob>('/nas-sync', data),
  update: (id: number, data: Record<string, unknown>) =>
    apiClient.put<NasSyncJob>(`/nas-sync/${id}`, data),
  delete: (id: number) => apiClient.delete(`/nas-sync/${id}`),
  run: (id: number, fresh = false) =>
    apiClient.post(`/nas-sync/${id}/run`, null, { params: fresh ? { fresh: true } : {} }),
  stop: (id: number) => apiClient.post(`/nas-sync/${id}/stop`),
  toggle: (id: number) => apiClient.post<NasSyncJob>(`/nas-sync/${id}/toggle`),
  logs: (id: number) => apiClient.get(`/nas-sync/${id}/logs`),
  progress: (id: number) => apiClient.get(`/nas-sync/${id}/progress`),
  stats: () => apiClient.get<NasSyncStats>('/nas-sync/stats/summary'),
  refreshCatalog: (id: number) => apiClient.post(`/nas-sync/${id}/refresh-catalog`),
  preflight: (id: number) => apiClient.post<PreflightCheck[]>(`/nas-sync/${id}/preflight`),
  capabilities: (endpointId: number) =>
    apiClient.get<EndpointCapabilities>(`/nas-sync/endpoints/${endpointId}/capabilities`),
}
