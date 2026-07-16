"""Pydantic schemas per sync jobs."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class SyncJobCreate(BaseModel):
    name: Optional[str] = None  # Se non fornito, viene generato automaticamente
    source_node_id: int
    source_dataset: str
    dest_node_id: int
    dest_dataset: str
    dest_subfolder: Optional[str] = None
    
    # Sync method: syncoid (ZFS) or btrfs_send (BTRFS)
    sync_method: str = "syncoid"  # syncoid | btrfs_send
    
    # ZFS/Syncoid options
    recursive: bool = False
    compress: str = "lz4"
    mbuffer_size: str = "128M"
    no_sync_snap: bool = False
    force_delete: bool = False
    extra_args: Optional[str] = None
    
    # BTRFS options
    btrfs_snapshot_dir: Optional[str] = None
    btrfs_dest_snapshot_dir: Optional[str] = None
    btrfs_max_snapshots: int = 5
    btrfs_full_sync: bool = False
    
    # Scheduling
    schedule: Optional[str] = None  # cron format
    schedule_config: Optional[Dict[str, Any]] = None  # struttura "human" (vedi schedule_translator)

    # VM options
    register_vm: bool = False
    vm_id: Optional[int] = None
    dest_vm_id: Optional[int] = None  # ID VM destinazione (se diverso da sorgente)
    vm_type: Optional[str] = None
    vm_name: Optional[str] = None
    dest_vm_name: Optional[str] = None  # Override completo nome VM (precede suffix)
    dest_vm_name_suffix: Optional[str] = None  # Suffisso per nome VM su destinazione (es: -replica)
    dest_bridge: Optional[str] = None  # Bridge dest (sostituisce bridge=... nelle righe netN)
    dest_vlan: Optional[int] = None    # VLAN tag dest (1-4094)
    disk_name: Optional[str] = None  # Nome disco (per BTRFS)
    force_cpu_host: bool = True  # Forza CPU type a 'host' su destinazione per compatibilità

    # Parametri sync_method=pve_native
    dump_dir: Optional[str] = None
    bandwidth_limit_kb: Optional[int] = None
    pve_compress: Optional[str] = None
    cleanup_after: Optional[bool] = None
    replace_existing: Optional[bool] = None
    
    # Notifiche
    notify_mode: str = "daily"  # daily, always, failure, never
    notify_subject: Optional[str] = None
    
    # Retention - snapshot da mantenere sulla destinazione
    keep_snapshots: int = 0  # 0 = solo ultima, N = mantieni ultime N
    
    # Retry
    retry_on_failure: bool = True
    max_retries: int = 3


class SyncJobUpdate(BaseModel):
    name: Optional[str] = None
    source_node_id: Optional[int] = None  # Permetti cambio nodo sorgente
    source_dataset: Optional[str] = None
    dest_node_id: Optional[int] = None  # Permetti cambio nodo destinazione
    dest_dataset: Optional[str] = None
    dest_subfolder: Optional[str] = None
    sync_method: Optional[str] = None
    
    # ZFS options
    recursive: Optional[bool] = None
    compress: Optional[str] = None
    mbuffer_size: Optional[str] = None
    no_sync_snap: Optional[bool] = None
    force_delete: Optional[bool] = None
    extra_args: Optional[str] = None
    
    # BTRFS options
    btrfs_snapshot_dir: Optional[str] = None
    btrfs_dest_snapshot_dir: Optional[str] = None
    btrfs_max_snapshots: Optional[int] = None
    btrfs_full_sync: Optional[bool] = None
    
    schedule: Optional[str] = None
    schedule_config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    register_vm: Optional[bool] = None
    vm_id: Optional[int] = None
    dest_vm_id: Optional[int] = None
    vm_type: Optional[str] = None
    vm_name: Optional[str] = None
    dest_vm_name: Optional[str] = None  # Override completo nome VM
    dest_vm_name_suffix: Optional[str] = None  # Suffisso per nome VM su destinazione
    dest_bridge: Optional[str] = None
    dest_vlan: Optional[int] = None
    disk_name: Optional[str] = None
    force_cpu_host: Optional[bool] = None  # Forza CPU type a 'host' su destinazione
    source_storage: Optional[str] = None  # Storage Proxmox sorgente
    dest_storage: Optional[str] = None  # Storage Proxmox destinazione
    # pve_native
    dump_dir: Optional[str] = None
    bandwidth_limit_kb: Optional[int] = None
    pve_compress: Optional[str] = None
    cleanup_after: Optional[bool] = None
    replace_existing: Optional[bool] = None
    
    # Notifiche
    notify_mode: Optional[str] = None  # daily, always, failure, never
    notify_subject: Optional[str] = None
    
    # Retention
    keep_snapshots: Optional[int] = None  # 0 = solo ultima, N = mantieni ultime N
    
    retry_on_failure: Optional[bool] = None
    max_retries: Optional[int] = None
    retry_delay_minutes: Optional[int] = None


class SyncJobResponse(BaseModel):
    id: int
    name: str
    sync_method: Optional[str] = "syncoid"
    source_node_id: int
    source_dataset: str
    dest_node_id: int
    dest_dataset: str
    dest_subfolder: Optional[str] = None
    
    # ZFS options
    recursive: bool
    compress: Optional[str]
    mbuffer_size: Optional[str]
    no_sync_snap: bool
    force_delete: bool
    extra_args: Optional[str]
    
    # BTRFS options
    btrfs_snapshot_dir: Optional[str] = None
    btrfs_dest_snapshot_dir: Optional[str] = None
    btrfs_max_snapshots: Optional[int] = 5
    btrfs_full_sync: Optional[bool] = False

    # pve_native options
    dump_dir: Optional[str] = None
    bandwidth_limit_kb: Optional[int] = None
    pve_compress: Optional[str] = None
    cleanup_after: Optional[bool] = None
    replace_existing: Optional[bool] = None
    
    schedule: Optional[str]
    schedule_config: Optional[Dict[str, Any]] = None
    is_active: bool
    register_vm: bool
    vm_id: Optional[int]
    dest_vm_id: Optional[int]
    vm_type: Optional[str]
    vm_name: Optional[str]
    dest_vm_name: Optional[str] = None
    dest_vm_name_suffix: Optional[str] = None
    dest_bridge: Optional[str] = None
    dest_vlan: Optional[int] = None
    force_cpu_host: Optional[bool] = True
    vm_group_id: Optional[str]
    disk_name: Optional[str]
    source_storage: Optional[str] = None
    dest_storage: Optional[str] = None
    
    # Notifiche
    notify_mode: Optional[str] = "daily"  # daily, always, failure, never
    notify_subject: Optional[str] = None
    
    # Retention
    keep_snapshots: Optional[int] = 0  # 0 = solo ultima, N = mantieni ultime N
    
    retry_on_failure: bool
    max_retries: int
    last_run: Optional[datetime]
    last_status: Optional[str]
    current_status: Optional[str] = None
    last_duration: Optional[int]
    last_transferred: Optional[str]
    last_sync_type: Optional[str] = None  # full/incremental per BTRFS
    run_count: int
    error_count: int
    consecutive_failures: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class SyncJobResponseWithNodes(SyncJobResponse):
    source_node_name: Optional[str] = None
    dest_node_name: Optional[str] = None
    is_replicating: bool = False
    transfer_progress: Optional[Dict[str, Any]] = None
    group_transfer_progress: Optional[Dict[str, Any]] = None
    group_disks_done: Optional[int] = None
    group_disks_total: Optional[int] = None
    group_is_running: bool = False


class VMReplicaCreate(BaseModel):
    """Schema per creare replica completa di una VM (ZFS / BTRFS / PVE_NATIVE)"""
    vm_id: int
    vm_type: str = "qemu"
    vm_name: Optional[str] = None
    source_node_id: int
    dest_node_id: int
    # Per ZFS/BTRFS: pool/subfolder; per pve_native ignorati
    dest_pool: Optional[str] = None
    dest_subfolder: str = "replica"
    dest_storage: Optional[str] = None  # Nome storage Proxmox destinazione
    dest_vm_id: Optional[int] = None
    dest_vm_name: Optional[str] = None
    dest_vm_name_suffix: Optional[str] = None
    dest_bridge: Optional[str] = None
    dest_vlan: Optional[int] = None
    force_cpu_host: bool = True
    schedule: Optional[str] = None
    schedule_config: Optional[Dict[str, Any]] = None
    compress: str = "lz4"
    recursive: bool = False
    register_vm: bool = True
    keep_snapshots: int = 0  # 0 = solo ultima, N = mantieni ultime N snapshot
    disks: List[dict] = []  # Lista dischi da replicare (se vuota, replica tutti)
    # pve_native specific
    dump_dir: Optional[str] = None
    bandwidth_limit_kb: Optional[int] = None
    pve_compress: Optional[str] = None
    cleanup_after: Optional[bool] = None
    replace_existing: Optional[bool] = None
    
    # BTRFS options
    sync_method: str = "syncoid"  # syncoid | btrfs_send
    btrfs_mount: Optional[str] = None  # Mount point BTRFS sorgente
    btrfs_snapshot_dir: Optional[str] = None  # Directory snapshot sorgente
    btrfs_dest_snapshot_dir: Optional[str] = None  # Directory snapshot destinazione
    btrfs_max_snapshots: int = 5


class SnapshotInfo(BaseModel):
    """Info su una snapshot"""
    name: str  # Nome completo (dataset@snapshot)
    snapshot_name: str  # Solo nome snapshot
    creation: datetime
    used: Optional[str] = None  # Spazio usato
    referenced: Optional[str] = None  # Spazio referenziato
