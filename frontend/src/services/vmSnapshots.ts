import apiClient from './api'

export interface VmTargetRef {
  node_id: number
  vmid: number
  vm_type: 'qemu' | 'lxc'
  name?: string | null
  node_name?: string | null
}

export interface VmSelectors {
  tags: string[]
  node_ids: number[]
  exclude_vmids: number[]
}

export interface VmIndexEntry {
  node_id: number
  node_name: string
  vmid: number
  name: string
  vm_type: 'qemu' | 'lxc'
  status: string
  tags: string[]
  has_pvesr: boolean
  source?: 'static' | 'selector'
  warning?: string | null
}

export interface VmSnapshotResult {
  node_id: number
  node_name: string
  vmid: number
  vm_name?: string | null
  vm_type: string
  snapname: string
  created: boolean
  pruned: string[]
  warning?: string | null
  error?: string | null
}

export interface VmSnapshotJob {
  id: number
  name: string
  description?: string | null
  label: string
  keep: number
  include_vmstate: boolean
  targets: VmTargetRef[]
  selectors: VmSelectors
  schedule?: string | null
  is_active: boolean
  current_status?: string | null
  last_run_at?: string | null
  last_run_status?: 'success' | 'partial' | 'failed' | null
  last_run_duration_sec?: number | null
  next_run_at?: string | null
  notify_mode?: string | null
  notify_subject?: string | null
  run_state?: { results?: VmSnapshotResult[]; summary?: Record<string, number>; snapname?: string } | null
  last_run_error?: string | null
  label_conflicts: string[]
}

export interface VmSnapshotEntry {
  name: string
  snaptime?: number | null
  description?: string | null
  vmstate: boolean
  is_module: boolean
  label?: string | null
}

export interface VmSnapshotVmEntry {
  node_id: number
  node_name?: string | null
  vmid: number
  vm_name?: string | null
  vm_type: string
  status?: string | null
  has_pvesr: boolean
  snapshots: VmSnapshotEntry[]
  error?: string | null
}

export interface VmSnapshotStats {
  total: number
  active: number
  running: number
  failed: number
}

export const vmSnapshotsApi = {
  list: () => apiClient.get<VmSnapshotJob[]>('/vm-snapshots'),
  get: (id: number) => apiClient.get<VmSnapshotJob>(`/vm-snapshots/${id}`),
  create: (data: Record<string, unknown>) => apiClient.post<VmSnapshotJob>('/vm-snapshots', data),
  update: (id: number, data: Record<string, unknown>) =>
    apiClient.put<VmSnapshotJob>(`/vm-snapshots/${id}`, data),
  delete: (id: number) => apiClient.delete(`/vm-snapshots/${id}`),
  run: (id: number) => apiClient.post(`/vm-snapshots/${id}/run`),
  toggle: (id: number) => apiClient.post<VmSnapshotJob>(`/vm-snapshots/${id}/toggle`),
  logs: (id: number) => apiClient.get(`/vm-snapshots/${id}/logs`),
  progress: (id: number) => apiClient.get(`/vm-snapshots/${id}/progress`),
  stats: () => apiClient.get<VmSnapshotStats>('/vm-snapshots/stats/summary'),
  vmIndex: () => apiClient.get<VmIndexEntry[]>('/vm-snapshots/vm-index'),
  resolvePreview: (targets: VmTargetRef[], selectors: Partial<VmSelectors>) =>
    apiClient.post<VmIndexEntry[]>('/vm-snapshots/resolve-preview', { targets, selectors }),
  snapshots: (id: number) => apiClient.get<VmSnapshotVmEntry[]>(`/vm-snapshots/${id}/snapshots`),
}
