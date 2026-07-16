import apiClient from './api'

export interface ClusterEntryInfo {
  entry_node_id: number | null
  entry_node_name?: string
  cluster_detected: boolean
  cluster_name?: string | null
  cluster_node_count?: number
  quorum?: boolean
  cluster_members?: Array<{ name: string; node_id?: string; votes?: string; status?: string }>
  registered_cluster_members?: Array<{ id: number; name: string; hostname: string }>
  registered_standalone_nodes?: Array<{ id: number; name: string; hostname: string }>
}

export interface HaActionResponse {
  success: boolean
  message: string
}

export interface HAResourcePayload {
  vmid: number
  vm_type: string
  group?: string | null
  state?: string
  max_restart?: number
  max_relocate?: number
}

export interface HAGroupPayload {
  name: string
  nodes: string[]
  restricted?: boolean
  nofailback?: boolean
}

export default {
  getClusterEntry() {
    return apiClient.get<ClusterEntryInfo>('/ha/cluster-entry')
  },

  getCompleteData(nodeId: number) {
    return apiClient.get(`/ha/node/${nodeId}/complete-data`)
  },

  getMonitor(nodeId: number) {
    return apiClient.get(`/ha/node/${nodeId}/monitor`)
  },

  getTopology(nodeId: number) {
    return apiClient.get(`/ha/node/${nodeId}/topology`)
  },

  addClusterNode(nodeId: number, newNodeIp: string) {
    return apiClient.post<HaActionResponse>(`/ha/node/${nodeId}/cluster/nodes`, {
      new_node_ip: newNodeIp,
    })
  },

  removeClusterNode(nodeId: number, nodeName: string) {
    return apiClient.delete<HaActionResponse>(`/ha/node/${nodeId}/cluster/nodes/${nodeName}`)
  },

  cleanClusterNode(nodeId: number, nodeName: string) {
    return apiClient.post(`/ha/node/${nodeId}/cluster/nodes/${nodeName}/clean`)
  },

  removeResource(nodeId: number, vmid: number | string, vmType: string) {
    return apiClient.delete<HaActionResponse>(`/ha/node/${nodeId}/resources/${vmid}`, {
      params: { vm_type: vmType },
    })
  },

  addResource(nodeId: number, data: HAResourcePayload) {
    return apiClient.post<HaActionResponse>(`/ha/node/${nodeId}/resources`, data)
  },

  deleteGroup(nodeId: number, groupName: string) {
    return apiClient.delete<HaActionResponse>(`/ha/node/${nodeId}/groups/${groupName}`)
  },

  createGroup(nodeId: number, data: HAGroupPayload) {
    return apiClient.post<HaActionResponse>(`/ha/node/${nodeId}/groups`, data)
  },
}
