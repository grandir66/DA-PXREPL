/**
 * Replication store — single source of truth per il modulo unificato di
 * repliche/backup. Tiene cache di nodi, VM e jobs (mergeati su tutti i
 * tipi: syncoid, backup PBS, recovery PBS) per consentire una vista
 * "VM-centric" agli schermi che la usano.
 */
import { defineStore } from 'pinia'
import nodesService, { type Node } from '../services/nodes'
import vmsService, { type VM } from '../services/vms'
import syncJobsService, { type SyncJob } from '../services/syncJobs'
import backupJobsService, { type BackupJob } from '../services/backupJobs'
import recoveryJobsService, { type RecoveryJob } from '../services/recoveryJobs'
import type { ScheduleConfig } from '../services/schedule'

export type JobKind = 'syncoid' | 'backup_pbs' | 'recovery_pbs'

export interface UnifiedJob {
  kind: JobKind
  id: number | string
  name: string
  // VM info (può essere assente per job legacy non vm-centric)
  vm_id?: number | string
  vm_name?: string
  vm_type?: string
  vm_group_id?: string | null
  // Endpoints
  source_node_id?: number
  source_node_name?: string
  dest_node_id?: number
  dest_node_name?: string
  pbs_node_id?: number
  pbs_node_name?: string
  pbs_datastore?: string
  source_storage?: string
  dest_storage?: string
  source_dataset?: string
  dest_dataset?: string
  // Schedule
  schedule?: string | null
  schedule_config?: ScheduleConfig | null
  // Stato
  is_active?: boolean
  last_run?: string | null
  last_status?: string | null
  current_status?: string | null
  // Riferimento al payload originario (necessario per edit di campi
  // specifici del tipo di job non tracciati nel modello unificato)
  raw: any
}

interface State {
  nodes: Node[]
  vms: VM[]
  jobs: UnifiedJob[]
  loadingNodes: boolean
  loadingVMs: boolean
  loadingJobs: boolean
  error: string | null
  lastFetchedAt: number | null
}

function n(v: any) {
  return v === undefined || v === null || v === '' ? null : v
}

function unifySync(j: any): UnifiedJob {
  return {
    kind: 'syncoid',
    id: j.id,
    name: j.name || j.job_name || `sync-${j.id}`,
    vm_id: j.vm_id,
    vm_name: j.vm_name,
    vm_type: j.vm_type,
    vm_group_id: j.vm_group_id,
    source_node_id: j.source_node_id,
    source_node_name: j.source_node_name,
    dest_node_id: j.dest_node_id,
    dest_node_name: j.dest_node_name,
    source_storage: j.source_storage,
    dest_storage: j.dest_storage,
    source_dataset: j.source_dataset,
    dest_dataset: j.dest_dataset,
    schedule: n(j.schedule),
    schedule_config: j.schedule_config || null,
    is_active: j.is_active ?? j.enabled ?? true,
    last_run: n(j.last_run),
    last_status: n(j.last_status),
    current_status: n(j.current_status),
    raw: j,
  }
}

function unifyBackup(j: any): UnifiedJob {
  return {
    kind: 'backup_pbs',
    id: j.id,
    name: j.name || j.job_name || `backup-${j.id}`,
    vm_id: j.vm_id,
    vm_name: j.vm_name,
    vm_type: j.vm_type,
    source_node_id: j.source_node_id,
    source_node_name: j.source_node_name,
    pbs_node_id: j.pbs_node_id,
    pbs_node_name: j.pbs_node_name,
    pbs_datastore: j.pbs_datastore,
    schedule: n(j.schedule),
    schedule_config: j.schedule_config || null,
    is_active: j.is_active ?? true,
    last_run: n(j.last_run),
    last_status: n(j.last_status),
    current_status: n(j.current_status),
    raw: j,
  }
}

function unifyRecovery(j: any): UnifiedJob {
  return {
    kind: 'recovery_pbs',
    id: j.id,
    name: j.name || `recovery-${j.id}`,
    vm_id: j.vm_id,
    vm_name: j.vm_name,
    vm_type: j.vm_type,
    source_node_id: j.source_node_id,
    source_node_name: j.source_node_name,
    pbs_node_id: j.pbs_node_id,
    pbs_node_name: j.pbs_node_name,
    pbs_datastore: j.pbs_datastore,
    dest_node_id: j.dest_node_id,
    dest_node_name: j.dest_node_name,
    dest_storage: j.dest_storage,
    schedule: n(j.schedule),
    schedule_config: j.schedule_config || null,
    is_active: j.is_active ?? true,
    last_run: n(j.last_run),
    last_status: n(j.last_status),
    current_status: n(j.current_status),
    raw: j,
  }
}

