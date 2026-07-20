"""Modello DB job Repliche dati v2 (tabella separata dal modulo file_replication)."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from database import Base


class NasSyncJob(Base):
    """Job replica dati v2: engine direct_rsync o rclone_smb, risolto da sync_method."""

    __tablename__ = "nas_sync_jobs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    source_endpoint_id = Column(Integer, ForeignKey("file_endpoints.id"), nullable=False)
    dest_endpoint_id = Column(Integer, ForeignKey("file_endpoints.id"), nullable=False)
    source_paths = Column(JSON, nullable=False, default=list)
    dest_base_path = Column(String(500), nullable=False)
    sync_method = Column(String(20), nullable=False, default="auto")
    resolved_engine = Column(String(20), nullable=True)
    delete_on_dest = Column(Boolean, default=False)
    rclone_size_only = Column(Boolean, default=False)
    exclude_presets = Column(JSON, nullable=False, default=list)
    exclude_patterns = Column(JSON, nullable=False, default=list)
    bandwidth_limit_kb = Column(Integer, nullable=True)
    snapshot_policy_hint = Column(JSON, nullable=True, default=dict)
    schedule = Column(String(100), nullable=True)
    schedule_config = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True)
    current_status = Column(String(20), nullable=True)
    last_run_at = Column(DateTime, nullable=True)
    last_run_status = Column(String(20), nullable=True)
    last_run_duration_sec = Column(Integer, nullable=True)
    last_bytes_transferred = Column(BigInteger, nullable=True)
    last_files_transferred = Column(Integer, nullable=True)
    next_run_at = Column(DateTime, nullable=True)
    notify_mode = Column(String(20), default="daily")
    notify_subject = Column(String(200), nullable=True)
    run_state = Column(JSON, nullable=True, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    source_endpoint = relationship("FileEndpoint", foreign_keys=[source_endpoint_id])
    dest_endpoint = relationship("FileEndpoint", foreign_keys=[dest_endpoint_id])
