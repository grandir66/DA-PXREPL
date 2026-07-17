# File Replication verso QNAP QuTS hero h6.0 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modulo dapx-unified per replica file monodirezionale da sorgenti eterogenee (Synology, QNAP, Linux, Windows) verso share staging QNAP QuTS hero h6.0, con immutabilità delegata a snapshot nativi.

**Architecture:** Endpoint riusabili con credenziali cifrate; browse lazy via client per tipo; sync rsync orchestrato dal backend dapx; snapshot immutabili configurati manualmente su QNAP h6.0 (UI hint only).

**Tech Stack:** FastAPI, SQLAlchemy 2.x, SQLite, Vue 3, httpx, paramiko (SSH), rsync/smbclient (system), cryptography (Fernet).

**Spec di riferimento:** `docs/superpowers/specs/2026-07-17-nas-worm-replication-design.md`

## Global Constraints

- Destinazione job: sempre endpoint tipo `qnap` (QuTS hero h6.0.x).
- Sync monodirezionale sorgente → QNAP staging mutabile; nessuna scrittura WORM durante sync.
- Password endpoint cifrate at rest; mai in log o risposte API.
- Route job/endpoint: `@require_operator` minimo; CRUD endpoint sensibili `@require_admin` se pattern esistente lo prevede.
- Path browse/sync: rifiutare `..` e path fuori base.
- Nuove tabelle via `database.py` + `Base.metadata.create_all`; nessuna migrazione Alembic.
- `update_db_schema.py` solo se servono colonne additive future.
- `CHANGELOG.md` aggiornato prima del commit di rilascio.
- Coerenza UI: classi `repl-*`, `btn`, wizard stile `JobModal.vue`.
- Fuori scope v1: trigger snapshot QNAP via API, relay VM, HBS automatico, sync bidirezionale.

## File Map

| File | Responsabilità |
|---|---|
| `backend/database.py` | Enum + modelli `FileEndpoint`, `FileReplicationJob` |
| `backend/services/file_replication/endpoint_crypto.py` | Fernet encrypt/decrypt password |
| `backend/services/file_replication/exclude_presets.py` | Preset → pattern rsync |
| `backend/services/file_replication/path_utils.py` | Sanitize path, match exclude |
| `backend/services/file_replication/browser_factory.py` | Factory → browser per tipo |
| `backend/services/file_replication/linux_browser.py` | Browse SSH |
| `backend/services/file_replication/synology_client.py` | Auth + browse DSM |
| `backend/services/file_replication/qnap_client.py` | Auth + browse QTS + test write |
| `backend/services/file_replication/smb_browser.py` | Browse SMB (Windows) |
| `backend/services/file_replication/file_sync_service.py` | Build rsync cmd, parse progress |
| `backend/services/file_replication/file_replication_execution.py` | Run job, JobLog, notify |
| `backend/services/file_replication_schemas.py` | Pydantic request/response |
| `backend/routers/file_endpoints.py` | CRUD endpoint + test + browse |
| `backend/routers/file_replication_jobs.py` | CRUD job + run + logs |
| `backend/services/scheduler.py` | Schedule `file_replication_{id}` |
| `backend/main.py` | Register routers |
| `backend/tests/test_file_replication_*.py` | Unit + API tests |
| `frontend/src/services/fileEndpoints.ts` | API client endpoint |
| `frontend/src/services/fileReplication.ts` | API client job |
| `frontend/src/components/file-replication/*` | UI componenti |
| `frontend/src/views/FileReplication.vue` | Vista principale |
| `frontend/src/router/index.ts` | Route |
| `frontend/src/layouts/MainLayout.vue` | Voce menu |

---

### Task 1: Modelli database

**Files:**
- Modify: `backend/database.py`
- Test: `backend/tests/test_file_replication_models.py`

