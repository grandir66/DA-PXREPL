"""Router CRUD endpoint replica file + browse + test."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import FileEndpoint, FileEndpointRole, FileEndpointType, FileReplicationJob, get_db
from routers.auth import User, get_current_user, require_operator
from services.file_replication.browser_factory import default_port, default_protocol, get_browser
from services.file_replication.endpoint_crypto import encrypt_password
from services.file_replication.path_utils import sanitize_path
from services.file_replication_schemas import (
    BrowseEntryOut,
    ConnectionTestResult,
    FileEndpointCreate,
    FileEndpointOut,
    FileEndpointUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _endpoint_out(ep: FileEndpoint) -> FileEndpointOut:
    return FileEndpointOut(
        id=ep.id,
        name=ep.name,
        endpoint_type=ep.endpoint_type.value if hasattr(ep.endpoint_type, "value") else str(ep.endpoint_type),
        role=ep.role.value if hasattr(ep.role, "value") else str(ep.role),
        host=ep.host,
        port=ep.port,
        protocol=ep.protocol,
        username=ep.username,
        ssh_key_path=ep.ssh_key_path,
        domain=ep.domain,
        base_path=ep.base_path,
        extra_config=ep.extra_config,
        last_test_at=ep.last_test_at,
        last_test_status=ep.last_test_status,
        last_test_message=ep.last_test_message,
        created_at=ep.created_at,
        updated_at=ep.updated_at,
    )


def _parse_endpoint_type(value: str) -> FileEndpointType:
    try:
        return FileEndpointType(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"endpoint_type invalido: {value}") from exc


def _parse_role(value: str) -> FileEndpointRole:
    try:
        return FileEndpointRole(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"role invalido: {value}") from exc


@router.get("", response_model=list[FileEndpointOut])
def list_endpoints(
    role: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = db.query(FileEndpoint).order_by(FileEndpoint.name)
    if role:
        q = q.filter(FileEndpoint.role == _parse_role(role))
    return [_endpoint_out(ep) for ep in q.all()]


@router.post("", response_model=FileEndpointOut)
def create_endpoint(
    body: FileEndpointCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_operator),
):
    et = _parse_endpoint_type(body.endpoint_type)
    ep = FileEndpoint(
        name=body.name,
        endpoint_type=et,
        role=_parse_role(body.role),
        host=body.host,
        port=body.port or default_port(et),
        protocol=body.protocol or default_protocol(et),
        username=body.username,
        password_enc=encrypt_password(body.password) if body.password else None,
        ssh_key_path=body.ssh_key_path,
        domain=body.domain,
        base_path=body.base_path,
        extra_config=body.extra_config or {},
    )
    db.add(ep)
    db.commit()
    db.refresh(ep)
    return _endpoint_out(ep)


@router.get("/{endpoint_id}", response_model=FileEndpointOut)
def get_endpoint(
    endpoint_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    ep = db.query(FileEndpoint).filter(FileEndpoint.id == endpoint_id).first()
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint non trovato")
    return _endpoint_out(ep)


@router.put("/{endpoint_id}", response_model=FileEndpointOut)
def update_endpoint(
    endpoint_id: int,
    body: FileEndpointUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_operator),
):
    ep = db.query(FileEndpoint).filter(FileEndpoint.id == endpoint_id).first()
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint non trovato")

    data = body.model_dump(exclude_unset=True)
    if "password" in data:
        pwd = data.pop("password")
        if pwd:
            ep.password_enc = encrypt_password(pwd)
    if "role" in data and data["role"] is not None:
        ep.role = _parse_role(data.pop("role"))
    for key, value in data.items():
        setattr(ep, key, value)
    ep.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(ep)
    return _endpoint_out(ep)


@router.delete("/{endpoint_id}")
def delete_endpoint(
    endpoint_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_operator),
):
    ep = db.query(FileEndpoint).filter(FileEndpoint.id == endpoint_id).first()
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint non trovato")
    in_use = db.query(FileReplicationJob).filter(
        (FileReplicationJob.source_endpoint_id == endpoint_id)
        | (FileReplicationJob.dest_endpoint_id == endpoint_id)
    ).count()
    if in_use:
        raise HTTPException(status_code=409, detail="Endpoint usato da job replica file")
    db.delete(ep)
    db.commit()
    return {"ok": True}


@router.post("/{endpoint_id}/test", response_model=ConnectionTestResult)
async def test_endpoint(
    endpoint_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_operator),
):
    ep = db.query(FileEndpoint).filter(FileEndpoint.id == endpoint_id).first()
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint non trovato")
    browser = get_browser(ep)
    result = await browser.test_connection()
    ep.last_test_at = datetime.utcnow()
    ep.last_test_status = "success" if result.success else "failed"
    ep.last_test_message = result.message
    db.commit()
    return result


@router.get("/{endpoint_id}/browse", response_model=list[BrowseEntryOut])
async def browse_endpoint(
    endpoint_id: int,
    path: str = Query("/"),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    ep = db.query(FileEndpoint).filter(FileEndpoint.id == endpoint_id).first()
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint non trovato")
    try:
        safe_path = sanitize_path(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    browser = get_browser(ep)
    try:
        return await browser.list_children(safe_path)
    except Exception as exc:
        logger.warning("browse endpoint %s failed: %s", endpoint_id, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
