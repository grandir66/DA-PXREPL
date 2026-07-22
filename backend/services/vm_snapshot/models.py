"""Modello DB job Snapshot VM (tabella dedicata, distinta da VMSnapshotConfig/Sanoid)."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    JSON,
    String,
    Text,
)

from database import Base


class VmSnapshotJob(Base):
    """Job snapshot Proxmox multi-VM: label+keep (stile cv4pve-autosnap), selettori dinamici."""

    __tablename__ = "vm_snapshot_jobs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    label = Column(String(20), nullable=False)
    keep = Column(Integer, nullable=False, default=7)
    include_vmstate = Column(Boolean, default=False)

    # Selezione VM: checkbox statiche + selettori dinamici risolti a runtime.
    # targets: [{"node_id": 1, "vmid": 100, "vm_type": "qemu", "name": "web01"}]
    # selectors: {"tags": [], "node_ids": [], "exclude_vmids": []}
    targets = Column(JSON, nullable=False, default=list)
    selectors = Column(JSON, nullable=False, default=dict)

    schedule = Column(String(100), nullable=True)
    schedule_config = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True)
    current_status = Column(String(20), nullable=True)
    last_run_at = Column(DateTime, nullable=True)
    last_run_status = Column(String(20), nullable=True)  # success | partial | failed
    last_run_duration_sec = Column(Integer, nullable=True)
    next_run_at = Column(DateTime, nullable=True)
    notify_mode = Column(String(20), default="failure")
    notify_subject = Column(String(200), nullable=True)
    run_state = Column(JSON, nullable=True, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