export const useReplicationStore = defineStore('replication', {
  state: (): State => ({
    nodes: [],
    vms: [],
    jobs: [],
    loadingNodes: false,
    loadingVMs: false,
    loadingJobs: false,
    error: null,
    lastFetchedAt: null,
  }),
  getters: {
    pveNodes(state): Node[] {
      return state.nodes.filter(nd => (nd.node_type || 'pve') === 'pve')
    },
    pbsNodes(state): Node[] {
      return state.nodes.filter(nd => nd.node_type === 'pbs')
    },
    nodeById(state) {
      const m = new Map<number, Node>()
      for (const nd of state.nodes) m.set(nd.id, nd)
      return (id: number | string | undefined) =>
        id == null ? null : (m.get(Number(id)) || null)
    },
    vmsByNode(state) {
      const m = new Map<number, VM[]>()
      for (const v of state.vms) {
        const k = Number(v.node_id || 0)
        if (!m.has(k)) m.set(k, [])
        m.get(k)!.push(v)
      }
      return (nodeId: number | string | undefined) =>
        nodeId == null ? [] : (m.get(Number(nodeId)) || [])
    },
    /**
     * Ritorna la lista dei job raggruppata per VM (utile per la lista
     * "enterprise" dove ogni riga rappresenta una VM e i singoli job
     * sono righe figlie). I job senza VM finiscono in un gruppo
     * "non-vm".
     */
    jobsByVM(state) {
      type Group = {
        key: string
        vm_id?: number | string
        vm_name?: string
        vm_type?: string
        jobs: UnifiedJob[]
      }
      const out: Group[] = []
      const idx = new Map<string, Group>()
      for (const j of state.jobs) {
        const key =
          j.vm_id != null
            ? `vm:${j.vm_id}:${j.kind === 'syncoid' && j.vm_group_id ? j.vm_group_id : 'all'}`
            : `solo:${j.kind}:${j.id}`
        let g = idx.get(key)
        if (!g) {
          g = {
            key,
            vm_id: j.vm_id,
            vm_name: j.vm_name,
            vm_type: j.vm_type,
            jobs: [],
          }
          idx.set(key, g)
          out.push(g)
        }
        g.jobs.push(j)
      }
      return out
    },
  },
  actions: {
    async fetchNodes(force = false) {
      if (this.loadingNodes) return
      if (!force && this.nodes.length > 0) return
      this.loadingNodes = true
      try {
        const r = await nodesService.getNodes()
        this.nodes = r.data
      } finally {
        this.loadingNodes = false
      }
    },
    async fetchVMs(force = false) {
      if (this.loadingVMs) return
      this.loadingVMs = true
      try {
        const r = await vmsService.getVMs(force)
        this.vms = r.data
      } finally {
        this.loadingVMs = false
      }
    },
    async fetchJobs() {
      this.loadingJobs = true
      try {
        const [sync, backup, recovery] = await Promise.all([
          syncJobsService.getJobs().catch(() => ({ data: [] as any[] })),
          backupJobsService.getJobs().catch(() => ({ data: [] as any[] })),
          recoveryJobsService.getJobs().catch(() => ({ data: [] as any[] })),
        ])
        const merged: UnifiedJob[] = []
        for (const j of sync.data as any[]) merged.push(unifySync(j))
        for (const j of backup.data as any[]) merged.push(unifyBackup(j))
        for (const j of recovery.data as any[]) merged.push(unifyRecovery(j))
        this.jobs = merged
        this.lastFetchedAt = Date.now()
      } finally {
        this.loadingJobs = false
      }
    },
    async fetchAll(force = false) {
      this.error = null
      try {
        await Promise.all([
          this.fetchNodes(force),
          this.fetchVMs(force),
          this.fetchJobs(),
        ])
      } catch (e: any) {
        this.error = e?.message || String(e)
      }
    },
  },
})
