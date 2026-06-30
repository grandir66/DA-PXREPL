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

export interface Node {
  id: number
  name: string
  hostname: string
  is_online: boolean
  node_type?: string
  storage_type?: string
  cpu?: { cores?: number }
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
  host_info?: Record<string, unknown>
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
    return apiClient.post(`/nodes/${id}/update-sanoid`)
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
}
