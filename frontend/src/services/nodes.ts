import apiClient from './api'

export interface NodeStorage {
  name: string
  type: string
  content?: string
  enabled?: boolean
  shared?: boolean
  avail_gb?: number
  total_gb?: number
  used_gb?: number
}

export interface HostInfoStorageItem {
  name?: string
  type?: string
  status?: string
  shared?: boolean | number
  content?: string
  used_gb?: number
  total_gb?: number
  used_percent?: number
}

export interface HostInfo {
  cpu?: {
    threads?: number
    sockets?: number
    load_1m?: number
    load_5m?: number
    load_15m?: number
    model?: string
  }
  memory?: {
    available_gb?: number
    swap_total_gb?: number
    swap_used_gb?: number
  }
  hardware?: {
    manufacturer?: string
    model?: string
    serial?: string
    bios_vendor?: string
    bios_version?: string
    board?: string
  }
  temperature?: { highest?: number }
  license?: { status?: string; subscription?: string }
  storage?: HostInfoStorageItem[]
  // Configurazioni di rete/guest PVE (struttura eterogenea, gestite dai helper)
  network?: any[]
  guests?: any[]
  proxmox_version?: string
  kernel_version?: string
  uptime_seconds?: number
  node_name?: string
}

export interface Node {
  id: number
  name: string
  hostname: string
  is_online: boolean
  node_type?: string
  storage_type?: string
  cpu?: { cores?: number; model?: string }
  memory?: { total_gb?: number; used_gb?: number }
  storage_total_gb?: number
  storage_used_gb?: number
  vm_count?: number
  running_vm_count?: number
  temperature_highest_c?: number
  proxmox_version?: string
  pbs_datastore?: string
  pbs_fingerprint?: string
  pbs_username?: string
  pbs_available?: boolean
  pbs_version?: string
  sanoid_installed?: boolean
  sanoid_version?: string
  host_info?: HostInfo
}

export default {
  getNodes() {
    return apiClient.get<Node[]>('/nodes/')
  },

  createNode(data: Record<string, unknown>) {
    return apiClient.post('/nodes/', data)
  },

  updateNode(id: number | string, data: Record<string, unknown>) {
    return apiClient.put(`/nodes/${id}`, data)
  },

  deleteNode(id: number | string) {
    return apiClient.delete(`/nodes/${id}`)
  },

  testNode(id: number | string) {
    return apiClient.post(`/nodes/${id}/test`)
  },

  installSanoid(id: number | string) {
    return apiClient.post(`/nodes/${id}/install-sanoid`)
  },

  updateSanoid(id: number | string) {
    return apiClient.post<{
      success: boolean
      output: string
      sanoid_version?: string | null
      syncoid_version?: string | null
      target_version?: string | null
    }>(`/nodes/${id}/update-sanoid`)
  },

  getStorages(nodeId: number | string) {
    return apiClient.get<{ storages: NodeStorage[] }>(`/nodes/${nodeId}/storages`)
  },

  refreshAllCache() {
    return apiClient.post('/nodes/refresh-cache')
  },

  runDiagnostic(id: number | string) {
    return apiClient.post<{ output: string; error: string; exit_code: number }>(
      `/nodes/${id}/diagnostic`
    )
  },

  getSanoidSyncoidStatus(refresh = false) {
    return apiClient.get<SanoidSyncoidStatusResponse>('/nodes/sanoid-syncoid/status', {
      params: { refresh },
    })
  },

  updateOutdatedSanoidSyncoid() {
    return apiClient.post<{ updated: number; results: Array<{ node_id: number; node_name: string; success: boolean; output: string }> }>(
      '/nodes/sanoid-syncoid/update-outdated'
    )
  },
}

export interface SanoidSyncoidNodeStatus {
  node_id: number
  node_name: string
  hostname: string
  sanoid_installed: boolean
  sanoid_version: string | null
  syncoid_installed: boolean
  syncoid_version: string | null
  update_available: boolean
  status: 'ok' | 'outdated' | 'missing' | 'offline' | 'error' | 'skipped'
  error?: string | null
}

export interface SanoidSyncoidStatusResponse {
  upstream: {
    version: string | null
    tag: string | null
    source_url: string
    release_url: string
    fetched_at: string
    error?: string
  }
  nodes: SanoidSyncoidNodeStatus[]
  summary: {
    total_pve: number
    ok: number
    outdated: number
    missing: number
    offline: number
    errors: number
  }
}

