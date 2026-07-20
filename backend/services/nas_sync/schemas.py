"""Schemi Pydantic Repliche dati v2."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class NasSyncJobCreate(BaseModel):
    name: str
    description: Optional[str] = None
    source_endpoint_id: int
    dest_endpoint_id: int
    source_paths: list[str] = Field(min_length=1)
    dest_base_path: str
    sync_method: str = "auto"
    delete_on_dest: bool = False
    rclone_size_only: bool = False
    exclude_presets: list[str] = Field(default_factory=lambda: ["nas_snapshots", "system_files"])
    exclude_patterns: list[str] = Field(default_factory=list)
    bandwidth_limit_kb: Optional[int] = None
    snapshot_policy_hint: Optional[dict[str, Any]] = None
    schedule: Optional[str] = None
    schedule_config: Optional[dict[str, Any]] = None
    is_active: bool = True
    notify_mode: str = "daily"
    notify_subject: Optional[str] = None


class NasSyncJobUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    source_paths: Optional[list[str]] = None
    dest_base_path: Optional[str] = None
    sync_method: Optional[str] = None
    delete_on_dest: Optional[bool] = None
    rclone_size_only: Optional[bool] = None
    exclude_presets: Optional[list[str]] = None
    exclude_patterns: Optional[list[str]] = None
    bandwidth_limit_kb: Optional[int] = None
    snapshot_policy_hint: Optional[dict[str, Any]] = None
    schedule: Optional[str] = None
    schedule_config: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None
    notify_mode: Optional[str] = None
    notify_subject: Optional[str] = None


class NasSyncJobOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    source_endpoint_id: int
    dest_endpoint_id: int
    source_paths: list[str]
    dest_base_path: str
    sync_method: str
    resolved_engine: Optional[str] = None
    engine_reason: Optional[str] = None
    delete_on_dest: bool
    rclone_size_only: bool = False
    exclude_presets: list[str]
    exclude_patterns: list[str]
    bandwidth_limit_kb: Optional[int] = None
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
    catalog_bytes_est: Optional[int] = None
    catalog_files_est: Optional[int] = None
    catalog_updated_at: Optional[str] = None
    catalog_folder_count: Optional[int] = None
    catalog_has_du: Optional[bool] = None

    class Config:
        from_attributes = True
