import apiClient from './api'

export interface ProxmoxCluster {
  id: number
  name: string
  hosts: string
  api_user?: string
  verify_ssl: boolean
  is_default: boolean
  is_initialized: boolean
  cluster_name?: string
  node_count?: number
  quorum_ok?: boolean
}

export interface ClusterCreatePayload {
  name: string
  hosts: string
  api_user?: string
  api_password?: string
  verify_ssl?: boolean
  is_default?: boolean
}

export interface ClusterUpdatePayload extends Partial<ClusterCreatePayload> {}

export default {
  list() {
    return apiClient.get<ProxmoxCluster[]>('/clusters')
  },

  create(data: ClusterCreatePayload) {
    return apiClient.post<ProxmoxCluster>('/clusters', data)
  },

  update(id: number, data: ClusterUpdatePayload) {
    return apiClient.put<ProxmoxCluster>(`/clusters/${id}`, data)
  },

  delete(id: number) {
    return apiClient.delete(`/clusters/${id}`)
  },
}