**Interfaces:**
- Produces: `FileEndpointType`, `FileEndpointRole`, `FileEndpoint`, `FileReplicationJob`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_file_replication_models.py
from database import FileEndpoint, FileReplicationJob, FileEndpointType, FileEndpointRole


def test_create_file_endpoint_and_job(db):
    src = FileEndpoint(
        name="syno-src",
        endpoint_type=FileEndpointType.SYNOLOGY,
        role=FileEndpointRole.SOURCE,
        host="192.168.1.10",
        port=5001,
        protocol="api",
        username="admin",
        password_enc="enc:dummy",
    )
    dest = FileEndpoint(
        name="qnap-dest",
        endpoint_type=FileEndpointType.QNAP,
        role=FileEndpointRole.DESTINATION,
        host="192.168.1.20",
        port=8080,
        protocol="api",
        username="admin",
        password_enc="enc:dummy",
    )
    db.add_all([src, dest])
    db.commit()

    job = FileReplicationJob(
        name="archivio-docs",
        source_endpoint_id=src.id,
        dest_endpoint_id=dest.id,
        source_paths=["/documenti"],
        dest_staging_path="/staging/archivio-docs",
        sync_method="rsync_ssh",
        exclude_presets=["nas_snapshots", "system_files"],
        exclude_patterns=[],
        snapshot_policy_hint={"schedule": "0 3 * * *", "only_if_modified": True},
    )
    db.add(job)
    db.commit()
    assert job.id is not None
    assert job.source_endpoint.endpoint_type == FileEndpointType.SYNOLOGY
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `cd backend && python -m pytest tests/test_file_replication_models.py -v`
Expected: `ImportError` o `AttributeError` su `FileEndpoint`

- [ ] **Step 3: Add enums and models to database.py**

Aggiungere dopo gli enum esistenti (~riga 100):

```python
class FileEndpointType(str, enum.Enum):
    SYNOLOGY = "synology"
    QNAP = "qnap"
    LINUX = "linux"
    WINDOWS = "windows"


class FileEndpointRole(str, enum.Enum):
    SOURCE = "source"
    DESTINATION = "destination"
    BOTH = "both"
```

Aggiungere modelli (zona verde, dopo `HostBackupJob` ~riga 735):

```python
class FileEndpoint(Base):
    __tablename__ = "file_endpoints"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    endpoint_type = Column(Enum(FileEndpointType), nullable=False)
    role = Column(Enum(FileEndpointRole), nullable=False, default=FileEndpointRole.SOURCE)
    host = Column(String(255), nullable=False)
    port = Column(Integer, nullable=False, default=22)
    protocol = Column(String(20), nullable=False, default="ssh")
    username = Column(String(100), nullable=False)
    password_enc = Column(String(500), nullable=True)
    ssh_key_path = Column(String(500), nullable=True)
    domain = Column(String(100), nullable=True)
    base_path = Column(String(500), nullable=True)
    extra_config = Column(JSON, nullable=True, default=dict)
    last_test_at = Column(DateTime, nullable=True)
    last_test_status = Column(String(20), nullable=True)
    last_test_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    source_jobs = relationship("FileReplicationJob", foreign_keys="FileReplicationJob.source_endpoint_id", back_populates="source_endpoint")
    dest_jobs = relationship("FileReplicationJob", foreign_keys="FileReplicationJob.dest_endpoint_id", back_populates="dest_endpoint")


class FileReplicationJob(Base):
    __tablename__ = "file_replication_jobs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    source_endpoint_id = Column(Integer, ForeignKey("file_endpoints.id"), nullable=False)
    dest_endpoint_id = Column(Integer, ForeignKey("file_endpoints.id"), nullable=False)
    source_paths = Column(JSON, nullable=False, default=list)
    dest_staging_path = Column(String(500), nullable=False)
    sync_method = Column(String(30), nullable=False, default="rsync_ssh")
    delete_on_dest = Column(Boolean, default=True)
    on_source_delete = Column(String(20), default="keep")
    exclude_presets = Column(JSON, nullable=False, default=list)
    exclude_patterns = Column(JSON, nullable=False, default=list)
    bandwidth_limit_kb = Column(Integer, nullable=True)
    extra_rsync_args = Column(String(500), nullable=True)
    immutability_strategy = Column(String(50), default="qnap_immutable_snapshot")
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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    source_endpoint = relationship("FileEndpoint", foreign_keys=[source_endpoint_id], back_populates="source_jobs")
    dest_endpoint = relationship("FileEndpoint", foreign_keys=[dest_endpoint_id], back_populates="dest_jobs")
```

