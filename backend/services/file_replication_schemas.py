"""Schemi Pydantic per replica file."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class SnapshotPolicyHint(BaseModel):
    schedule: str = "0 3 * * *"
    protection: str = "prohibit_recycle_and_delete_until_expired"
    retention_mode: str = "smart_versioning"
    max_snapshots: int = 10
    expiration_days: int = 30
    only_if_modified: bool = True


class FileEndpointCreate(BaseModel):
    name: str
    endpoint_type: str
    role: str = "source"
    host: str
    port: Optional[int] = None
    protocol: Optional[str] = None
    username: str
    password: Optional[str] = None
    ssh_key_path: Optional[str] = None
    domain: Optional[str] = None
    base_path: Optional[str] = None
    extra_config: Optional[dict[str, Any]] = None


class FileEndpointUpdate(BaseModel):
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    protocol: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    ssh_key_path: Optional[str] = None
    domain: Optional[str] = None
    base_path: Optional[str] = None
    extra_config: Optional[dict[str, Any]] = None
    role: Optional[str] = None


class FileEndpointOut(BaseModel):
    id: int
    name: str
    endpoint_type: str
    role: str
    host: str
    port: int
    protocol: str
    username: str
    ssh_key_path: Optional[str] = None
    domain: Optional[str] = None
    base_path: Optional[str] = None
    extra_config: Optional[dict[str, Any]] = None
    last_test_at: Optional[datetime] = None
    last_test_status: Optional[str] = None
    last_test_message: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class BrowseEntryOut(BaseModel):
    name: str
    path: str
    is_dir: bool
    is_excluded: bool = False
    selectable: bool = True
    size: Optional[int] = None


class ConnectionTestResult(BaseModel):
    success: bool
    message: str
    details: Optional[dict[str, Any]] = None


class FileReplicationJobCreate(BaseModel):
    name: str
    description: Optional[str] = None
    source_endpoint_id: int
    dest_endpoint_id: int
    source_paths: list[str] = Field(min_length=1)
    dest_staging_path: str
    sync_method: str = "rsync_ssh"
    delete_on_dest: bool = True
    on_source_delete: str = "keep"
    exclude_presets: list[str] = Field(default_factory=lambda: ["nas_snapshots", "system_files"])
    exclude_patterns: list[str] = Field(default_factory=list)
    bandwidth_limit_kb: Optional[int] = None
    extra_rsync_args: Optional[str] = None
    snapshot_policy_hint: Optional[SnapshotPolicyHint] = None
    schedule: Optional[str] = None
    schedule_config: Optional[dict[str, Any]] = None
    is_active: bool = True
    notify_mode: str = "daily"
    notify_subject: Optional[str] = None


class FileReplicationJobUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    source_paths: Optional[list[str]] = None
    dest_staging_path: Optional[str] = None
    sync_method: Optional[str] = None
    delete_on_dest: Optional[bool] = None
    on_source_delete: Optional[str] = None
    exclude_presets: Optional[list[str]] = None
    exclude_patterns: Optional[list[str]] = None
    bandwidth_limit_kb: Optional[int] = None
    extra_rsync_args: Optional[str] = None
    snapshot_policy_hint: Optional[SnapshotPolicyHint] = None
    schedule: Optional[str] = None
    schedule_config: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None
    notify_mode: Optional[str] = None
    notify_subject: Optional[str] = None


class FileReplicationJobOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    source_endpoint_id: int
    dest_endpoint_id: int
    source_paths: list[str]
    dest_staging_path: str
    sync_method: str
    delete_on_dest: bool
    on_source_delete: str
    exclude_presets: list[str]
    exclude_patterns: list[str]
    bandwidth_limit_kb: Optional[int] = None
    immutability_strategy: str
    snapshot_policy_hint: Optional[dict[str, Any]] = None
    schedule: Optional[str] = None
    schedule_config: Optional[dict[str, Any]] = None
    is_active: bool
    current_status: Optional[str] = None
    last_run_at: Optional[datetime] = None
    last_run_status: Optional[str] = None
    last_run_duration_sec: Optional[int] = None
    last_bytes_transferred: Optional[int] = None
    last_files_transferred: Optional[int] = None
    next_run_at: Optional[datetime] = None
    notify_mode: Optional[str] = None
    notify_subject: Optional[str] = None
    source_endpoint_name: Optional[str] = None
    dest_endpoint_name: Optional[str] = None
    last_run_error: Optional[str] = None

    class Config:
        from_attributes = True
