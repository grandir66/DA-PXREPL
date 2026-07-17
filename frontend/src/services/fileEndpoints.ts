import apiClient from './api'

export interface FileEndpoint {
  id: number
  name: string
  endpoint_type: 'synology' | 'qnap' | 'linux' | 'windows'
  role: string
  host: string
  port: number
  protocol: string
  username: string
  ssh_key_path?: string | null
  domain?: string | null
  base_path?: string | null
  extra_config?: Record<string, unknown> | null
  last_test_at?: string | null
  last_test_status?: string | null
  last_test_message?: string | null
}

export interface BrowseEntry {
  name: string
  path: string
  is_dir: boolean
  is_excluded: boolean
  selectable: boolean
  size?: number | null
}

export interface ConnectionTestResult {
  success: boolean
  message: string
  details?: Record<string, unknown>
}

export const fileEndpointsApi = {
  list: (role?: string) =>
    apiClient.get<FileEndpoint[]>('/file-endpoints', { params: role ? { role } : {} }),
  get: (id: number) => apiClient.get<FileEndpoint>(`/file-endpoints/${id}`),
  create: (data: Record<string, unknown>) => apiClient.post<FileEndpoint>('/file-endpoints', data),
  update: (id: number, data: Record<string, unknown>) =>
    apiClient.put<FileEndpoint>(`/file-endpoints/${id}`, data),
  delete: (id: number) => apiClient.delete(`/file-endpoints/${id}`),
  test: (id: number) => apiClient.post<ConnectionTestResult>(`/file-endpoints/${id}/test`),
  browse: (id: number, path: string) =>
    apiClient.get<BrowseEntry[]>(`/file-endpoints/${id}/browse`, { params: { path } }),
}