- [ ] **Step 4: Run test — expect PASS**

Run: `cd backend && python -m pytest tests/test_file_replication_models.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/database.py backend/tests/test_file_replication_models.py
git commit -m "feat(file-replication): add FileEndpoint and FileReplicationJob models"
```

---

### Task 2: Cifratura password endpoint

**Files:**
- Create: `backend/services/file_replication/__init__.py`
- Create: `backend/services/file_replication/endpoint_crypto.py`
- Test: `backend/tests/test_endpoint_crypto.py`

**Interfaces:**
- Produces: `encrypt_password(plain: str) -> str`, `decrypt_password(token: str) -> str`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_endpoint_crypto.py
import os
import pytest
from services.file_replication.endpoint_crypto import encrypt_password, decrypt_password


def test_encrypt_decrypt_roundtrip():
    os.environ["DAPX_SECRET_KEY"] = "test-secret-key-for-testing-only"
    enc = encrypt_password("s3cr3t!")
    assert enc != "s3cr3t!"
    assert decrypt_password(enc) == "s3cr3t!"


def test_decrypt_invalid_raises():
    with pytest.raises(ValueError):
        decrypt_password("not-valid")
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `cd backend && python -m pytest tests/test_endpoint_crypto.py -v`

- [ ] **Step 3: Implement endpoint_crypto.py**

```python
# backend/services/file_replication/endpoint_crypto.py
import os
import base64
import hashlib
import logging
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


def _fernet() -> Fernet:
    secret = (
        os.environ.get("DAPX_SECRET_KEY")
        or os.environ.get("SANOID_MANAGER_SECRET_KEY")
    )
    if not secret:
        raise RuntimeError("DAPX_SECRET_KEY non configurata")
    digest = hashlib.sha256(secret.encode()).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_password(plain: str) -> str:
    if not plain:
        return ""
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_password(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        logger.warning("decrypt_password: token invalido")
        raise ValueError("password endpoint non decifrabile") from exc
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add backend/services/file_replication/ backend/tests/test_endpoint_crypto.py
git commit -m "feat(file-replication): add Fernet password encryption for endpoints"
```

---

### Task 3: Preset esclusioni e path utils

**Files:**
- Create: `backend/services/file_replication/exclude_presets.py`
- Create: `backend/services/file_replication/path_utils.py`
- Test: `backend/tests/test_exclude_presets.py`

**Interfaces:**
- Produces: `build_exclude_lines(presets: list[str], custom: list[str]) -> list[str]`
- Produces: `sanitize_path(path: str) -> str`, `is_path_excluded(name: str, presets: list[str]) -> bool`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_exclude_presets.py
import pytest
from services.file_replication.exclude_presets import build_exclude_lines, PRESETS
from services.file_replication.path_utils import sanitize_path, is_excluded_name


def test_build_exclude_lines_merges_presets_and_custom():
    lines = build_exclude_lines(["nas_snapshots", "system_files"], ["*.bak"])
    assert "@Snapshot" in lines
    assert ".DS_Store" in lines
    assert "*.bak" in lines


def test_sanitize_path_rejects_traversal():
    with pytest.raises(ValueError):
        sanitize_path("/docs/../etc/passwd")


