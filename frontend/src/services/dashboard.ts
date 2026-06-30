import apiClient from './api'

export interface JobStats {
  replica_zfs: number
  replica_btrfs: number
  backup_pbs: number
  replica_pbs: number
  migration: number
  total: number
}

export interface NodeMetrics {
  node_id: string
  node_name: string
  cpu: {
    usage_percent: number
    load_1min: number
    load_5min: number
    load_15min: number
  }
  memory: {
    used_gb: number
    total_gb: number
    usage_percent: number
  }
  network: Record<string, unknown>
  disk_io: Record<string, unknown>
}

export default {
  getJobStats() {
    return apiClient.get<JobStats>('/dashboard/job-stats')
  },

  getNodesMetrics() {
    return apiClient.get<NodeMetrics[]>('/dashboard/nodes-metrics')
  },
}
