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

export interface ReplicationHealthJob {
  id: number
  name: string
  type: string
  sync_method?: string | null
  vm_id?: number | null
  vm_name?: string | null
  vm_group_id?: string | null
  disk_name?: string | null
  schedule: string
  last_run?: string | null
  last_status?: string | null
  next_run?: string | null
  missed_slots?: number
  overdue: boolean
  expected_slot?: string | null
  hours_since_last_run?: number | null
  reason?: string | null
}

export interface ReplicationHealthGroup {
  key: string
  vm_group_id?: string | null
  vm_id?: number | null
  vm_name?: string | null
  schedule?: string | null
  job_count: number
  overdue: boolean
  missed_slots: number
  hours_since_last_run?: number | null
  last_run?: string | null
  next_run?: string | null
  last_status?: string | null
  jobs: Array<{ id: number; name: string; disk_name?: string | null }>
}

export interface ReplicationHealth {
  overdue_count: number
  overdue_group_count: number
  running_count: number
  healthy_count: number
  total_scheduled: number
  checked_at: string
  jobs: ReplicationHealthJob[]
  groups: ReplicationHealthGroup[]
  overdue_groups: ReplicationHealthGroup[]
  running_jobs: ReplicationHealthJob[]
}

export default {
  getJobStats() {
    return apiClient.get<JobStats>('/dashboard/job-stats')
  },

  getNodesMetrics() {
    return apiClient.get<NodeMetrics[]>('/dashboard/nodes-metrics')
  },

  getReplicationHealth() {
    return apiClient.get<ReplicationHealth>('/dashboard/replication-health')
  },
}