def test_is_excluded_name_snapshot():
    assert is_excluded_name("@Snapshot", ["nas_snapshots"]) is True
    assert is_excluded_name("documenti", ["nas_snapshots"]) is False
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# backend/services/file_replication/exclude_presets.py
PRESETS: dict[str, list[str]] = {
    "nas_snapshots": [
        "@Snapshot", "@snapshots", "#snapshot", ".snapshot",
        "@eaDir", "#recycle", ".Trash-*",
        "@SynologyApplicationService", "@ActiveBackup",
    ],
    "system_files": [
        ".DS_Store", "Thumbs.db", "desktop.ini",
        "*.tmp", "*.swp", "~$*", "*.lnk",
        "System Volume Information", "$RECYCLE.BIN",
    ],
    "windows_vss": ["~$*", "*.wbk"],
}


def build_exclude_lines(presets: list[str], custom: list[str]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for preset in presets or []:
        for pat in PRESETS.get(preset, []):
            if pat not in seen:
                seen.add(pat)
                lines.append(pat)
    for pat in custom or []:
        p = (pat or "").strip()
        if p and p not in seen:
            seen.add(p)
            lines.append(p)
    return lines
```

```python
# backend/services/file_replication/path_utils.py
import fnmatch
from services.file_replication.exclude_presets import PRESETS


def sanitize_path(path: str) -> str:
    p = (path or "").strip().replace("\\", "/")
    if not p:
        return "/"
    if ".." in p.split("/"):
        raise ValueError("path traversal non consentito")
    if not p.startswith("/"):
        p = "/" + p
    return p.rstrip("/") or "/"


def is_excluded_name(name: str, presets: list[str]) -> bool:
    patterns: list[str] = []
    for preset in presets or []:
        patterns.extend(PRESETS.get(preset, []))
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

---

### Task 4: Schemi Pydantic

**Files:**
- Create: `backend/services/file_replication_schemas.py`

**Interfaces:**
- Produces: `FileEndpointCreate`, `FileEndpointUpdate`, `FileEndpointOut`, `FileReplicationJobCreate`, `FileReplicationJobUpdate`, `FileReplicationJobOut`, `BrowseEntryOut`, `ConnectionTestResult`

- [ ] **Step 1: Create schemas**

```python
# backend/services/file_replication_schemas.py
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any
from datetime import datetime


class SnapshotPolicyHint(BaseModel):
    schedule: str = "0 3 * * *"
    protection: str = "prohibit_recycle_and_delete_until_expired"
    retention_mode: str = "smart_versioning"
    max_snapshots: int = 10
    expiration_days: int = 30
    only_if_modified: bool = True


class FileEndpointCreate(BaseModel):
    name: str
    endpoint_type: str  # synology | qnap | linux | windows
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
    is_active: bool
    current_status: Optional[str] = None
    last_run_at: Optional[datetime] = None
    last_run_status: Optional[str] = None
    last_bytes_transferred: Optional[int] = None
    source_endpoint_name: Optional[str] = None
    dest_endpoint_name: Optional[str] = None

    class Config:
        from_attributes = True
```

- [ ] **Step 2: Commit**

```bash
git add backend/services/file_replication_schemas.py
git commit -m "feat(file-replication): add Pydantic schemas"
```

---

### Task 5: Client Synology (auth + browse)

**Files:**
- Create: `backend/services/file_replication/synology_client.py`
- Test: `backend/tests/test_synology_client.py`

**Interfaces:**
- Produces: `SynologyClient(host, port, username, password, verify_ssl=True)`
- Methods: `async login()`, `async logout()`, `async test_connection() -> ConnectionTestResult`, `async list_children(path: str) -> list[BrowseEntryOut]`

- [ ] **Step 1: Write unit test with mocked httpx**

```python
# backend/tests/test_synology_client.py
import pytest
from unittest.mock import AsyncMock, patch
from services.file_replication.synology_client import SynologyClient


@pytest.mark.asyncio
async def test_list_shares_parses_response():
    client = SynologyClient("10.0.0.1", 5001, "user", "pass", verify_ssl=False)
    fake = {"success": True, "data": {"shares": [{"name": "documenti", "path": "/documenti"}]}}
    with patch.object(client, "_api_get", new=AsyncMock(return_value=fake)):
        with patch.object(client, "login", new=AsyncMock(return_value="sid")):
            rows = await client.list_children("/")
    assert rows[0].name == "documenti"
    assert rows[0].is_dir is True
```

- [ ] **Step 2: Implement synology_client.py**

Pattern API:
- `GET /webapi/auth.cgi?api=SYNO.API.Auth&version=7&method=login&account=&passwd=&session=FileStation&format=sid`
- `GET /webapi/entry.cgi?api=SYNO.FileStation.List&version=2&method=list_share&_sid=`
- `GET ...&method=list&folder_path=`

Usare `httpx.AsyncClient` con timeout 30s, `verify=verify_ssl`.

Mappare ogni entry con `is_excluded_name()` e `selectable=not is_excluded`.

- [ ] **Step 3: Run test — expect PASS**

- [ ] **Step 4: Commit**

---

### Task 6: Client QNAP (auth + browse + test write)

**Files:**
- Create: `backend/services/file_replication/qnap_client.py`
- Test: `backend/tests/test_qnap_client.py`

**Interfaces:**
- Produces: `QnapClient` — stessa interfaccia di Synology + `async get_firmware_version() -> str`

Implementazione:
- Login: `POST http://host:8080/cgi-bin/authLogin.cgi` (QTS 5+) con user/password
- Browse: File Station API v5 `func=get_list` / share list
- Version: endpoint sys info se disponibile; fallback messaggio "unknown"

- [ ] **Steps: test mock → implement → pytest → commit**

---

### Task 7: Browser Linux (SSH) e SMB (Windows)

**Files:**
- Create: `backend/services/file_replication/linux_browser.py`
- Create: `backend/services/file_replication/smb_browser.py`
- Create: `backend/services/file_replication/browser_factory.py`
- Test: `backend/tests/test_browser_factory.py`

**Interfaces:**
- Produces: `get_browser(endpoint: FileEndpoint) -> EndpointBrowser`
- `LinuxSshBrowser.list_children`: comando SSH `find '{path}' -maxdepth 1 -mindepth 1 -printf '%y\t%f\t%s\n'` (fallback `ls -la`)
- `SmbBrowser.list_children`: `smbclient -L` + `smbclient //host/share -c 'cd path; ls'` oppure mount temporaneo

```python
# backend/services/file_replication/browser_factory.py
from database import FileEndpoint, FileEndpointType
from services.file_replication.synology_client import SynologyClient
from services.file_replication.qnap_client import QnapClient
from services.file_replication.linux_browser import LinuxSshBrowser
from services.file_replication.smb_browser import SmbBrowser
from services.file_replication.endpoint_crypto import decrypt_password


def get_browser(endpoint: FileEndpoint):
    password = decrypt_password(endpoint.password_enc or "")
    if endpoint.endpoint_type == FileEndpointType.SYNOLOGY:
        ssl = (endpoint.extra_config or {}).get("verify_ssl", True)
        return SynologyClient(endpoint.host, endpoint.port or 5001, endpoint.username, password, verify_ssl=ssl)
    if endpoint.endpoint_type == FileEndpointType.QNAP:
        return QnapClient(endpoint.host, endpoint.port or 8080, endpoint.username, password)
    if endpoint.endpoint_type == FileEndpointType.LINUX:
        return LinuxSshBrowser(endpoint.host, endpoint.port or 22, endpoint.username, password, endpoint.ssh_key_path)
    if endpoint.endpoint_type == FileEndpointType.WINDOWS:
        return SmbBrowser(endpoint.host, endpoint.port or 445, endpoint.username, password, endpoint.domain, endpoint.base_path)
    raise ValueError(f"tipo endpoint non supportato: {endpoint.endpoint_type}")
```

- [ ] **Implement + test factory routing per ogni tipo → commit**

---

### Task 8: Router file endpoints

**Files:**
- Create: `backend/routers/file_endpoints.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_file_endpoints_api.py`

**Interfaces:**
- Consumes: Task 2–7
- Produces: REST `/api/file-endpoints/*`

- [ ] **Step 1: Write API tests**

```python
# backend/tests/test_file_endpoints_api.py
def test_create_and_list_endpoint(client, auth_headers):
    r = client.post("/api/file-endpoints", headers=auth_headers, json={
        "name": "linux-src",
        "endpoint_type": "linux",
        "role": "source",
        "host": "192.168.1.50",
        "port": 22,
        "protocol": "ssh",
        "username": "backup",
        "password": "secret",
    })
    assert r.status_code == 200
    eid = r.json()["id"]
    r2 = client.get("/api/file-endpoints", headers=auth_headers)
    assert any(x["id"] == eid for x in r2.json())
```

- [ ] **Step 2: Implement router**

Pattern da `host_backup.py`:
- `@router.get("")` lista
- `@router.post("")` crea — cifra password prima di salvare
- `@router.put("/{id}")` — se `password` in body, re-cifra
- `@router.delete("/{id}")` — rifiuta se referenziato da job
- `@router.post("/{id}/test")` — `browser.test_connection()`, aggiorna `last_test_*`
- `@router.get("/{id}/browse")` — query `path`, chiama `list_children(sanitize_path(path))`

Registrare in `main.py`:

```python
from routers import file_endpoints, file_replication_jobs
app.include_router(file_endpoints.router, prefix="/api/file-endpoints", tags=["file-endpoints"])
```

- [ ] **Step 3: pytest → commit**

---

### Task 9: Servizio rsync e esecuzione job

**Files:**
- Create: `backend/services/file_replication/file_sync_service.py`
- Create: `backend/services/file_replication/file_replication_execution.py`
- Test: `backend/tests/test_file_sync_service.py`

**Interfaces:**
- Produces: `build_rsync_command(job, source_endpoint, dest_endpoint) -> list[str]`
- Produces: `parse_rsync_progress(line: str) -> dict | None`
- Produces: `async execute_file_replication_job(job_id: int) -> None`

**Logica `file_sync_service.py`:**

```python
def build_rsync_command(job, src, dest, exclude_file: str, dest_local_mount: str | None) -> list[str]:
    cmd = ["rsync", "-a", "--info=progress2"]
    if job.delete_on_dest:
        cmd.append("--delete")
    if job.bandwidth_limit_kb:
        cmd.extend(["--bwlimit", str(job.bandwidth_limit_kb)])
    cmd.extend(["--exclude-from", exclude_file])
    if job.extra_rsync_args:
        cmd.extend(job.extra_rsync_args.split())
    # rsync_ssh: source remota via ssh, dest locale (mount qnap) o remota
    if job.sync_method == "rsync_ssh":
        ssh = f"ssh -p {src.port or 22} -o StrictHostKeyChecking=no"
        if src.ssh_key_path:
            ssh += f" -i {src.ssh_key_path}"
        cmd.extend(["-e", ssh])
        for sp in job.source_paths:
            cmd.append(f"{src.username}@{src.host}:{sp}/")
        cmd.append(f"{dest_local_mount or dest_staging_local}/{job.dest_staging_path.strip('/')}/")
    return cmd
```

**Strategia mount QNAP dest (v1):**
- Se dest protocol `smb`: mount CIFS temporaneo in `/tmp/dapx-fr-{job_id}/`
- Se dest protocol `ssh`: rsync diretto `user@qnap:/share/path/`

**`file_replication_execution.py`:**
1. Load job + endpoints
2. `JobLog(job_type="file_replication", status="running")`
3. Write exclude file temp
4. `asyncio.create_subprocess_exec` rsync, stream stderr → parse progress → update `job.current_status`
5. On success: stats + notify via `notification_service`
6. `finally`: unmount + delete temp files

- [ ] **Unit test build_rsync_command con job fittizio**
- [ ] **Implement execution (mock subprocess in test)**
- [ ] **Commit**

---

### Task 10: Router file replication jobs

**Files:**
- Create: `backend/routers/file_replication_jobs.py`
- Test: `backend/tests/test_file_replication_jobs_api.py`

**Endpoints:** CRUD + `POST /{id}/run` + `POST /{id}/toggle` + `GET /{id}/logs` + `GET /stats/summary`

Validazioni create:
- `dest_endpoint.endpoint_type == QNAP`
- `source_paths` non vuoto
- `dest_staging_path` sanitize

Run manuale: `asyncio.create_task(execute_file_replication_job(id))` con guard `_running_jobs`.

- [ ] **API tests CRUD + run 409 if already running**
- [ ] **Implement router**
- [ ] **Register in main.py**
- [ ] **Commit**

---

### Task 11: Integrazione scheduler

**Files:**
- Modify: `backend/services/scheduler.py`
- Test: `backend/tests/test_file_replication_scheduler.py`

**Pattern:** copiare blocco `HostBackupJob` (~riga 509):

```python
from database import FileReplicationJob
from services.file_replication.file_replication_execution import execute_file_replication_job

# in _check_scheduled_jobs:
file_jobs = db.query(FileReplicationJob).filter(
    FileReplicationJob.is_active == True,
    FileReplicationJob.schedule.isnot(None),
    FileReplicationJob.schedule != "",
).all()
for job in file_jobs:
    job_key = f"file_replication_{job.id}"
    # stessa logica croniter + _guarded_execute
    asyncio.create_task(self._guarded_execute(job_key, execute_file_replication_job, job.id))
```

Aggiungere metodi pubblici `update_file_replication_schedule(job_id, cron)` e `remove_file_replication_schedule(job_id)` chiamati dal router on create/update/delete.

- [ ] **Test job_key format**
- [ ] **Implement + commit**

---

### Task 12: Frontend — API services

**Files:**
- Create: `frontend/src/services/fileEndpoints.ts`
- Create: `frontend/src/services/fileReplication.ts`

```typescript
// frontend/src/services/fileEndpoints.ts
import api from './api'

export interface FileEndpoint {
  id: number
  name: string
  endpoint_type: 'synology' | 'qnap' | 'linux' | 'windows'
  role: string
  host: string
  port: number
  protocol: string
  username: string
}

export const fileEndpointsApi = {
  list: () => api.get<FileEndpoint[]>('/file-endpoints'),
  create: (data: Record<string, unknown>) => api.post<FileEndpoint>('/file-endpoints', data),
  test: (id: number) => api.post(`/file-endpoints/${id}/test`),
  browse: (id: number, path: string) => api.get(`/file-endpoints/${id}/browse`, { params: { path } }),
}
```

Stesso pattern per `fileReplication.ts` con CRUD + run + logs.

- [ ] **Create both files → commit**

---

### Task 13: Frontend — Form endpoint e FolderBrowser

**Files:**
- Create: `frontend/src/components/file-replication/FileEndpointForm.vue`
- Create: `frontend/src/components/file-replication/FolderBrowser.vue`

**FileEndpointForm.vue:**
- Props: `modelValue`, `endpointType`
- Campi condizionali per tipo (tabella spec §7.4)
- Emit `test` → chiama API test, mostra badge success/error

**FolderBrowser.vue:**
- Props: `endpointId`, `presets`
- State: `tree`, `expanded`, `selected: Set<string>`
- On expand: `fileEndpointsApi.browse(id, path)` → append children
- Checkbox solo se `entry.selectable`
- Righe `is_excluded`: classe `.fb-excluded`, checkbox disabled
- Emit `update:selectedPaths`

- [ ] **Implement components → manual smoke in dev**

---

### Task 14: Frontend — Wizard job e hint immutabilità

**Files:**
- Create: `frontend/src/components/file-replication/FileReplJobModal.vue`
- Create: `frontend/src/components/file-replication/QnapImmutabilityHint.vue`

**Wizard 4 step:**
1. Sorgente — select endpoint source + test
2. Cartelle — `FolderBrowser`
3. Destinazione — select endpoint QNAP + `dest_staging_path` + test
4. Regole — exclude presets checkboxes, custom patterns textarea, `delete_on_dest`, schedule cron, `QnapImmutabilityHint`

**QnapImmutabilityHint.vue:** checklist statica setup Snapshot Manager h6.0 + campi hint (schedule snapshot, expiration_days, max_snapshots) salvati in `snapshot_policy_hint`.

- [ ] **Implement → commit**

---

### Task 15: Frontend — Vista principale e navigazione

**Files:**
- Create: `frontend/src/views/FileReplication.vue`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/layouts/MainLayout.vue`
- Modify: `frontend/src/views/Replication.vue` (voce menu "Nuovo job" opzionale)

**FileReplication.vue:**
- Header stile `Replication.vue`
- Stats: totali, attivi, running, failed
- Tabella job con run/edit/log/delete/toggle
- Pulsante "Gestione endpoint" → modal o sub-view
- Integrazione `JobLogViewer.vue` esistente (`job_type=file_replication`)

**Router:**

```typescript
{
  path: 'file-replication',
  name: 'file-replication',
  component: () => import('../views/FileReplication.vue'),
},
```

**MainLayout.vue** — sotto "Repliche & Backup":

```html
<router-link :to="{ name: 'file-replication' }" class="nav-item" active-class="active">
  Replica file NAS
</router-link>
```

- [ ] **Implement + `npm run build` senza errori**
- [ ] **Commit**

---

### Task 16: Documentazione e CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`
- Create: `docs/file-replication-setup-qnap-h6.md`

**Contenuto doc setup QNAP h6.0:**
- Prerequisiti share staging thin
- Schedule snapshot immutabile (protection policy + smart versioning)
- Orari consigliati (sync dapx → +1h snapshot)
- Porte firewall (rsync 873, SSH 22, SMB 445, QNAP API 8080)
- Sorgenti supportate e protocolli

**CHANGELOG voce:**

```markdown
### Aggiunte
- Modulo replica file monodirezionale verso QNAP QuTS hero h6.0 (`backend/routers/file_replication_jobs.py`, `frontend/src/views/FileReplication.vue`): endpoint Synology/QNAP/Linux/Windows, browse cartelle, sync rsync, hint snapshot immutabili.
```

- [ ] **Write docs + CHANGELOG → commit**

---

## Self-Review (spec coverage)

| Requisito spec | Task |
|---|---|
| Endpoint CRUD + test | 8 |
| Credenziali cifrate | 2 |
| Browse lazy multi-tipo | 5–7, 13 |
| Job monodirezionale + exclude | 3, 9, 10 |
| Schedule + JobLog | 9, 10, 11 |
| UI wizard 4 step | 14 |
| Hint immutabilità QNAP h6.0 | 14, 16 |
| Sorgenti Synology/QNAP/Linux/Windows | 5–7 |
| Dest solo QNAP | 10 (validazione) |
| Sicurezza path traversal | 3 |
| Fuori scope snapshot API | non presente ✓ |

**Placeholder scan:** nessun TBD nel piano.

**Type consistency:** `BrowseEntryOut`, `FileEndpointType`, `job_type="file_replication"` allineati tra task.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-17-file-replication-qnap.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — implement tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
