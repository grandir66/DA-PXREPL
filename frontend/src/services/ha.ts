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

export default {
  getClusterEntry() {
    return apiClient.get<ClusterEntryInfo>('/ha/cluster-entry')
  },
}
