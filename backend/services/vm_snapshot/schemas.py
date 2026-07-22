"""Schemi Pydantic modulo Snapshot VM."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from services.vm_snapshot.naming import LABEL_RE


class TargetRef(BaseModel):
    node_id: int
    vmid: int
    vm_type: str = "qemu"
    name: Optional[str] = None
    node_name: Optional[str] = None


class Selectors(BaseModel):
    tags: list[str] = Field(default_factory=list)
    node_ids: list[int] = Field(default_factory=list)
    exclude_vmids: list[int] = Field(default_factory=list)


def _validate_label(value: str) -> str:
    if not LABEL_RE.fullmatch(value or ""):
        raise ValueError(
            "Label non valido: minuscolo, inizia con lettera, solo lettere/cifre, 2-16 caratteri"
        )
    return value


class VmSnapshotJobCreate(BaseModel):
    name: str
    description: Optional[str] = None
    label: str
    keep: int = Field(default=7, ge=1, le=100)
    include_vmstate: bool = False
    targets: list[TargetRef] = Field(default_factory=list)
    selectors: Selectors = Field(default_factory=Selectors)
    schedule: Optional[str] = None
    schedule_config: Optional[dict[str, Any]] = None
    is_active: bool = True
    notify_mode: str = "failure"
    notify_subject: Optional[str] = None

    @field_validator("label")
    @classmethod
    def check_label(cls, value: str) -> str:
        return _validate_label(value)


class VmSnapshotJobUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    label: Optional[str] = None
    keep: Optional[int] = Field(default=None, ge=1, le=100)
    include_vmstate: Optional[bool] = None
    targets: Optional[list[TargetRef]] = None
    selectors: Optional[Selectors] = None
    schedule: Optional[str] = None
    schedule_config: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None
    notify_mode: Optional[str] = None
    notify_subject: Optional[str] = None

    @field_validator("label")
    @classmethod
    def check_label(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        return _validate_label(value)


class VmSnapshotJobOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    label: str
    keep: int
    include_vmstate: bool
    targets: list[dict[str, Any]]
    selectors: dict[str, Any]
    schedule: Optional[str] = None
    schedule_config: Optional[dict[str, Any]] = None
    is_active: bool
    current_status: Optional[str] = None
    last_run_at: Optional[datetime] = None
    last_run_status: Optional[str] = None
    last_run_duration_sec: Optional[int] = None
    next_run_at: Optional[datetime] = None
    notify_mode: Optional[str] = None
    notify_subject: Optional[str] = None
    run_state: Optional[dict[str, Any]] = None
    last_run_error: Optional[str] = None
    label_conflicts: list[str] = Field(default_factory=list)

    class Config:
        from_attributes = True
