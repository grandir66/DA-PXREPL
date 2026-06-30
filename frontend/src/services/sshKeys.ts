import apiClient from './api'

export interface SSHKeyInfo {
  exists: boolean
  public_key?: string
  key_type?: string
  fingerprint?: string
  comment?: string
}

export interface SSHTestResult {
  node_id?: number
  node_name?: string
  host: string
  success: boolean
  message: string
}

export default {
  getInfo() {
    return apiClient.get<SSHKeyInfo>('/ssh-keys/info')
  },

  generate(overwrite = false) {
    return apiClient.post('/ssh-keys/generate', { overwrite })
  },

  distribute(nodeIds?: number[]) {
    return apiClient.post('/ssh-keys/distribute', { node_ids: nodeIds ?? null })
  },

  testConnections(nodeIds?: number[]) {
    return apiClient.post<SSHTestResult[]>('/ssh-keys/test', { node_ids: nodeIds ?? null })
  },

  setupMesh() {
    return apiClient.post('/ssh-keys/setup-mesh', {})
  },
}
