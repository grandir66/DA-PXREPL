# «Repliche dati» v2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nuovo modulo parallelo «Repliche dati» (`/api/nas-sync`, view `NasSync.vue`) con motore diretto rsync NAS→NAS e fallback rclone SMB, senza toccare il modulo esistente «Replica file».

**Architecture:** Verticale autonoma: nuovo package `backend/services/nas_sync/`, nuova tabella `nas_sync_jobs`, nuovo router, nuova view+menù. Tabella `file_endpoints` condivisa in lettura con chiavi additive in `extra_config`. Due engine dietro un contratto eventi comune; l'orchestratore è engine-agnostico. Spec di riferimento: `docs/superpowers/specs/2026-07-20-nas-sync-v2-design.md`.

**Tech Stack:** FastAPI + SQLAlchemy 2.x + SQLite; Vue 3 + TS + Vite; rsync (remoto via SSH), rclone (locale, SMB, `--use-json-log`); pytest + pytest-asyncio.

## Global Constraints

- **VIETATO modificare** questi file/directory (modulo esistente): `backend/routers/file_replication_jobs.py`, `backend/routers/file_endpoints.py`, `backend/services/file_replication/**`, `backend/services/file_replication_schemas.py`, `frontend/src/views/FileReplication.vue`, `frontend/src/components/file-replication/**`, `frontend/src/services/fileReplication.ts`, `frontend/src/utils/fileReplProgress.ts`. Da questi si può solo **importare** o **copiare**.
- Unici file esistenti modificabili (solo blocchi additivi indicati nei task): `backend/main.py`, `backend/services/scheduler.py`, `backend/update_db_schema.py`, `backend/database.py` (**NO** — nemmeno questo: il modello v2 vive in `services/nas_sync/models.py`), `frontend/src/router/index.ts`, `frontend/src/layouts/MainLayout.vue`, `CHANGELOG.md`.
- **NIENTE bump versioni** (`version.json`, `backend/version.json`, `frontend/package.json`, `main.py`): nessuna release in questo piano. **NIENTE `git push`**: solo commit locali.
- Mai credenziali in argv, log o messaggi d'errore. Le password degli endpoint si cifrano/decifrano SOLO con `services.file_replication.endpoint_crypto` (import read-only).
- Etichette UI in italiano. Voce menù nuova: **«Repliche dati»**. Non rinominare la voce esistente «Replica file NAS».
- Test backend: `cd backend && ./venv/bin/python -m pytest tests/<file> -v`. Build frontend: `cd frontend && npm run build`.
- Un commit per task, prefisso `feat(nas-sync):` (o `test:`/`chore:` dove indicato). Prima di ogni commit: `git diff --name-only` NON deve contenere file della lista vietata.
- Import ammessi dal modulo esistente (funzioni pure, read-only): `services.file_replication.endpoint_crypto`, `services.file_replication.path_utils`, `services.file_replication.exclude_presets`, `services.size_utils`.

---

### Task 1: Modello DB `NasSyncJob` + registrazione schema

**Files:**
- Create: `backend/services/nas_sync/__init__.py`
- Create: `backend/services/nas_sync/models.py`
- Modify: `backend/update_db_schema.py` (blocco additivo in `update_schema()`)
- Test: `backend/tests/test_nas_sync_models.py`

**Interfaces:**
- Produces: classe `NasSyncJob` (tabella `nas_sync_jobs`) con i campi elencati sotto; import path `services.nas_sync.models`.

- [ ] **Step 1: Write the failing test**

```python
"""Test modello NasSyncJob."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from services.nas_sync.models import NasSyncJob


def test_nas_sync_job_table_create_and_insert():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    job = NasSyncJob(
        name="test",
        source_endpoint_id=1,
        dest_endpoint_id=2,
        source_paths=["/SHARE/docs"],
        dest_base_path="/share/DATI",
    )
    db.add(job)
    db.commit()
    row = db.query(NasSyncJob).first()
    assert row.name == "test"
    assert row.sync_method == "auto"
    assert row.delete_on_dest is False
    assert row.exclude_presets == []
    assert row.run_state == {}
    db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_nas_sync_models.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'services.nas_sync'`

- [ ] **Step 3: Write minimal implementation**

`backend/services/nas_sync/__init__.py`:

```python
"""Modulo «Repliche dati» v2 — sync NAS→NAS diretto (rsync) o via rclone SMB."""
```

`backend/services/nas_sync/models.py`:

```python
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
```

Nota: `default=list`/`default=dict` sono callables lato Python → al primo `refresh` dopo insert i JSON risultano `[]`/`{}`. Se il test mostra `None` per `run_state`, aggiungere `db.refresh(job)` dopo commit nel test è ACCETTABILE; NON cambiare il modello.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_nas_sync_models.py -v`
Expected: PASS

- [ ] **Step 5: Registrare la tabella in `update_db_schema.py`**

In `backend/update_db_schema.py`, dentro `update_schema()`, individuare la riga
`_ensure_column(conn, "file_replication_jobs", "run_state", "JSON")` e aggiungere **subito dopo** (stessa indentazione):

```python
            # Repliche dati v2: tabella nuova, creata idempotente via metadata.
            # Il modello è registrato importando services.nas_sync.models.
            from services.nas_sync import models as _nas_sync_models  # noqa: F401
            Base.metadata.create_all(bind=engine)
```

Se `Base`/`engine` non sono già importati a inizio file, aggiungere all'import esistente da `database`: `from database import Base, engine` (verificare con `grep -n "^from database" backend/update_db_schema.py` e integrare, senza duplicare import).

- [ ] **Step 6: Verifica schema script**

Run: `cd backend && ./venv/bin/python -c "import update_db_schema; print('ok')"`
Expected: `ok` (nessun ImportError)

- [ ] **Step 7: Commit**

```bash
git add backend/services/nas_sync/__init__.py backend/services/nas_sync/models.py backend/update_db_schema.py backend/tests/test_nas_sync_models.py
git commit -m "feat(nas-sync): modello NasSyncJob e tabella nas_sync_jobs"
```

---

### Task 2: Matrice di capacità e selezione engine

**Files:**
- Create: `backend/services/nas_sync/capabilities.py`
- Test: `backend/tests/test_nas_sync_capabilities.py`

**Interfaces:**
- Consumes: `FileEndpoint`, `FileEndpointType` da `database`.
- Produces:
  - `ENGINE_DIRECT = "direct_rsync"`, `ENGINE_RCLONE = "rclone_smb"` (costanti stringa)
  - `resolve_capabilities(endpoint) -> dict` con chiavi `rsync_source: bool`, `rsync_dest: bool`, `smb: bool`, `reasons: dict[str, str]`
  - `resolve_engine(sync_method: str, source, dest) -> tuple[str, str]` → `(engine, reason)`; solleva `ValueError` con messaggio italiano se il metodo forzato non è supportato.

- [ ] **Step 1: Write the failing test**

```python
"""Test matrice capacità e selezione engine nas_sync."""

import pytest

from database import FileEndpoint, FileEndpointType
from services.nas_sync.capabilities import (
    ENGINE_DIRECT,
    ENGINE_RCLONE,
    resolve_capabilities,
    resolve_engine,
)


def _ep(ep_type, *, password_enc="x", ssh_key=None, extra=None):
    return FileEndpoint(
        name="e",
        endpoint_type=ep_type,
        host="h",
        port=22,
        protocol="ssh",
        username="u",
        password_enc=password_enc,
        ssh_key_path=ssh_key,
        extra_config=extra or {},
    )


def test_synology_source_has_rsync_and_smb():
    caps = resolve_capabilities(_ep(FileEndpointType.SYNOLOGY))
    assert caps["rsync_source"] is True
    assert caps["smb"] is True
    assert caps["rsync_dest"] is False  # manca rsync_module


def test_qnap_dest_with_module_has_rsync_dest():
    caps = resolve_capabilities(
        _ep(FileEndpointType.QNAP, extra={"rsync_module": "DATI", "rsync_password_enc": "x"})
    )
    assert caps["rsync_dest"] is True


def test_windows_is_smb_only():
    caps = resolve_capabilities(_ep(FileEndpointType.WINDOWS))
    assert caps == {
        "rsync_source": False,
        "rsync_dest": False,
        "smb": True,
        "reasons": caps["reasons"],
    }
    assert "rsync" in caps["reasons"]["rsync_source"].lower()


def test_source_without_credentials_no_rsync_source():
    caps = resolve_capabilities(_ep(FileEndpointType.SYNOLOGY, password_enc=None))
    assert caps["rsync_source"] is False


def test_auto_picks_direct_when_both_capable():
    src = _ep(FileEndpointType.SYNOLOGY)
    dst = _ep(FileEndpointType.QNAP, extra={"rsync_module": "DATI", "rsync_password_enc": "x"})
    engine, reason = resolve_engine("auto", src, dst)
    assert engine == ENGINE_DIRECT
    assert "diretto" in reason.lower()


def test_auto_falls_back_to_rclone_for_windows_source():
    src = _ep(FileEndpointType.WINDOWS)
    dst = _ep(FileEndpointType.QNAP, extra={"rsync_module": "DATI", "rsync_password_enc": "x"})
    engine, _ = resolve_engine("auto", src, dst)
    assert engine == ENGINE_RCLONE


def test_forced_direct_raises_if_unsupported():
    src = _ep(FileEndpointType.WINDOWS)
    dst = _ep(FileEndpointType.QNAP, extra={})
    with pytest.raises(ValueError):
        resolve_engine("direct_rsync", src, dst)


def test_forced_rclone_always_allowed_for_smb_pair():
    src = _ep(FileEndpointType.SYNOLOGY)
    dst = _ep(FileEndpointType.QNAP, extra={"rsync_module": "DATI", "rsync_password_enc": "x"})
    engine, _ = resolve_engine("rclone_smb", src, dst)
    assert engine == ENGINE_RCLONE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_nas_sync_capabilities.py -v`
Expected: FAIL con `ModuleNotFoundError` (capabilities non esiste)

- [ ] **Step 3: Write minimal implementation**

`backend/services/nas_sync/capabilities.py`:

```python
"""Capacità per endpoint e selezione engine (auto | direct_rsync | rclone_smb)."""

from __future__ import annotations

from database import FileEndpoint, FileEndpointType

ENGINE_DIRECT = "direct_rsync"
ENGINE_RCLONE = "rclone_smb"

_SSH_CAPABLE = (FileEndpointType.SYNOLOGY, FileEndpointType.QNAP, FileEndpointType.LINUX)
_SMB_CAPABLE = (FileEndpointType.SYNOLOGY, FileEndpointType.QNAP, FileEndpointType.WINDOWS)


def _has_ssh_credentials(ep: FileEndpoint) -> bool:
    return bool(ep.ssh_key_path) or bool(ep.password_enc)


def resolve_capabilities(ep: FileEndpoint) -> dict:
    """Capacità derivate da tipo + config. reasons spiega ogni capacità mancante."""
    reasons: dict[str, str] = {}

    rsync_source = ep.endpoint_type in _SSH_CAPABLE and _has_ssh_credentials(ep)
    if ep.endpoint_type not in _SSH_CAPABLE:
        reasons["rsync_source"] = "Il tipo endpoint non supporta rsync via SSH (solo SMB)."
    elif not _has_ssh_credentials(ep):
        reasons["rsync_source"] = "Mancano credenziali SSH (chiave o password)."

    extra = ep.extra_config or {}
    has_module = bool(extra.get("rsync_module"))
    rsync_dest = ep.endpoint_type in _SSH_CAPABLE and has_module
    if ep.endpoint_type not in _SSH_CAPABLE:
        reasons["rsync_dest"] = "Il tipo endpoint non può fare da destinazione rsync."
    elif not has_module:
        reasons["rsync_dest"] = (
            "Modulo rsync non configurato: attiva il servizio rsync sul NAS "
            "e imposta modulo/utente/password nell'endpoint."
        )

    smb = ep.endpoint_type in _SMB_CAPABLE
    if not smb:
        reasons["smb"] = "Endpoint senza share SMB."

    return {
        "rsync_source": rsync_source,
        "rsync_dest": rsync_dest,
        "smb": smb,
        "reasons": reasons,
    }


def resolve_engine(sync_method: str, source: FileEndpoint, dest: FileEndpoint) -> tuple[str, str]:
    """Risolve l'engine effettivo. Solleva ValueError se un metodo forzato non è supportato."""
    src_caps = resolve_capabilities(source)
    dst_caps = resolve_capabilities(dest)
    direct_ok = src_caps["rsync_source"] and dst_caps["rsync_dest"]
    rclone_ok = src_caps["smb"] and dst_caps["smb"]

    if sync_method == ENGINE_DIRECT:
        if not direct_ok:
            missing = []
            if not src_caps["rsync_source"]:
                missing.append(f"sorgente: {src_caps['reasons'].get('rsync_source', 'non idonea')}")
            if not dst_caps["rsync_dest"]:
                missing.append(f"destinazione: {dst_caps['reasons'].get('rsync_dest', 'non idonea')}")
            raise ValueError("Motore diretto rsync non disponibile — " + "; ".join(missing))
        return ENGINE_DIRECT, "Motore diretto rsync forzato dall'utente."

    if sync_method == ENGINE_RCLONE:
        if not rclone_ok:
            raise ValueError("Motore rclone SMB non disponibile: sorgente o destinazione senza SMB.")
        return ENGINE_RCLONE, "Motore rclone SMB forzato dall'utente."

    # auto
    if direct_ok:
        return ENGINE_DIRECT, (
            "Diretto rsync: i dati viaggiano dalla sorgente alla destinazione senza passare da dapx."
        )
    if rclone_ok:
        why = (
            src_caps["reasons"].get("rsync_source")
            or dst_caps["reasons"].get("rsync_dest")
            or "prerequisiti rsync mancanti"
        )
        return ENGINE_RCLONE, f"rclone SMB (fallback): {why}"
    raise ValueError(
        "Nessun motore disponibile per questa coppia di endpoint: configurare SSH/rsync o SMB."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_nas_sync_capabilities.py -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/nas_sync/capabilities.py backend/tests/test_nas_sync_capabilities.py
git commit -m "feat(nas-sync): matrice capacità endpoint e selezione engine"
```

---

### Task 3: Modello eventi comune + vista progresso

**Files:**
- Create: `backend/services/nas_sync/events.py`
- Test: `backend/tests/test_nas_sync_events.py`

**Interfaces:**
- Produces:
  - `@dataclass SyncEvent` con campi: `phase: str | None`, `last_file: str | None`, `files_new: int = 0`, `files_replaced: int = 0`, `files_skipped: int = 0`, `files_deleted: int = 0`, `bytes_done: int | None = None`, `bytes_total: int | None = None`, `percent: int | None = None`, `speed: str | None = None`, `eta_seconds: int | None = None`, `raw_line: str = ""`
  - `apply_event(progress: dict, ev: SyncEvent) -> dict` (nuovo dict, accumula contatori, aggiorna ultimi valori)
  - `build_view(progress: dict) -> dict` — aggiunge i campi UI che il frontend esistente consuma: `phase`, `phase_label`, `detail_lines: list[str]`, `display_summary`, `progress_percent`, `eta_human`, `transferred_human`, `files_done`, `files_copied`
  - `human_bytes(n: int) -> str` (es. `1536 → "1.5 KiB"`)

I nomi dei contatori nel dict progress DEVONO essere: `files_new`, `files_replaced`, `files_copied` (= new+replaced), `files_skipped`, `files_deleted`, `files_done` (= files_copied), `last_file`, `bytes_done`, `bytes_total`, `percent`, `speed`, `eta_seconds` — il frontend v2 riusa `fileReplProgress.ts` che legge questi nomi (stessi del modulo esistente).

- [ ] **Step 1: Write the failing test**

```python
"""Test eventi e vista progresso nas_sync."""

from services.nas_sync.events import SyncEvent, apply_event, build_view, human_bytes


def test_apply_event_accumulates_counters():
    p: dict = {}
    p = apply_event(p, SyncEvent(phase="copying", last_file="a.txt", files_new=1))
    p = apply_event(p, SyncEvent(phase="copying", last_file="b.txt", files_replaced=1))
    p = apply_event(p, SyncEvent(phase="copying", files_skipped=2))
    assert p["files_new"] == 1
    assert p["files_replaced"] == 1
    assert p["files_copied"] == 2
    assert p["files_done"] == 2
    assert p["files_skipped"] == 2
    assert p["last_file"] == "b.txt"


def test_apply_event_updates_bytes_and_speed():
    p = apply_event({}, SyncEvent(phase="copying", bytes_done=1048576, bytes_total=4194304,
                                  percent=25, speed="2.00MB/s", eta_seconds=90))
    assert p["bytes_done"] == 1048576
    assert p["percent"] == 25
    assert p["speed"] == "2.00MB/s"
    assert p["eta_seconds"] == 90


def test_build_view_copying_labels():
    p = {"phase": "copying", "files_new": 3, "files_replaced": 1, "files_copied": 4,
         "files_skipped": 10, "files_deleted": 0, "files_done": 4,
         "bytes_done": 1048576, "bytes_total": 4194304, "percent": 25,
         "speed": "2.00MB/s", "eta_seconds": 90, "last_file": "x.txt"}
    view = build_view(p)
    assert view["phase_label"] == "Copia file verso destinazione"
    assert any("3 nuovi" in line for line in view["detail_lines"])
    assert view["progress_percent"] == "25%"
    assert view["eta_human"] == "1 minuto e 30 secondi"
    assert view["transferred_human"] == "1.0 MiB"


def test_build_view_scanning():
    view = build_view({"phase": "scanning"})
    assert view["phase_label"] == "Scansione sorgente"


def test_human_bytes():
    assert human_bytes(0) == "0 B"
    assert human_bytes(1536) == "1.5 KiB"
    assert human_bytes(1073741824) == "1.0 GiB"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_nas_sync_events.py -v`
Expected: FAIL con ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

`backend/services/nas_sync/events.py`:

```python
"""Modello eventi comune ai due engine e costruzione vista progresso per la UI."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SyncEvent:
    phase: str | None = None
    last_file: str | None = None
    files_new: int = 0
    files_replaced: int = 0
    files_skipped: int = 0
    files_deleted: int = 0
    bytes_done: int | None = None
    bytes_total: int | None = None
    percent: int | None = None
    speed: str | None = None
    eta_seconds: int | None = None
    raw_line: str = ""


def human_bytes(n: int | None) -> str:
    if not n:
        return "0 B"
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def _fmt_count(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def eta_human(seconds: int | None) -> str | None:
    if not seconds or seconds <= 0:
        return None
    units = (
        (seconds // 86400, "giorno", "giorni"),
        ((seconds % 86400) // 3600, "ora", "ore"),
        ((seconds % 3600) // 60, "minuto", "minuti"),
        (seconds % 60, "secondo", "secondi"),
    )
    parts = [f"{n} {sing if n == 1 else plur}" for n, sing, plur in units if n]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + f" e {parts[-1]}"


def apply_event(progress: dict, ev: SyncEvent) -> dict:
    """Accumula un evento nel dict di progresso (ritorna un nuovo dict)."""
    p = dict(progress)
    for attr in ("files_new", "files_replaced", "files_skipped", "files_deleted"):
        delta = getattr(ev, attr)
        if delta:
            p[attr] = int(p.get(attr) or 0) + delta
    p["files_copied"] = int(p.get("files_new") or 0) + int(p.get("files_replaced") or 0)
    p["files_done"] = p["files_copied"]
    if ev.phase:
        p["phase"] = ev.phase
    if ev.last_file:
        p["last_file"] = ev.last_file
    for attr in ("bytes_done", "bytes_total", "percent", "speed", "eta_seconds"):
        value = getattr(ev, attr)
        if value is not None:
            p[attr] = value
    return p


_PHASE_LABELS = {
    "starting": "Avvio replica…",
    "scanning": "Scansione sorgente",
    "copying": "Copia file verso destinazione",
    "done": "Completato",
}


def build_view(progress: dict) -> dict:
    """Campi leggibili per la UI (stessi nomi consumati da fileReplProgress.ts)."""
    view = dict(progress)
    phase = view.get("phase") or "starting"
    view["phase"] = phase
    view["phase_label"] = _PHASE_LABELS.get(phase, phase)

    detail_lines: list[str] = []
    new = int(view.get("files_new") or 0)
    replaced = int(view.get("files_replaced") or 0)
    skipped = int(view.get("files_skipped") or 0)
    deleted = int(view.get("files_deleted") or 0)
    if new or replaced or skipped or deleted:
        parts = []
        if new:
            parts.append(f"{_fmt_count(new)} nuovi")
        if replaced:
            parts.append(f"{_fmt_count(replaced)} aggiornati")
        if skipped:
            parts.append(f"{_fmt_count(skipped)} già allineati (saltati)")
        if deleted:
            parts.append(f"{_fmt_count(deleted)} eliminati su destinazione")
        detail_lines.append("File elaborati: " + ", ".join(parts))

    bytes_done = view.get("bytes_done")
    if bytes_done:
        view["transferred_human"] = human_bytes(int(bytes_done))
        total = view.get("bytes_total")
        if total:
            detail_lines.append(
                f"Trasferiti: {human_bytes(int(bytes_done))} / {human_bytes(int(total))}"
            )
        else:
            detail_lines.append(f"Trasferiti: {human_bytes(int(bytes_done))}")

    if view.get("percent") is not None:
        view["progress_percent"] = f"{int(view['percent'])}%"
    if view.get("speed"):
        detail_lines.append(f"Velocità attuale: {view['speed']}")
    eta = eta_human(view.get("eta_seconds"))
    if eta:
        view["eta_human"] = eta
        detail_lines.append(f"Tempo restante stimato: ~{eta}")
    if view.get("last_file") and phase == "copying":
        detail_lines.append(f"Ultimo file: {view['last_file']}")

    view["detail_lines"] = detail_lines
    view["display_summary"] = view["phase_label"] + (f" — {detail_lines[0]}" if detail_lines else "")
    return view
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_nas_sync_events.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/nas_sync/events.py backend/tests/test_nas_sync_events.py
git commit -m "feat(nas-sync): modello eventi SyncEvent e vista progresso"
```

---

### Task 4: Motore diretto — builder comandi e parser output

**Files:**
- Create: `backend/services/nas_sync/engine_direct_rsync.py` (solo builder+parser in questo task; il runner arriva nel Task 5 nello stesso file)
- Test: `backend/tests/test_nas_sync_direct_rsync.py`

**Interfaces:**
- Consumes: `SyncEvent` (Task 3), `sanitize_path`/`normalize_synology_ssh_path` da `services.file_replication.path_utils`, `decrypt_password` da `services.file_replication.endpoint_crypto`.
- Produces:
  - `build_source_fs_path(source, src_path) -> str` — path filesystem sulla sorgente, con `/` finale
  - `build_dest_rsync_url(dest, src_path, dest_subpath) -> str` — `rsync://user@host:port/MODULE/sub/`
  - `build_remote_rsync_script(fs_src, dest_url, *, exclude_lines, delete_on_dest, bandwidth_limit_kb) -> str` — script shell remoto: legge la password modulo da stdin, esporta `RSYNC_PASSWORD`, stampa `__DAPX_PID__<pid>`, `exec rsync …`
  - `build_ssh_argv(source) -> tuple[list[str], dict]` — argv ssh/sshpass + env extra (`SSHPASS` se password); **mai** password in argv
  - `parse_rsync_line(line) -> SyncEvent | None` — gestisce progress2 (stderr) e itemize `%i %n` (stdout) e `*deleting`
  - `RSYNC_EXIT_HINTS: dict[int, str]`, `RSYNC_WARNING_EXITS = (23, 24)`

- [ ] **Step 1: Write the failing test**

```python
"""Test builder e parser del motore diretto rsync."""

from database import FileEndpoint, FileEndpointType
from services.nas_sync.engine_direct_rsync import (
    RSYNC_WARNING_EXITS,
    build_dest_rsync_url,
    build_remote_rsync_script,
    build_source_fs_path,
    build_ssh_argv,
    parse_rsync_line,
)


def _src(ep_type=FileEndpointType.SYNOLOGY, **kw):
    defaults = dict(name="s", endpoint_type=ep_type, host="10.0.0.1", port=5001,
                    protocol="api", username="admin", password_enc="enc",
                    extra_config={})
    defaults.update(kw)
    return FileEndpoint(**defaults)


def _dst(**kw):
    defaults = dict(name="d", endpoint_type=FileEndpointType.QNAP, host="10.0.0.2",
                    port=8080, protocol="api", username="admin", password_enc="enc",
                    extra_config={"rsync_module": "DATI", "rsync_user": "backup",
                                  "rsync_port": 873})
    defaults.update(kw)
    return FileEndpoint(**defaults)


def test_source_fs_path_synology_volume():
    assert build_source_fs_path(_src(), "/Condivisa/docs") == "/volume1/Condivisa/docs/"


def test_source_fs_path_qnap_share_prefix():
    ep = _src(ep_type=FileEndpointType.QNAP)
    assert build_source_fs_path(ep, "/Public/foto") == "/share/Public/foto/"


def test_dest_rsync_url_includes_module_and_subpath():
    url = build_dest_rsync_url(_dst(), "/Condivisa/docs", "")
    assert url == "rsync://backup@10.0.0.2:873/DATI/Condivisa/docs/"


def test_dest_rsync_url_with_base_subpath():
    url = build_dest_rsync_url(_dst(), "/Condivisa/docs", "backup-syno")
    assert url == "rsync://backup@10.0.0.2:873/DATI/backup-syno/Condivisa/docs/"


def test_remote_script_never_contains_password_and_exports_env():
    script = build_remote_rsync_script(
        "/volume1/Condivisa/docs/",
        "rsync://backup@10.0.0.2:873/DATI/Condivisa/docs/",
        exclude_lines=["@eaDir", "#recycle"],
        delete_on_dest=True,
        bandwidth_limit_kb=5000,
    )
    assert "IFS= read -r RSYNC_PASSWORD" in script
    assert "export RSYNC_PASSWORD" in script
    assert "__DAPX_PID__$$" in script
    assert "--delete-after" in script
    assert "--bwlimit=5000" in script
    assert "--exclude '@eaDir'" in script
    assert "--partial-dir=.dapx-partial" in script
    assert "--info=progress2" in script


def test_ssh_argv_with_key_uses_batchmode(monkeypatch):
    ep = _src(ssh_key_path="/root/.ssh/id_rsa", password_enc=None)
    argv, env = build_ssh_argv(ep)
    assert argv[0] == "ssh"
    assert "-i" in argv and "/root/.ssh/id_rsa" in argv
    assert "BatchMode=yes" in " ".join(argv)
    assert env == {}
    assert argv[-1] == "admin@10.0.0.1"


def test_ssh_argv_with_password_uses_sshpass_env(monkeypatch):
    monkeypatch.setattr(
        "services.nas_sync.engine_direct_rsync.decrypt_password", lambda _: "segreta"
    )
    argv, env = build_ssh_argv(_src())
    assert argv[0] == "sshpass"
    assert argv[1] == "-e"
    assert "segreta" not in " ".join(argv)
    assert env == {"SSHPASS": "segreta"}


def test_parse_progress2_line():
    ev = parse_rsync_line("  1,234,567  12%  3.21MB/s    0:01:23 (xfr#5, to-chk=100/500)")
    assert ev.bytes_done == 1234567
    assert ev.percent == 12
    assert ev.speed == "3.21MB/s"
    assert ev.eta_seconds == 83
    assert ev.phase == "copying"


def test_parse_itemize_new_file():
    ev = parse_rsync_line(">f+++++++++ docs/report.pdf")
    assert ev.files_new == 1
    assert ev.last_file == "docs/report.pdf"


def test_parse_itemize_updated_file():
    ev = parse_rsync_line(">f.st...... docs/old.xlsx")
    assert ev.files_replaced == 1


def test_parse_itemize_directory_ignored():
    assert parse_rsync_line("cd+++++++++ docs/") is None


def test_parse_deleting():
    ev = parse_rsync_line("*deleting   docs/gone.txt")
    assert ev.files_deleted == 1
    assert ev.last_file == "docs/gone.txt"


def test_parse_garbage_returns_none():
    assert parse_rsync_line("sending incremental file list") is None


def test_warning_exits():
    assert 23 in RSYNC_WARNING_EXITS and 24 in RSYNC_WARNING_EXITS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_nas_sync_direct_rsync.py -v`
Expected: FAIL con ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

`backend/services/nas_sync/engine_direct_rsync.py`:

```python
"""Motore diretto: rsync eseguito via SSH sulla sorgente, push verso rsyncd destinazione.

I dati viaggiano sorgente→destinazione senza transitare da dapx.
Sicurezza: password SSH via env SSHPASS (sshpass -e); password modulo rsync
via stdin remoto → RSYNC_PASSWORD. Mai credenziali in argv o nei log.
"""

from __future__ import annotations

import re
import shlex

from database import FileEndpoint, FileEndpointType
from services.file_replication.endpoint_crypto import decrypt_password
from services.file_replication.path_utils import normalize_synology_ssh_path, sanitize_path
from services.nas_sync.events import SyncEvent

RSYNC_WARNING_EXITS = (23, 24)
RSYNC_EXIT_HINTS: dict[int, str] = {
    1: "Errore di sintassi rsync (bug interno: aprire un issue).",
    5: "Autenticazione al modulo rsync fallita: verifica utente/password del servizio rsync sul NAS di destinazione.",
    10: "Errore socket verso il demone rsync di destinazione: verifica che il servizio rsync sia attivo e la porta raggiungibile.",
    11: "Errore I/O file: spazio disco o permessi sulla destinazione.",
    12: "Errore di protocollo rsync: versioni rsync incompatibili tra sorgente e destinazione.",
    30: "Timeout di rete durante il trasferimento.",
    35: "Timeout in attesa del demone rsync di destinazione.",
    255: "Connessione SSH alla sorgente fallita: verifica host, porta, credenziali SSH.",
}

_PROGRESS2_RE = re.compile(
    r"^\s*([\d,]+)\s+(\d+)%\s+([\d.]+\s?[KMGT]?B/s)\s+(\d+):(\d{2}):(\d{2})"
)
_ITEMIZE_RE = re.compile(r"^([<>ch.*][fdLDS])([+.cstTpoguax?]{7,10})\s(.+)$")
_DELETING_RE = re.compile(r"^\*deleting\s+(.+)$")


def _ssh_port(ep: FileEndpoint) -> int:
    extra = ep.extra_config or {}
    if extra.get("ssh_port") is not None:
        return int(extra["ssh_port"])
    if ep.protocol == "ssh":
        return ep.port or 22
    return 22


def build_source_fs_path(source: FileEndpoint, src_path: str) -> str:
    """Path filesystem del percorso sorgente, visto da shell SSH sulla sorgente."""
    clean = sanitize_path(src_path)
    if source.endpoint_type == FileEndpointType.SYNOLOGY:
        extra = source.extra_config or {}
        vol = extra.get("synology_volume") or extra.get("ssh_volume") or "volume1"
        return normalize_synology_ssh_path(clean, vol).rstrip("/") + "/"
    if source.endpoint_type == FileEndpointType.QNAP:
        return f"/share{clean}".rstrip("/") + "/"
    base = (source.base_path or "").rstrip("/")
    return f"{base}{clean}".rstrip("/") + "/"


def build_dest_rsync_url(dest: FileEndpoint, src_path: str, dest_subpath: str) -> str:
    """URL rsyncd destinazione: rsync://user@host:port/MODULE/[subpath/]<struttura sorgente>/"""
    extra = dest.extra_config or {}
    module = str(extra.get("rsync_module") or "").strip("/")
    if not module:
        raise ValueError("Endpoint destinazione senza rsync_module configurato")
    user = str(extra.get("rsync_user") or dest.username)
    port = int(extra.get("rsync_port") or 873)
    rel = sanitize_path(src_path).strip("/")
    parts = [p for p in (dest_subpath.strip("/"), rel) if p]
    sub = "/".join(parts)
    return f"rsync://{user}@{dest.host}:{port}/{module}/{sub}/"


def build_remote_rsync_script(
    fs_src: str,
    dest_url: str,
    *,
    exclude_lines: list[str],
    delete_on_dest: bool,
    bandwidth_limit_kb: int | None,
) -> str:
    """Script eseguito via SSH sulla sorgente. Legge da stdin la password modulo."""
    parts = [
        "rsync",
        "-a",
        "--info=progress2",
        "--out-format=%i %n",
        "--partial-dir=.dapx-partial",
    ]
    for pattern in exclude_lines:
        parts.extend(["--exclude", shlex.quote(pattern)])
    if bandwidth_limit_kb:
        parts.append(f"--bwlimit={int(bandwidth_limit_kb)}")
    if delete_on_dest:
        parts.append("--delete-after")
    parts.append(shlex.quote(fs_src))
    parts.append(shlex.quote(dest_url))
    rsync_cmd = " ".join(parts)
    return (
        "IFS= read -r RSYNC_PASSWORD; export RSYNC_PASSWORD; "
        'echo "__DAPX_PID__$$"; '
        f"exec {rsync_cmd}"
    )


def build_ssh_argv(source: FileEndpoint) -> tuple[list[str], dict]:
    """argv per la sessione SSH dapx→sorgente + env extra. Mai password in argv."""
    port = _ssh_port(source)
    argv = ["ssh", "-p", str(port), "-o", "StrictHostKeyChecking=accept-new"]
    env: dict = {}
    if source.ssh_key_path:
        argv.extend(["-i", source.ssh_key_path, "-o", "BatchMode=yes"])
    else:
        password = decrypt_password(source.password_enc or "")
        if password:
            argv = ["sshpass", "-e", *argv]
            env["SSHPASS"] = password
    argv.append(f"{source.username}@{source.host}")
    return argv, env


def _eta_to_seconds(h: str, m: str, s: str) -> int:
    return int(h) * 3600 + int(m) * 60 + int(s)


def parse_rsync_line(line: str) -> SyncEvent | None:
    """Parsa una riga di output rsync (progress2, itemize %i %n, *deleting)."""
    text = line.rstrip("\r\n")
    if not text.strip():
        return None

    deleting = _DELETING_RE.match(text.strip())
    if deleting:
        return SyncEvent(files_deleted=1, last_file=deleting.group(1).strip(), raw_line=text)

    progress = _PROGRESS2_RE.match(text)
    if progress:
        return SyncEvent(
            phase="copying",
            bytes_done=int(progress.group(1).replace(",", "")),
            percent=int(progress.group(2)),
            speed=progress.group(3).replace(" ", ""),
            eta_seconds=_eta_to_seconds(progress.group(4), progress.group(5), progress.group(6)),
            raw_line=text,
        )

    itemize = _ITEMIZE_RE.match(text)
    if itemize:
        kind = itemize.group(1)
        flags = itemize.group(2)
        name = itemize.group(3).strip()
        if kind[1] != "f":  # directory, symlink, device: non contati
            return None
        if kind[0] not in "<>":
            return None
        if "+" in flags:
            return SyncEvent(phase="copying", files_new=1, last_file=name, raw_line=text)
        return SyncEvent(phase="copying", files_replaced=1, last_file=name, raw_line=text)

    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_nas_sync_direct_rsync.py -v`
Expected: 13 PASS

Se `test_source_fs_path_synology_volume` fallisce perché `normalize_synology_ssh_path` ha firma diversa: verificare con `grep -n "def normalize_synology_ssh_path" backend/services/file_replication/path_utils.py` e adattare SOLO la chiamata in `build_source_fs_path` (non il file path_utils).

- [ ] **Step 5: Commit**

```bash
git add backend/services/nas_sync/engine_direct_rsync.py backend/tests/test_nas_sync_direct_rsync.py
git commit -m "feat(nas-sync): builder comandi e parser output motore diretto rsync"
```

---

### Task 5: Motore diretto — runner SSH, cattura PID, stop remoto

**Files:**
- Modify: `backend/services/nas_sync/engine_direct_rsync.py` (append in coda al file del Task 4)
- Test: `backend/tests/test_nas_sync_direct_rsync_runner.py`

**Interfaces:**
- Consumes: builder/parser Task 4, `SyncEvent` Task 3.
- Produces (append allo stesso modulo):
  - `class EngineError(RuntimeError)` con attributo `exit_code: int | None`
  - `class EngineCancelled(Exception)`
  - `@dataclass StepResult: output_lines: list[str]; exit_code: int; warnings: list[str]; remote_pid: int | None`
  - `async run_direct_rsync(source, dest, src_path, dest_subpath, *, exclude_lines, delete_on_dest, bandwidth_limit_kb, on_event, cancel_check, process_registry, argv_override=None) -> StepResult`
    - `on_event: Callable[[SyncEvent], None] | None`; `cancel_check: Callable[[], bool] | None`
    - `argv_override`: SOLO per test — sostituisce interamente l'argv (ssh) del processo; lo script remoto viene comunque appeso come ultimo argomento
  - `async kill_remote_rsync(source, pid: int) -> bool`

- [ ] **Step 1: Write the failing test**

```python
"""Test runner motore diretto con processo locale simulato (bash al posto di ssh)."""

import asyncio

import pytest

from database import FileEndpoint, FileEndpointType
from services.nas_sync.engine_direct_rsync import (
    EngineCancelled,
    EngineError,
    run_direct_rsync,
)


def _src():
    return FileEndpoint(
        name="s", endpoint_type=FileEndpointType.SYNOLOGY, host="10.0.0.1",
        port=5001, protocol="api", username="admin", password_enc=None,
        ssh_key_path="/tmp/fake_key", extra_config={},
    )


def _dst():
    return FileEndpoint(
        name="d", endpoint_type=FileEndpointType.QNAP, host="10.0.0.2",
        port=8080, protocol="api", username="admin", password_enc=None,
        extra_config={"rsync_module": "DATI"},
    )


def _fake_ssh(body: str) -> list[str]:
    """argv che ignora lo script remoto appeso e esegue `body` in bash locale."""
    return ["bash", "-c", body, "fake-ssh"]


def test_runner_collects_events_and_pid():
    events = []
    fake = _fake_ssh(
        'read -r _pw; echo "__DAPX_PID__4242"; '
        "echo '>f+++++++++ docs/a.txt'; echo '>f.st...... docs/b.txt'; exit 0"
    )
    result = asyncio.run(
        run_direct_rsync(
            _src(), _dst(), "/Condivisa/docs", "",
            exclude_lines=[], delete_on_dest=False, bandwidth_limit_kb=None,
            on_event=events.append, cancel_check=None, process_registry=[],
            argv_override=fake,
        )
    )
    assert result.exit_code == 0
    assert result.remote_pid == 4242
    assert sum(e.files_new for e in events) == 1
    assert sum(e.files_replaced for e in events) == 1


def test_runner_warning_exit_24_is_success_with_warning():
    fake = _fake_ssh('read -r _pw; echo "__DAPX_PID__1"; exit 24')
    result = asyncio.run(
        run_direct_rsync(
            _src(), _dst(), "/Condivisa/docs", "",
            exclude_lines=[], delete_on_dest=False, bandwidth_limit_kb=None,
            on_event=None, cancel_check=None, process_registry=[],
            argv_override=fake,
        )
    )
    assert result.exit_code == 24
    assert result.warnings


def test_runner_fatal_exit_raises_engine_error_with_hint():
    fake = _fake_ssh('read -r _pw; echo "__DAPX_PID__1"; echo "auth failed" >&2; exit 5')
    with pytest.raises(EngineError) as exc:
        asyncio.run(
            run_direct_rsync(
                _src(), _dst(), "/Condivisa/docs", "",
                exclude_lines=[], delete_on_dest=False, bandwidth_limit_kb=None,
                on_event=None, cancel_check=None, process_registry=[],
                argv_override=fake,
            )
        )
    assert exc.value.exit_code == 5
    assert "modulo rsync" in str(exc.value)


def test_runner_cancel_raises_cancelled():
    fake = _fake_ssh('read -r _pw; echo "__DAPX_PID__1"; sleep 30')
    with pytest.raises(EngineCancelled):
        asyncio.run(
            run_direct_rsync(
                _src(), _dst(), "/Condivisa/docs", "",
                exclude_lines=[], delete_on_dest=False, bandwidth_limit_kb=None,
                on_event=None, cancel_check=lambda: True, process_registry=[],
                argv_override=fake,
            )
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_nas_sync_direct_rsync_runner.py -v`
Expected: FAIL con ImportError (`run_direct_rsync` non definito)

- [ ] **Step 3: Write minimal implementation**

Append in coda a `backend/services/nas_sync/engine_direct_rsync.py`:

```python
import asyncio
import logging
import os
import signal
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_PID_MARKER = "__DAPX_PID__"


class EngineError(RuntimeError):
    """Errore fatale engine (exit code rsync mappato in RSYNC_EXIT_HINTS)."""

    def __init__(self, message: str, exit_code: int | None = None):
        super().__init__(message)
        self.exit_code = exit_code


class EngineCancelled(Exception):
    """Step interrotto su richiesta utente."""


@dataclass
class StepResult:
    output_lines: list[str] = field(default_factory=list)
    exit_code: int = 0
    warnings: list[str] = field(default_factory=list)
    remote_pid: int | None = None


def _module_password(dest: FileEndpoint) -> str:
    extra = dest.extra_config or {}
    enc = extra.get("rsync_password_enc") or ""
    if enc:
        return decrypt_password(enc)
    return ""


async def kill_remote_rsync(source: FileEndpoint, pid: int) -> bool:
    """Termina il process group rsync sulla sorgente via SSH. Best effort."""
    argv, env = build_ssh_argv(source)
    cmd = argv + [f"kill -TERM -- -{pid} 2>/dev/null || kill -TERM {pid} 2>/dev/null || true"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env={**os.environ, **env},
        )
        await asyncio.wait_for(proc.wait(), timeout=15)
        return proc.returncode == 0
    except (OSError, asyncio.TimeoutError):
        return False


async def _terminate_local(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is None and proc.pid:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()
        await asyncio.sleep(0.5)
        if proc.returncode is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()


async def run_direct_rsync(
    source: FileEndpoint,
    dest: FileEndpoint,
    src_path: str,
    dest_subpath: str,
    *,
    exclude_lines: list[str],
    delete_on_dest: bool,
    bandwidth_limit_kb: int | None,
    on_event: Optional[Callable[[SyncEvent], None]],
    cancel_check: Optional[Callable[[], bool]],
    process_registry: list,
    argv_override: list[str] | None = None,
) -> StepResult:
    """Esegue rsync sulla sorgente via SSH; stdout/stderr → SyncEvent via on_event."""
    fs_src = build_source_fs_path(source, src_path)
    dest_url = build_dest_rsync_url(dest, src_path, dest_subpath)
    script = build_remote_rsync_script(
        fs_src,
        dest_url,
        exclude_lines=exclude_lines,
        delete_on_dest=delete_on_dest,
        bandwidth_limit_kb=bandwidth_limit_kb,
    )
    if argv_override is not None:
        argv, env = list(argv_override), {}
    else:
        argv, env = build_ssh_argv(source)
    cmd = argv + [script]
    logger.info("nas_sync direct: rsync %s -> %s (via ssh %s)", fs_src, dest_url, source.host)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, **env},
        start_new_session=True,
    )
    process_registry.append(proc)
    assert proc.stdin is not None and proc.stdout is not None
    try:
        proc.stdin.write((_module_password(dest) + "\n").encode())
        await proc.stdin.drain()
        proc.stdin.close()
    except (BrokenPipeError, ConnectionResetError):
        pass

    result = StepResult()
    cancelled = False
    while True:
        if cancel_check and cancel_check() and not cancelled:
            cancelled = True
            if result.remote_pid:
                await kill_remote_rsync(source, result.remote_pid)
            await _terminate_local(proc)
            raise EngineCancelled("Step interrotto dall'utente")
        try:
            line_b = await asyncio.wait_for(proc.stdout.readline(), timeout=1.0)
        except asyncio.TimeoutError:
            if proc.returncode is not None:
                break
            continue
        if not line_b:
            break
        line = line_b.decode(errors="replace")
        result.output_lines.append(line)
        stripped = line.strip()
        if stripped.startswith(_PID_MARKER):
            try:
                result.remote_pid = int(stripped[len(_PID_MARKER):])
            except ValueError:
                pass
            continue
        event = parse_rsync_line(line)
        if event and on_event:
            on_event(event)

    await proc.wait()
    result.exit_code = proc.returncode or 0

    if result.exit_code in RSYNC_WARNING_EXITS:
        result.warnings.append(
            "rsync ha segnalato file saltati o spariti durante la copia "
            f"(exit {result.exit_code}): controllare il log per l'elenco."
        )
        return result
    if result.exit_code != 0:
        hint = RSYNC_EXIT_HINTS.get(
            result.exit_code, f"rsync terminato con codice {result.exit_code}."
        )
        tail = "".join(result.output_lines)[-1500:]
        raise EngineError(f"{hint}\n{tail}", exit_code=result.exit_code)
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_nas_sync_direct_rsync_runner.py tests/test_nas_sync_direct_rsync.py -v`
Expected: tutti PASS (runner + builder/parser)

- [ ] **Step 5: Commit**

```bash
git add backend/services/nas_sync/engine_direct_rsync.py backend/tests/test_nas_sync_direct_rsync_runner.py
git commit -m "feat(nas-sync): runner SSH motore diretto con PID remoto e stop"
```

---

### Task 6: Engine rclone SMB v2 (JSON log)

**Files:**
- Create: `backend/services/nas_sync/engine_rclone.py`
- Test: `backend/tests/test_nas_sync_engine_rclone.py`

**Interfaces:**
- Consumes: `SyncEvent`, `EngineError`, `EngineCancelled`, `StepResult` (riesporta da `engine_direct_rsync`), `decrypt_password`, `parse_synology_share_path` da `services.file_replication.path_utils` (funziona per qualsiasi path `/SHARE/sub`).
- Produces:
  - `build_rclone_config(source, dest) -> tuple[str, str, str]` — (path config temp 0600, nome remote src, nome remote dest); sezione `[nas2_source]`/`[nas2_dest]` tipo smb, con `domain =` se endpoint Windows con `domain` valorizzato
  - `build_rclone_cmd(src_remote_path, dest_remote_path, *, delete_on_dest, size_only, bandwidth_limit_kb, filter_file) -> list[str]` — include `--use-json-log`, `--stats 5s`, `-v`, `--modify-window 2s`, `--fast-list`; `sync --delete-after` se delete_on_dest altrimenti `copy --no-traverse`
  - `parse_rclone_json_line(line: str) -> SyncEvent | None`
  - `async run_rclone_step(source, dest, src_path, dest_base_path, *, delete_on_dest, size_only, bandwidth_limit_kb, filter_file, on_event, cancel_check, process_registry) -> StepResult`

- [ ] **Step 1: Write the failing test**

```python
"""Test engine rclone v2 (JSON log)."""

import json

from database import FileEndpoint, FileEndpointType
from services.nas_sync.engine_rclone import build_rclone_cmd, parse_rclone_json_line


def test_cmd_copy_mode_flags():
    cmd = build_rclone_cmd(
        "nas2_source:Share/docs", "nas2_dest:DATI/docs",
        delete_on_dest=False, size_only=False, bandwidth_limit_kb=None, filter_file=None,
    )
    assert cmd[0] == "rclone"
    assert cmd[1] == "copy"
    assert "--no-traverse" in cmd
    assert "--use-json-log" in cmd
    assert "--delete-after" not in cmd


def test_cmd_sync_mode_with_delete_and_bwlimit():
    cmd = build_rclone_cmd(
        "nas2_source:Share", "nas2_dest:DATI",
        delete_on_dest=True, size_only=True, bandwidth_limit_kb=2048, filter_file="/tmp/f.txt",
    )
    assert cmd[1] == "sync"
    assert "--delete-after" in cmd
    assert "--size-only" in cmd
    assert "--bwlimit" in cmd and "2048K" in cmd
    assert "--filter-from" in cmd and "/tmp/f.txt" in cmd


def test_parse_copied_new():
    line = json.dumps({"level": "info", "msg": "Copied (new)", "object": "docs/a.txt"})
    ev = parse_rclone_json_line(line)
    assert ev.files_new == 1
    assert ev.last_file == "docs/a.txt"


def test_parse_copied_replaced():
    line = json.dumps({"level": "info", "msg": "Copied (replaced existing)", "object": "b.txt"})
    ev = parse_rclone_json_line(line)
    assert ev.files_replaced == 1


def test_parse_unchanged_skipped():
    line = json.dumps({"level": "info", "msg": "Unchanged skipping", "object": "c.txt"})
    ev = parse_rclone_json_line(line)
    assert ev.files_skipped == 1


def test_parse_deleted():
    line = json.dumps({"level": "info", "msg": "Deleted", "object": "old.txt"})
    ev = parse_rclone_json_line(line)
    assert ev.files_deleted == 1


def test_parse_stats_block():
    line = json.dumps({
        "level": "info", "msg": "...",
        "stats": {"bytes": 1048576, "totalBytes": 4194304, "speed": 2097152.0,
                  "eta": 90, "transfers": 3, "totalTransfers": 12},
    })
    ev = parse_rclone_json_line(line)
    assert ev.bytes_done == 1048576
    assert ev.bytes_total == 4194304
    assert ev.percent == 25
    assert ev.eta_seconds == 90
    assert ev.speed == "2.0 MiB/s"


def test_parse_non_json_returns_none():
    assert parse_rclone_json_line("not json at all") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_nas_sync_engine_rclone.py -v`
Expected: FAIL con ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

`backend/services/nas_sync/engine_rclone.py`:

```python
"""Engine rclone SMB↔SMB v2: output JSON strutturato, sorgente/destinazione generiche.

Usato quando il motore diretto non è disponibile (tipicamente sorgente Windows).
I dati transitano dal container dapx (limite noto e documentato).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import tempfile
from typing import Callable, Optional

from database import FileEndpoint, FileEndpointType
from services.file_replication.endpoint_crypto import decrypt_password
from services.file_replication.path_utils import parse_synology_share_path
from services.nas_sync.engine_direct_rsync import (
    EngineCancelled,
    EngineError,
    StepResult,
)
from services.nas_sync.events import SyncEvent, human_bytes

logger = logging.getLogger(__name__)


def _obscure(password: str) -> str:
    import subprocess

    proc = subprocess.run(
        ["rclone", "obscure", password], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise EngineError(f"rclone obscure fallito: {proc.stderr.strip()}")
    return proc.stdout.strip()


def build_rclone_config(source: FileEndpoint, dest: FileEndpoint) -> tuple[str, str, str]:
    spass = decrypt_password(source.password_enc or "")
    dpass = decrypt_password(dest.password_enc or "")
    if not spass or not dpass:
        raise EngineError("Password mancante su endpoint sorgente o destinazione (SMB)")

    fd, cfg_path = tempfile.mkstemp(prefix="dapx-nas2-rclone-", suffix=".conf")
    os.close(fd)
    os.chmod(cfg_path, 0o600)

    def _section(name: str, ep: FileEndpoint, password: str) -> str:
        lines = [
            f"[{name}]",
            "type = smb",
            f"host = {ep.host}",
            f"user = {ep.username}",
            f"pass = {_obscure(password)}",
            "use_signing = false",
            "use_server_modtime = true",
        ]
        if ep.endpoint_type == FileEndpointType.WINDOWS and ep.domain:
            lines.append(f"domain = {ep.domain}")
        return "\n".join(lines) + "\n"

    content = _section("nas2_source", source, spass) + "\n" + _section("nas2_dest", dest, dpass)
    with open(cfg_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return cfg_path, "nas2_source", "nas2_dest"


def build_rclone_cmd(
    src_remote_path: str,
    dest_remote_path: str,
    *,
    delete_on_dest: bool,
    size_only: bool,
    bandwidth_limit_kb: int | None,
    filter_file: str | None,
) -> list[str]:
    cmd = [
        "rclone",
        "sync" if delete_on_dest else "copy",
        src_remote_path,
        dest_remote_path,
        "--create-empty-src-dirs",
        "--modify-window", "2s",
        "--fast-list",
        "--use-json-log",
        "--stats", "5s",
        "-v",
    ]
    if delete_on_dest:
        cmd.append("--delete-after")
    else:
        cmd.append("--no-traverse")
    if size_only:
        cmd.append("--size-only")
    if bandwidth_limit_kb:
        cmd.extend(["--bwlimit", f"{int(bandwidth_limit_kb)}K"])
    if filter_file:
        cmd.extend(["--filter-from", filter_file, "--ignore-case"])
    return cmd


def parse_rclone_json_line(line: str) -> SyncEvent | None:
    text = line.strip()
    if not text.startswith("{"):
        return None
    try:
        obj = json.loads(text)
    except ValueError:
        return None

    msg = str(obj.get("msg") or "")
    target = obj.get("object")
    if target:
        if msg.startswith("Copied (new)"):
            return SyncEvent(phase="copying", files_new=1, last_file=str(target), raw_line=text)
        if msg.startswith("Copied"):
            return SyncEvent(phase="copying", files_replaced=1, last_file=str(target), raw_line=text)
        if msg.startswith("Unchanged skipping") or "Updated modification time" in msg:
            return SyncEvent(files_skipped=1, last_file=str(target), raw_line=text)
        if msg.startswith("Deleted"):
            return SyncEvent(files_deleted=1, last_file=str(target), raw_line=text)

    stats = obj.get("stats")
    if isinstance(stats, dict):
        bytes_done = int(stats.get("bytes") or 0)
        bytes_total = int(stats.get("totalBytes") or 0) or None
        percent = None
        if bytes_total:
            percent = min(100, int(bytes_done * 100 / bytes_total))
        speed = None
        if stats.get("speed"):
            speed = f"{human_bytes(int(float(stats['speed'])))}/s"
        eta = stats.get("eta")
        return SyncEvent(
            phase="copying" if bytes_done else "scanning",
            bytes_done=bytes_done or None,
            bytes_total=bytes_total,
            percent=percent,
            speed=speed,
            eta_seconds=int(eta) if eta is not None else None,
            raw_line=text,
        )
    return None


async def run_rclone_step(
    source: FileEndpoint,
    dest: FileEndpoint,
    src_path: str,
    dest_base_path: str,
    *,
    delete_on_dest: bool,
    size_only: bool,
    bandwidth_limit_kb: int | None,
    filter_file: str | None,
    on_event: Optional[Callable[[SyncEvent], None]],
    cancel_check: Optional[Callable[[], bool]],
    process_registry: list,
) -> StepResult:
    cfg_path, src_name, dest_name = build_rclone_config(source, dest)
    share, subpath = parse_synology_share_path(src_path)
    src_remote = f"{src_name}:{share}/{subpath}" if subpath else f"{src_name}:{share}"
    rel = src_path.strip("/")
    dest_share, dest_sub = parse_synology_share_path("/" + dest_base_path.strip("/"))
    dest_parts = [p for p in (dest_sub, rel) if p]
    dest_remote = f"{dest_name}:{dest_share}/" + "/".join(dest_parts)
    cmd = build_rclone_cmd(
        src_remote,
        dest_remote,
        delete_on_dest=delete_on_dest,
        size_only=size_only,
        bandwidth_limit_kb=bandwidth_limit_kb,
        filter_file=filter_file,
    )
    env = {**os.environ, "RCLONE_CONFIG": cfg_path}
    logger.info("nas_sync rclone: %s %s -> %s", cmd[1], src_remote, dest_remote)

    result = StepResult()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
        process_registry.append(proc)
        assert proc.stdout is not None
        while True:
            if cancel_check and cancel_check():
                if proc.returncode is None and proc.pid:
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        proc.terminate()
                raise EngineCancelled("Step interrotto dall'utente")
            try:
                line_b = await asyncio.wait_for(proc.stdout.readline(), timeout=1.0)
            except asyncio.TimeoutError:
                if proc.returncode is not None:
                    break
                continue
            if not line_b:
                break
            line = line_b.decode(errors="replace")
            result.output_lines.append(line)
            event = parse_rclone_json_line(line)
            if event and on_event:
                on_event(event)
        await proc.wait()
        result.exit_code = proc.returncode or 0
        if result.exit_code != 0:
            tail = "".join(result.output_lines)[-1500:]
            raise EngineError(f"rclone exit {result.exit_code}: {tail}", exit_code=result.exit_code)
        return result
    finally:
        try:
            os.unlink(cfg_path)
        except OSError:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_nas_sync_engine_rclone.py -v`
Expected: 8 PASS

Nota: `parse_synology_share_path` — verificare firma con `grep -n "def parse_synology_share_path" backend/services/file_replication/path_utils.py`; splitta `/SHARE/sub…` in `(share, sub)` per qualunque path, non solo Synology. Se solleva su path senza sottocartella, adeguare SOLO la chiamata qui.

- [ ] **Step 5: Commit**

```bash
git add backend/services/nas_sync/engine_rclone.py backend/tests/test_nas_sync_engine_rclone.py
git commit -m "feat(nas-sync): engine rclone SMB v2 con parsing JSON log"
```

---

### Task 7: Stato run (`run_state`): catalogo, checkpoint cartelle, pausa

**Files:**
- Create: `backend/services/nas_sync/state.py`
- Test: `backend/tests/test_nas_sync_state.py`

**Interfaces:**
- Produces (tutte funzioni pure su dict, tranne assign):
  - `get_run_state(job) -> dict` (copia difensiva, default `{}`)
  - `assign_run_state(job, state) -> None` (assegna + `flag_modified(job, "run_state")` per SQLAlchemy JSON)
  - `set_du_catalog(state, root: str, folders: list[dict], total_bytes: int, total_files: int | None, at_iso: str) -> dict` — folder dict: `{"path": str, "name": str, "bytes": int}`
  - `catalog_summary(state) -> dict` — chiavi `catalog_bytes_est`, `catalog_files_est`, `catalog_updated_at`, `catalog_folder_count`, `catalog_has_du` (per JobOut)
  - `pending_folders(state, root) -> list[dict]` — cartelle non ancora `done` per root
  - `mark_folder_done(state, root, folder_path) -> dict`
  - `reset_run_progress(state) -> dict` — azzera done/pausa, conserva catalogo
  - `save_pause(state, source_path: str, folder_path: str | None, last_file: str | None) -> dict`
  - `get_pause(state) -> dict | None`, `clear_pause(state) -> dict`

- [ ] **Step 1: Write the failing test**

```python
"""Test run_state nas_sync."""

from services.nas_sync.state import (
    catalog_summary,
    clear_pause,
    get_pause,
    mark_folder_done,
    pending_folders,
    reset_run_progress,
    save_pause,
    set_du_catalog,
)

FOLDERS = [
    {"path": "/SHARE/a", "name": "a", "bytes": 100},
    {"path": "/SHARE/b", "name": "b", "bytes": 200},
]


def test_catalog_roundtrip_and_summary():
    state = set_du_catalog({}, "/SHARE", FOLDERS, 300, 42, "2026-07-20T10:00:00")
    summary = catalog_summary(state)
    assert summary["catalog_bytes_est"] == 300
    assert summary["catalog_files_est"] == 42
    assert summary["catalog_folder_count"] == 2
    assert summary["catalog_has_du"] is True
    assert summary["catalog_updated_at"] == "2026-07-20T10:00:00"


def test_summary_empty_state():
    summary = catalog_summary({})
    assert summary["catalog_has_du"] is False
    assert summary["catalog_bytes_est"] is None


def test_pending_and_mark_done():
    state = set_du_catalog({}, "/SHARE", FOLDERS, 300, None, "t")
    assert [f["path"] for f in pending_folders(state, "/SHARE")] == ["/SHARE/a", "/SHARE/b"]
    state = mark_folder_done(state, "/SHARE", "/SHARE/a")
    assert [f["path"] for f in pending_folders(state, "/SHARE")] == ["/SHARE/b"]


def test_reset_keeps_catalog_clears_done():
    state = set_du_catalog({}, "/SHARE", FOLDERS, 300, None, "t")
    state = mark_folder_done(state, "/SHARE", "/SHARE/a")
    state = reset_run_progress(state)
    assert len(pending_folders(state, "/SHARE")) == 2
    assert catalog_summary(state)["catalog_has_du"] is True


def test_pause_roundtrip():
    state = save_pause({}, "/SHARE", "/SHARE/b", "b/file.txt")
    pause = get_pause(state)
    assert pause == {"source_path": "/SHARE", "folder_path": "/SHARE/b", "last_file": "b/file.txt"}
    state = clear_pause(state)
    assert get_pause(state) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_nas_sync_state.py -v`
Expected: FAIL con ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

`backend/services/nas_sync/state.py`:

```python
"""run_state del job v2: catalogo du, checkpoint per-cartella, pausa.

Struttura:
{
  "catalog": {"<root>": {"folders": [{"path","name","bytes"}...],
                          "total_bytes": int, "total_files": int|None,
                          "updated_at": iso}},
  "done": {"<root>": ["<folder_path>", ...]},
  "pause": {"source_path", "folder_path", "last_file"} | assente
}
"""

from __future__ import annotations

import copy

from sqlalchemy.orm.attributes import flag_modified


def get_run_state(job) -> dict:
    return copy.deepcopy(job.run_state or {})


def assign_run_state(job, state: dict) -> None:
    job.run_state = state
    flag_modified(job, "run_state")


def set_du_catalog(
    state: dict,
    root: str,
    folders: list[dict],
    total_bytes: int,
    total_files: int | None,
    at_iso: str,
) -> dict:
    s = copy.deepcopy(state)
    s.setdefault("catalog", {})[root] = {
        "folders": folders,
        "total_bytes": total_bytes,
        "total_files": total_files,
        "updated_at": at_iso,
    }
    return s


def catalog_summary(state: dict) -> dict:
    catalog = state.get("catalog") or {}
    if not catalog:
        return {
            "catalog_bytes_est": None,
            "catalog_files_est": None,
            "catalog_updated_at": None,
            "catalog_folder_count": None,
            "catalog_has_du": False,
        }
    total_bytes = sum(int(c.get("total_bytes") or 0) for c in catalog.values())
    files = [c.get("total_files") for c in catalog.values() if c.get("total_files")]
    folder_count = sum(len(c.get("folders") or []) for c in catalog.values())
    updated = max((c.get("updated_at") or "" for c in catalog.values()), default=None)
    return {
        "catalog_bytes_est": total_bytes,
        "catalog_files_est": sum(files) if files else None,
        "catalog_updated_at": updated or None,
        "catalog_folder_count": folder_count,
        "catalog_has_du": True,
    }


def pending_folders(state: dict, root: str) -> list[dict]:
    catalog = (state.get("catalog") or {}).get(root) or {}
    done = set((state.get("done") or {}).get(root) or [])
    return [f for f in (catalog.get("folders") or []) if f.get("path") not in done]


def mark_folder_done(state: dict, root: str, folder_path: str) -> dict:
    s = copy.deepcopy(state)
    done = s.setdefault("done", {}).setdefault(root, [])
    if folder_path not in done:
        done.append(folder_path)
    return s


def reset_run_progress(state: dict) -> dict:
    s = copy.deepcopy(state)
    s.pop("done", None)
    s.pop("pause", None)
    return s


def save_pause(state: dict, source_path: str, folder_path: str | None, last_file: str | None) -> dict:
    s = copy.deepcopy(state)
    s["pause"] = {
        "source_path": source_path,
        "folder_path": folder_path,
        "last_file": last_file,
    }
    return s


def get_pause(state: dict) -> dict | None:
    return state.get("pause") or None


def clear_pause(state: dict) -> dict:
    s = copy.deepcopy(state)
    s.pop("pause", None)
    return s
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_nas_sync_state.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/nas_sync/state.py backend/tests/test_nas_sync_state.py
git commit -m "feat(nas-sync): run_state con catalogo du, checkpoint cartelle e pausa"
```

---

### Task 8: Catalogo du via SSH (generico, non solo Synology)

**Files:**
- Create: `backend/services/nas_sync/du_catalog.py`
- Test: `backend/tests/test_nas_sync_du_catalog.py`

**Interfaces:**
- Consumes: `build_ssh_argv`, `build_source_fs_path` (Task 4), `state.set_du_catalog` (Task 7), `NasSyncJob` (Task 1), `SessionLocal` da `database`.
- Produces:
  - `parse_du_output(text: str, fs_root: str, src_root: str) -> tuple[list[dict], int]` — folders + total_bytes; converte i path filesystem (`/volume1/SHARE/x`) in path logici (`/SHARE/x`)
  - `build_du_script(fs_root: str) -> str` — comando remoto: `du -sb` del root + prime-level dirs escludendo `@*`/`#*`/`.*`
  - `async refresh_job_du_catalog(job_id: int) -> None` (task asincrono, aggiorna `run_state` e stato)
  - `get_catalog_progress(job_id) -> dict | None`, `is_catalog_refresh_running(job_id) -> bool`

- [ ] **Step 1: Write the failing test**

```python
"""Test parser catalogo du nas_sync."""

from services.nas_sync.du_catalog import build_du_script, parse_du_output


def test_build_du_script_excludes_system_dirs():
    script = build_du_script("/volume1/Condivisa/")
    assert "du -sb" in script
    assert "! -name '@*'" in script
    assert "! -name '#*'" in script
    assert "maxdepth 1" in script


def test_parse_du_output_maps_fs_to_logical_paths():
    text = (
        "524288000\t/volume1/Condivisa\n"
        "104857600\t/volume1/Condivisa/Progetti\n"
        "209715200\t/volume1/Condivisa/Archivio\n"
    )
    folders, total = parse_du_output(text, "/volume1/Condivisa/", "/Condivisa")
    assert total == 524288000
    assert folders == [
        {"path": "/Condivisa/Progetti", "name": "Progetti", "bytes": 104857600},
        {"path": "/Condivisa/Archivio", "name": "Archivio", "bytes": 209715200},
    ]


def test_parse_du_output_ignores_malformed_lines():
    folders, total = parse_du_output("garbage\n123\n", "/volume1/X/", "/X")
    assert folders == []
    assert total == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_nas_sync_du_catalog.py -v`
Expected: FAIL con ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

`backend/services/nas_sync/du_catalog.py`:

```python
"""Catalogo dimensioni per-cartella (du -sb via SSH sulla sorgente) — job separato dalla replica."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

from database import FileEndpoint, SessionLocal
from services.file_replication.path_utils import sanitize_path
from services.nas_sync.engine_direct_rsync import build_source_fs_path, build_ssh_argv
from services.nas_sync.models import NasSyncJob
from services.nas_sync.state import assign_run_state, get_run_state, set_du_catalog

logger = logging.getLogger(__name__)

_catalog_running: set[int] = set()
_catalog_progress: dict[int, dict] = {}


def is_catalog_refresh_running(job_id: int) -> bool:
    return job_id in _catalog_running


def get_catalog_progress(job_id: int) -> dict | None:
    return _catalog_progress.get(job_id)


def build_du_script(fs_root: str) -> str:
    root = fs_root.rstrip("/")
    return (
        f"du -sb '{root}' 2>/dev/null; "
        f"find '{root}' -mindepth 1 -maxdepth 1 -type d "
        "! -name '@*' ! -name '#*' ! -name '.*' -print0 2>/dev/null "
        "| xargs -0 -r -n1 du -sb 2>/dev/null"
    )


def parse_du_output(text: str, fs_root: str, src_root: str) -> tuple[list[dict], int]:
    root = fs_root.rstrip("/")
    logical_root = sanitize_path(src_root).rstrip("/")
    folders: list[dict] = []
    total = 0
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        try:
            size = int(parts[0].strip())
        except ValueError:
            continue
        path = parts[1].strip().rstrip("/")
        if path == root:
            total = size
            continue
        if not path.startswith(root + "/"):
            continue
        rel = path[len(root) + 1 :]
        if "/" in rel:
            continue  # solo primo livello
        folders.append({"path": f"{logical_root}/{rel}", "name": rel, "bytes": size})
    return folders, total


async def refresh_job_du_catalog(job_id: int) -> None:
    if job_id in _catalog_running:
        return
    _catalog_running.add(job_id)
    _catalog_progress[job_id] = {"status": "running", "message": "Catalogo du in corso…"}
    db = SessionLocal()
    try:
        job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
        if not job:
            return
        source = db.query(FileEndpoint).filter(FileEndpoint.id == job.source_endpoint_id).first()
        if not source:
            _catalog_progress[job_id] = {"status": "failed", "error": "Endpoint sorgente mancante"}
            return
        state = get_run_state(job)
        argv, env = build_ssh_argv(source)
        for src_path in job.source_paths or []:
            fs_root = build_source_fs_path(source, src_path)
            script = build_du_script(fs_root)
            proc = await asyncio.create_subprocess_exec(
                *argv,
                script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env={**os.environ, **env},
            )
            out_b, _ = await asyncio.wait_for(proc.communicate(), timeout=3600)
            folders, total = parse_du_output(
                out_b.decode(errors="replace"), fs_root, src_path
            )
            state = set_du_catalog(
                state, sanitize_path(src_path), folders, total, None,
                datetime.utcnow().isoformat(timespec="seconds"),
            )
            _catalog_progress[job_id] = {
                "status": "running",
                "message": f"Catalogo aggiornato: {src_path}",
            }
        assign_run_state(job, state)
        db.commit()
        _catalog_progress[job_id] = {"status": "success", "message": "Catalogo du aggiornato"}
    except Exception as exc:  # noqa: BLE001 — task fire-and-forget, errore in progress
        logger.error("nas_sync du catalog %s fallito: %s", job_id, exc, exc_info=True)
        _catalog_progress[job_id] = {"status": "failed", "error": str(exc)}
    finally:
        _catalog_running.discard(job_id)
        db.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_nas_sync_du_catalog.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/nas_sync/du_catalog.py backend/tests/test_nas_sync_du_catalog.py
git commit -m "feat(nas-sync): catalogo du via SSH generico per-cartella"
```

---

### Task 9: Preflight prerequisiti

**Files:**
- Create: `backend/services/nas_sync/preflight.py`
- Test: `backend/tests/test_nas_sync_preflight.py`

**Interfaces:**
- Consumes: `resolve_engine`, `ENGINE_DIRECT`, `ENGINE_RCLONE` (Task 2), `build_ssh_argv` (Task 4).
- Produces:
  - `async run_preflight(job, source, dest, *, ssh_runner=None) -> list[dict]` — lista `{"check": str, "ok": bool, "message": str, "hint": str | None}`; primo elemento sempre `{"check": "engine", …}` col motore risolto.
  - `ssh_runner` (solo test): `async def runner(argv: list[str], env: dict, script: str, timeout: int) -> tuple[int, str]` che rimpiazza l'esecuzione SSH reale.
  - Check per motore diretto: `engine`, `ssh_source`, `rsync_source`, `dest_port`, `dest_module`. Per rclone: `engine`, `rclone_binary`.

- [ ] **Step 1: Write the failing test**

```python
"""Test preflight nas_sync con runner SSH finto."""

import asyncio

from database import FileEndpoint, FileEndpointType
from services.nas_sync.models import NasSyncJob
from services.nas_sync.preflight import run_preflight


def _src():
    return FileEndpoint(
        name="s", endpoint_type=FileEndpointType.SYNOLOGY, host="10.0.0.1", port=5001,
        protocol="api", username="admin", password_enc="enc", extra_config={},
    )


def _dst():
    return FileEndpoint(
        name="d", endpoint_type=FileEndpointType.QNAP, host="10.0.0.2", port=8080,
        protocol="api", username="admin", password_enc="enc",
        extra_config={"rsync_module": "DATI", "rsync_password_enc": "enc", "rsync_port": 873},
    )


def _job(method="auto"):
    return NasSyncJob(
        name="j", source_endpoint_id=1, dest_endpoint_id=2,
        source_paths=["/Condivisa/docs"], dest_base_path="", sync_method=method,
    )


def test_preflight_all_ok():
    async def runner(argv, env, script, timeout):
        if "rsync --version" in script:
            return 0, "rsync  version 3.2.7"
        return 0, "ok"

    checks = asyncio.run(run_preflight(_job(), _src(), _dst(), ssh_runner=runner))
    by_name = {c["check"]: c for c in checks}
    assert by_name["engine"]["ok"] is True
    assert "direct" in by_name["engine"]["message"]
    assert by_name["ssh_source"]["ok"] is True
    assert by_name["rsync_source"]["ok"] is True
    assert by_name["dest_port"]["ok"] is True
    assert by_name["dest_module"]["ok"] is True


def test_preflight_ssh_failure_stops_dependent_checks():
    async def runner(argv, env, script, timeout):
        return 255, "Permission denied"

    checks = asyncio.run(run_preflight(_job(), _src(), _dst(), ssh_runner=runner))
    by_name = {c["check"]: c for c in checks}
    assert by_name["ssh_source"]["ok"] is False
    assert by_name["ssh_source"]["hint"]
    assert "rsync_source" not in by_name  # non eseguito senza SSH


def test_preflight_rclone_engine_checks_binary():
    src = FileEndpoint(
        name="w", endpoint_type=FileEndpointType.WINDOWS, host="10.0.0.3", port=445,
        protocol="smb", username="u", password_enc="enc", extra_config={},
    )
    checks = asyncio.run(run_preflight(_job(), src, _dst(), ssh_runner=None))
    by_name = {c["check"]: c for c in checks}
    assert by_name["engine"]["ok"] is True
    assert "rclone" in by_name["engine"]["message"]
    assert "rclone_binary" in by_name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_nas_sync_preflight.py -v`
Expected: FAIL con ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

`backend/services/nas_sync/preflight.py`:

```python
"""Verifica prerequisiti prima del run: SSH, rsync, porta/modulo destinazione."""

from __future__ import annotations

import asyncio
import os
import shutil

from database import FileEndpoint
from services.nas_sync.capabilities import ENGINE_DIRECT, resolve_engine
from services.nas_sync.engine_direct_rsync import build_ssh_argv


async def _default_ssh_runner(argv: list[str], env: dict, script: str, timeout: int) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, **env},
    )
    try:
        out_b, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "timeout"
    return proc.returncode or 0, out_b.decode(errors="replace")


async def run_preflight(job, source: FileEndpoint, dest: FileEndpoint, *, ssh_runner=None) -> list[dict]:
    checks: list[dict] = []
    runner = ssh_runner or _default_ssh_runner

    try:
        engine, reason = resolve_engine(job.sync_method or "auto", source, dest)
    except ValueError as exc:
        checks.append({"check": "engine", "ok": False, "message": str(exc), "hint": None})
        return checks
    checks.append({"check": "engine", "ok": True, "message": f"Motore: {engine} — {reason}", "hint": None})

    if engine != ENGINE_DIRECT:
        has_rclone = bool(shutil.which("rclone"))
        checks.append({
            "check": "rclone_binary",
            "ok": has_rclone,
            "message": "rclone presente sul server dapx" if has_rclone else "rclone non installato",
            "hint": None if has_rclone else "Installare con: apt install rclone",
        })
        return checks

    argv, env = build_ssh_argv(source)

    code, out = await runner(argv, env, "echo dapx-ok", 20)
    ok = code == 0 and "dapx-ok" in out
    checks.append({
        "check": "ssh_source",
        "ok": ok,
        "message": "SSH sorgente raggiungibile" if ok else f"SSH sorgente fallito: {out.strip()[:200]}",
        "hint": None if ok else "Verifica servizio SSH attivo sul NAS sorgente, porta e credenziali (o installa la chiave dapx).",
    })
    if not ok:
        return checks

    code, out = await runner(argv, env, "rsync --version 2>&1 | head -1", 20)
    ok = code == 0 and "rsync" in out.lower()
    checks.append({
        "check": "rsync_source",
        "ok": ok,
        "message": out.strip()[:120] if ok else "rsync non trovato sulla sorgente",
        "hint": None if ok else "Il NAS sorgente deve avere il binario rsync (di serie su Synology/QNAP).",
    })
    if not ok:
        return checks

    extra = dest.extra_config or {}
    port = int(extra.get("rsync_port") or 873)
    probe = (
        f"(command -v nc >/dev/null && nc -z -w 5 {dest.host} {port} && echo open) "
        f"|| (timeout 5 bash -c 'cat < /dev/null > /dev/tcp/{dest.host}/{port}' && echo open) "
        "|| echo closed"
    )
    code, out = await runner(argv, env, probe, 25)
    ok = "open" in out
    checks.append({
        "check": "dest_port",
        "ok": ok,
        "message": (
            f"Porta rsync {port} della destinazione raggiungibile dalla sorgente"
            if ok else f"Porta {port} non raggiungibile dalla sorgente"
        ),
        "hint": None if ok else "Attiva il servizio rsync sul NAS di destinazione e verifica firewall tra le due NAS.",
    })
    if not ok:
        return checks

    module = str(extra.get("rsync_module") or "")
    user = str(extra.get("rsync_user") or dest.username)
    list_cmd = (
        "IFS= read -r RSYNC_PASSWORD; export RSYNC_PASSWORD; "
        f"rsync --timeout=15 rsync://{user}@{dest.host}:{port}/{module}/ >/dev/null 2>&1 "
        "&& echo module-ok || echo module-fail"
    )
    code, out = await runner(argv, env, list_cmd, 30)
    ok = "module-ok" in out
    checks.append({
        "check": "dest_module",
        "ok": ok,
        "message": f"Modulo rsync «{module}» accessibile" if ok else f"Accesso al modulo «{module}» fallito",
        "hint": None if ok else "Verifica nome modulo, utente e password del servizio rsync sulla destinazione.",
    })
    return checks
```

Nota nota bene: il check `dest_module` esegue `IFS= read -r RSYNC_PASSWORD` — il runner reale deve scrivere la password su stdin. Per semplicità del preflight, questo check con il runner di default viene eseguito SENZA password su stdin (il read scade col timeout): accettabile in v1 del preflight se il modulo è senza auth; con auth attiva il check può risultare `module-fail` pur con config corretta. Mitigazione: nel runner di default aggiungere `stdin=asyncio.subprocess.PIPE` e scrivere `decrypt_password(extra.get("rsync_password_enc") or "") + "\n"` prima di `communicate()`. Implementarlo così da subito:

```python
# variante _default_ssh_runner con stdin_data opzionale
async def _default_ssh_runner(argv, env, script, timeout, stdin_data: str | None = None):
    proc = await asyncio.create_subprocess_exec(
        *argv, script,
        stdin=asyncio.subprocess.PIPE if stdin_data is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, **env},
    )
    try:
        out_b, _ = await asyncio.wait_for(
            proc.communicate(input=stdin_data.encode() if stdin_data is not None else None),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "timeout"
    return proc.returncode or 0, out_b.decode(errors="replace")
```

e nel check `dest_module` chiamare `runner(...)` passando la password via `stdin_data` SOLO se il runner è quello di default (i runner di test hanno firma a 4 argomenti: usare `inspect.signature` oppure — più semplice — definire il runner di default con firma `(argv, env, script, timeout, stdin_data=None)` e chiamarlo con 5 argomenti solo internamente; i runner di test ricevono sempre 4). Implementazione concreta: nel corpo di `run_preflight`, per il check modulo:

```python
    from services.file_replication.endpoint_crypto import decrypt_password
    module_password = decrypt_password(extra.get("rsync_password_enc") or "")
    if ssh_runner is None:
        code, out = await _default_ssh_runner(argv, env, list_cmd, 30, stdin_data=module_password + "\n")
    else:
        code, out = await runner(argv, env, list_cmd, 30)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_nas_sync_preflight.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/nas_sync/preflight.py backend/tests/test_nas_sync_preflight.py
git commit -m "feat(nas-sync): preflight prerequisiti con esiti e rimedi"
```

---

### Task 10: Orchestratore esecuzione + notifiche

**Files:**
- Create: `backend/services/nas_sync/execution.py`
- Create: `backend/services/nas_sync/notifications.py`
- Test: `backend/tests/test_nas_sync_execution.py`

**Interfaces:**
- Consumes: tutto quanto sopra; `JobLog`, `SessionLocal` da `database`; `build_exclude_lines` da `services.file_replication.exclude_presets` (per il motore diretto) e `build_rclone_filter_lines` (per engine rclone).
- Produces:
  - `async execute_nas_sync_job(job_id: int, *, fresh: bool = False) -> None`
  - `async stop_nas_sync_job(job_id: int) -> dict` — `{"ok": bool, "message": str}`
  - `get_job_progress(job_id) -> dict | None` (già passato da `build_view`)
  - `is_job_running(job_id) -> bool`, `is_job_busy(job_id) -> bool` (run o catalogo)
  - `reconcile_stale_running_jobs() -> int`
  - `notifications.notify_nas_sync_result(job, source, dest, *, status, duration, progress=None, error=None, is_scheduled=False) -> None` (async)
  - **Iniezione engine per test**: `execute_nas_sync_job` accetta kwarg `_engine_runner=None`: se valorizzato, sostituisce la chiamata engine con `await _engine_runner(step_ctx: dict)` che ritorna `StepResult`. `step_ctx` contiene `{"engine", "src_path", "folder_path", "dest_subpath"}`.

- [ ] **Step 1: Write the failing test**

```python
"""Test orchestratore nas_sync con engine finto e DB in memoria."""

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import database
from database import Base, FileEndpoint, FileEndpointType, JobLog
from services.nas_sync import execution
from services.nas_sync.engine_direct_rsync import EngineCancelled, StepResult
from services.nas_sync.models import NasSyncJob


@pytest.fixture()
def db_session(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    monkeypatch.setattr(execution, "SessionLocal", TestSession)
    db = TestSession()
    src = FileEndpoint(name="s", endpoint_type=FileEndpointType.SYNOLOGY, host="1", port=1,
                       protocol="api", username="u", password_enc="x", extra_config={})
    dst = FileEndpoint(name="d", endpoint_type=FileEndpointType.QNAP, host="2", port=1,
                       protocol="api", username="u", password_enc="x",
                       extra_config={"rsync_module": "DATI", "rsync_password_enc": "x"})
    db.add_all([src, dst])
    db.commit()
    job = NasSyncJob(name="j", source_endpoint_id=src.id, dest_endpoint_id=dst.id,
                     source_paths=["/Condivisa/docs"], dest_base_path="", sync_method="auto",
                     notify_mode="never")
    db.add(job)
    db.commit()
    yield db, TestSession, job.id
    db.close()


def test_success_run_updates_job_and_log(db_session):
    db, TestSession, job_id = db_session

    async def fake_engine(step_ctx):
        return StepResult(output_lines=["x"], exit_code=0)

    asyncio.run(execution.execute_nas_sync_job(job_id, _engine_runner=fake_engine))

    check = TestSession()
    job = check.query(NasSyncJob).get(job_id)
    assert job.last_run_status == "success"
    assert job.current_status == "idle"
    assert job.resolved_engine == "direct_rsync"
    log = check.query(JobLog).filter(JobLog.job_type == "nas_sync").first()
    assert log is not None and log.status == "success"
    check.close()


def test_engine_failure_marks_failed(db_session):
    db, TestSession, job_id = db_session

    async def fake_engine(step_ctx):
        raise RuntimeError("boom rete")

    asyncio.run(execution.execute_nas_sync_job(job_id, _engine_runner=fake_engine))
    check = TestSession()
    job = check.query(NasSyncJob).get(job_id)
    assert job.last_run_status == "failed"
    assert job.current_status == "failed"
    check.close()


def test_cancel_marks_paused_with_checkpoint(db_session):
    db, TestSession, job_id = db_session

    async def fake_engine(step_ctx):
        raise EngineCancelled("stop")

    asyncio.run(execution.execute_nas_sync_job(job_id, _engine_runner=fake_engine))
    check = TestSession()
    job = check.query(NasSyncJob).get(job_id)
    assert job.current_status == "paused"
    assert (job.run_state or {}).get("pause")
    check.close()


def test_double_run_guard(db_session):
    db, TestSession, job_id = db_session
    execution._running.add(job_id)
    try:
        asyncio.run(execution.execute_nas_sync_job(job_id))
        check = TestSession()
        job = check.query(NasSyncJob).get(job_id)
        assert job.last_run_status is None  # non ha girato
        check.close()
    finally:
        execution._running.discard(job_id)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_nas_sync_execution.py -v`
Expected: FAIL con ModuleNotFoundError

- [ ] **Step 3: Write implementation**

`backend/services/nas_sync/notifications.py`:

```python
"""Notifiche email risultato job Repliche dati (riusa email_service globale)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def notify_nas_sync_result(
    job,
    source,
    dest,
    *,
    status: str,
    duration: int,
    progress: dict | None = None,
    error: str | None = None,
    is_scheduled: bool = False,
) -> None:
    """Invia email secondo job.notify_mode (never|failure|always|daily)."""
    mode = (job.notify_mode or "never").lower()
    if mode == "never":
        return
    if mode == "failure" and status != "failed":
        return
    try:
        from services.email_service import email_service  # import pigro: SMTP opzionale

        subject = job.notify_subject or f"Repliche dati: {job.name}"
        outcome = "OK" if status == "success" else ("IN PAUSA" if status == "paused" else "ERRORE")
        lines = [
            f"Job: {job.name}",
            f"Esito: {outcome}",
            f"Sorgente: {source.name} ({source.host})",
            f"Destinazione: {dest.name} ({dest.host})",
            f"Durata: {duration}s",
        ]
        if progress and progress.get("display_summary"):
            lines.append(f"Riepilogo: {progress['display_summary']}")
        if error:
            lines.append(f"Errore: {error}")
        await email_service.send_notification(
            subject=f"[{outcome}] {subject}",
            body="\n".join(lines),
            category="nas_sync",
            status=status,
            daily_key=f"nas_sync_{job.id}" if mode == "daily" else None,
        )
    except Exception as exc:  # noqa: BLE001 — la notifica non deve rompere il run
        logger.warning("Notifica nas_sync %s non inviata: %s", job.id, exc)
```

ATTENZIONE: la firma esatta di `email_service.send_notification` va verificata con
`grep -n "def send" backend/services/email_service.py` e con come la usa
`backend/services/file_replication/file_replication_notifications.py` (leggerlo, NON modificarlo).
Adattare SOLO la chiamata qui dentro allo stesso pattern usato lì (stessi parametri/fallback);
se lì esiste una logica "daily" (max 1 OK/giorno), replicarla qui con chiave `nas_sync_{job.id}`.

`backend/services/nas_sync/execution.py`:

```python
"""Orchestratore esecuzione job Repliche dati: engine-agnostico, stato, pausa, log."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from database import FileEndpoint, JobLog, SessionLocal
from services.file_replication.exclude_presets import (
    build_rclone_filter_lines,
    build_rsync_exclude_lines,
)
from services.file_replication.path_utils import sanitize_path
from services.nas_sync.capabilities import ENGINE_DIRECT, resolve_engine
from services.nas_sync.du_catalog import is_catalog_refresh_running
from services.nas_sync.engine_direct_rsync import (
    EngineCancelled,
    EngineError,
    StepResult,
    kill_remote_rsync,
    run_direct_rsync,
)
from services.nas_sync.engine_rclone import run_rclone_step
from services.nas_sync.events import SyncEvent, apply_event, build_view
from services.nas_sync.models import NasSyncJob
from services.nas_sync.notifications import notify_nas_sync_result
from services.nas_sync.state import (
    assign_run_state,
    catalog_summary,
    clear_pause,
    get_pause,
    get_run_state,
    mark_folder_done,
    pending_folders,
    reset_run_progress,
    save_pause,
)

logger = logging.getLogger(__name__)

_running: set[int] = set()
_cancel_requested: set[int] = set()
_processes: dict[int, list] = {}
_remote_pids: dict[int, tuple[int, int]] = {}  # job_id -> (source_endpoint_id, pid)
_progress: dict[int, dict] = {}


def is_job_running(job_id: int) -> bool:
    return job_id in _running


def is_job_busy(job_id: int) -> bool:
    return job_id in _running or is_catalog_refresh_running(job_id)


def get_job_progress(job_id: int) -> Optional[dict]:
    return _progress.get(job_id)


def reconcile_stale_running_jobs() -> int:
    """All'avvio backend: job 'running' in DB senza run in memoria → paused."""
    db = SessionLocal()
    reset = 0
    try:
        jobs = db.query(NasSyncJob).filter(NasSyncJob.current_status == "running").all()
        for job in jobs:
            if job.id not in _running:
                job.current_status = "paused"
                job.last_run_status = "paused"
                reset += 1
        if reset:
            db.commit()
    finally:
        db.close()
    return reset


async def stop_nas_sync_job(job_id: int) -> dict:
    if job_id not in _running:
        return {"ok": False, "message": "Job non in esecuzione"}
    _cancel_requested.add(job_id)
    remote = _remote_pids.get(job_id)
    if remote:
        db = SessionLocal()
        try:
            source = db.query(FileEndpoint).filter(FileEndpoint.id == remote[0]).first()
            if source:
                await kill_remote_rsync(source, remote[1])
        finally:
            db.close()
    _progress[job_id] = {
        **(_progress.get(job_id) or {}),
        "status": "cancelling",
        "message": "Interruzione in corso…",
    }
    return {"ok": True, "message": "Interruzione richiesta"}


def _build_steps(job: NasSyncJob, run_state: dict) -> list[dict]:
    """Step di lavoro: per-cartella se il catalogo du esiste, altrimenti per source_path."""
    steps: list[dict] = []
    pause = get_pause(run_state)
    for src_path in job.source_paths or []:
        root = sanitize_path(src_path)
        folders = pending_folders(run_state, root)
        if folders:
            for folder in folders:
                steps.append({"src_path": folder["path"], "root": root,
                              "folder_path": folder["path"]})
        else:
            catalog_present = bool((run_state.get("catalog") or {}).get(root))
            done_all = catalog_present and not folders
            if done_all and not pause:
                continue  # tutte le cartelle già replicate in run precedente
            steps.append({"src_path": root, "root": root, "folder_path": None})
    if not steps and (job.source_paths or []):
        # catalogo completo ma nessun pending (es. resume completato): replica root per sicurezza delete
        for src_path in job.source_paths or []:
            root = sanitize_path(src_path)
            steps.append({"src_path": root, "root": root, "folder_path": None})
    return steps


async def _run_engine_step(
    engine: str,
    job: NasSyncJob,
    source: FileEndpoint,
    dest: FileEndpoint,
    step: dict,
    exclude_lines: list[str],
    filter_file: str | None,
    on_event,
    job_id: int,
) -> StepResult:
    if engine == ENGINE_DIRECT:
        result = await run_direct_rsync(
            source,
            dest,
            step["src_path"],
            (job.dest_base_path or "").strip(),
            exclude_lines=exclude_lines,
            delete_on_dest=bool(job.delete_on_dest),
            bandwidth_limit_kb=job.bandwidth_limit_kb,
            on_event=on_event,
            cancel_check=lambda: job_id in _cancel_requested,
            process_registry=_processes[job_id],
        )
        if result.remote_pid:
            _remote_pids[job_id] = (source.id, result.remote_pid)
        return result
    return await run_rclone_step(
        source,
        dest,
        step["src_path"],
        job.dest_base_path or "",
        delete_on_dest=bool(job.delete_on_dest),
        size_only=bool(job.rclone_size_only),
        bandwidth_limit_kb=job.bandwidth_limit_kb,
        filter_file=filter_file,
        on_event=on_event,
        cancel_check=lambda: job_id in _cancel_requested,
        process_registry=_processes[job_id],
    )


async def execute_nas_sync_job(job_id: int, *, fresh: bool = False, _engine_runner=None) -> None:
    if job_id in _running:
        logger.warning("NasSyncJob %s già in esecuzione", job_id)
        return
    _running.add(job_id)
    _cancel_requested.discard(job_id)
    _processes[job_id] = []
    _progress[job_id] = build_view({"status": "running", "phase": "starting"})
    started = datetime.utcnow()
    db = SessionLocal()
    log_row: Optional[JobLog] = None
    source: Optional[FileEndpoint] = None
    dest: Optional[FileEndpoint] = None
    current_step: dict = {}
    progress_state: dict = {}
    warnings: list[str] = []
    output_tail: list[str] = []
    filter_path: Optional[str] = None

    try:
        job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
        if not job:
            logger.error("NasSyncJob %s non trovato", job_id)
            return
        source = db.query(FileEndpoint).filter(FileEndpoint.id == job.source_endpoint_id).first()
        dest = db.query(FileEndpoint).filter(FileEndpoint.id == job.dest_endpoint_id).first()
        if not source or not dest:
            raise RuntimeError("Endpoint sorgente o destinazione mancante")

        engine, reason = resolve_engine(job.sync_method or "auto", source, dest)
        job.resolved_engine = engine
        job.current_status = "running"
        db.commit()

        log_row = JobLog(
            job_type="nas_sync",
            job_id=job.id,
            node_name=dest.name,
            dataset=job.dest_base_path,
            status="started",
            message=f"Avvio replica dati: {job.name} [{engine}]",
        )
        db.add(log_row)
        db.commit()

        exclude_lines = build_rsync_exclude_lines(
            job.exclude_presets or [], job.exclude_patterns or []
        )
        if engine != ENGINE_DIRECT:
            import os
            import tempfile

            filter_lines = build_rclone_filter_lines(
                job.exclude_presets or [], job.exclude_patterns or []
            )
            fd, filter_path = tempfile.mkstemp(prefix="dapx-nas2-filter-", suffix=".txt")
            with os.fdopen(fd, "w") as fh:
                fh.write("\n".join(filter_lines) + "\n")

        run_state = get_run_state(job)
        if fresh:
            run_state = reset_run_progress(run_state)
            assign_run_state(job, run_state)
            db.commit()
        run_state = clear_pause(run_state)

        def on_event(ev: SyncEvent) -> None:
            nonlocal progress_state
            progress_state = apply_event(progress_state, ev)
            view = build_view(progress_state)
            view["status"] = "running"
            view.update(catalog_summary(run_state))
            if current_step.get("folder_path"):
                view["current_folder_path"] = current_step["folder_path"]
                view["current_folder_name"] = current_step["folder_path"].rsplit("/", 1)[-1]
            _progress[job_id] = view

        steps = _build_steps(job, run_state)
        for step in steps:
            current_step.clear()
            current_step.update(step)
            if job_id in _cancel_requested:
                raise EngineCancelled("Interrotto dall'utente")
            if _engine_runner is not None:
                result = await _engine_runner(
                    {"engine": engine, "src_path": step["src_path"],
                     "folder_path": step["folder_path"],
                     "dest_subpath": job.dest_base_path or ""}
                )
            else:
                result = await _run_engine_step(
                    engine, job, source, dest, step, exclude_lines, filter_path,
                    on_event, job_id,
                )
            warnings.extend(result.warnings)
            output_tail.extend(result.output_lines[-200:])
            if step["folder_path"]:
                run_state = mark_folder_done(run_state, step["root"], step["folder_path"])
                assign_run_state(job, run_state)
                db.commit()

        duration = int((datetime.utcnow() - started).total_seconds())
        final_view = build_view(progress_state)
        job.last_run_at = datetime.utcnow()
        job.last_run_status = "success"
        job.last_run_duration_sec = duration
        job.last_bytes_transferred = int(progress_state.get("bytes_done") or 0)
        job.last_files_transferred = int(progress_state.get("files_copied") or 0)
        job.current_status = "idle"
        run_state = reset_run_progress(run_state)
        assign_run_state(job, run_state)
        db.commit()

        if log_row:
            summary = final_view.get("display_summary") or f"Replica completata in {duration}s"
            if warnings:
                summary += " — con avvisi"
            log_row.status = "success"
            log_row.message = summary
            log_row.output = ("\n".join(warnings) + "\n\n" if warnings else "") + "".join(output_tail)[-45000:]
            log_row.duration = duration
            log_row.completed_at = datetime.utcnow()
            db.commit()

        _progress[job_id] = {**final_view, "status": "success", "warnings": warnings}
        await notify_nas_sync_result(
            job, source, dest, status="success", duration=duration,
            progress=final_view, is_scheduled=bool(job.schedule),
        )

    except EngineCancelled:
        duration = int((datetime.utcnow() - started).total_seconds())
        job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
        if job:
            run_state = get_run_state(job)
            run_state = save_pause(
                run_state,
                current_step.get("root") or (job.source_paths or [""])[0],
                current_step.get("folder_path"),
                progress_state.get("last_file"),
            )
            assign_run_state(job, run_state)
            job.last_run_at = datetime.utcnow()
            job.last_run_status = "paused"
            job.last_run_duration_sec = duration
            job.current_status = "paused"
        if log_row:
            log_row.status = "cancelled"
            log_row.message = "Replica messa in pausa dall'utente"
            log_row.duration = duration
            log_row.completed_at = datetime.utcnow()
        db.commit()
        _progress[job_id] = {
            **build_view(progress_state),
            "status": "paused",
            "message": "In pausa — riprendi dal checkpoint salvato",
        }
    except Exception as exc:  # noqa: BLE001 — qualunque errore chiude il run come failed
        logger.error("NasSyncJob %s fallito: %s", job_id, exc, exc_info=True)
        duration = int((datetime.utcnow() - started).total_seconds())
        err_text = str(exc)
        job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
        if job:
            job.last_run_at = datetime.utcnow()
            job.last_run_status = "failed"
            job.last_run_duration_sec = duration
            job.current_status = "failed"
        if log_row:
            log_row.status = "failed"
            log_row.error = err_text
            log_row.duration = duration
            log_row.completed_at = datetime.utcnow()
        elif job:
            db.add(JobLog(
                job_type="nas_sync", job_id=job_id,
                node_name=dest.name if dest else None,
                dataset=job.dest_base_path, status="failed",
                message=f"Replica fallita: {job.name}", error=err_text,
                duration=duration, completed_at=datetime.utcnow(),
            ))
        db.commit()
        _progress[job_id] = {"status": "failed", "error": err_text}
        if job and source and dest:
            await notify_nas_sync_result(
                job, source, dest, status="failed", duration=duration,
                error=err_text, is_scheduled=bool(job.schedule),
            )
    finally:
        import os as _os

        _cancel_requested.discard(job_id)
        _processes.pop(job_id, None)
        _remote_pids.pop(job_id, None)
        if filter_path:
            try:
                _os.unlink(filter_path)
            except OSError:
                pass
        _running.discard(job_id)
        db.close()
```

ATTENZIONE per l'implementatore:
- `db.query(NasSyncJob).get(id)` è legacy SQLAlchemy: nei test va bene, nel codice usare `.filter(...).first()` come sopra.
- `JobLog`: verificare i nomi campo con `grep -n "class JobLog" -A 25 backend/database.py`; se `started_at`/`transferred` esistono con altri nomi, adattare SOLO qui.
- NON usare `conn.begin()` espliciti (SQLAlchemy 2.x autobegin — vedi CLAUDE.md).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_nas_sync_execution.py -v`
Expected: 4 PASS

- [ ] **Step 5: Run whole nas_sync suite**

Run: `cd backend && ./venv/bin/python -m pytest tests/ -k nas_sync -v`
Expected: tutti PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/nas_sync/execution.py backend/services/nas_sync/notifications.py backend/tests/test_nas_sync_execution.py
git commit -m "feat(nas-sync): orchestratore esecuzione engine-agnostico con pausa e notifiche"
```

---

### Task 11: Schemi Pydantic + Router `/api/nas-sync` + registrazioni

**Files:**
- Create: `backend/services/nas_sync/schemas.py`
- Create: `backend/routers/nas_sync_jobs.py`
- Modify: `backend/main.py` (2 righe additive)
- Modify: `backend/services/scheduler.py` (blocchi additivi)
- Test: `backend/tests/test_nas_sync_router.py`

**Interfaces:**
- Consumes: tutto il package `services/nas_sync`; `get_current_user`, `require_operator` da `routers.auth`.
- Produces: router FastAPI `router` in `routers.nas_sync_jobs`; rotte: `GET/POST ""`, `GET/PUT/DELETE /{job_id}`, `POST /{job_id}/run?fresh=`, `POST /{job_id}/stop`, `POST /{job_id}/toggle`, `GET /{job_id}/logs`, `GET /{job_id}/progress`, `POST /{job_id}/refresh-catalog`, `POST /{job_id}/preflight`, `GET /stats/summary`, `GET /endpoints/{endpoint_id}/capabilities`.
- Scheduler: metodi `update_nas_sync_schedule(job_id, schedule, last_run=None)`, `remove_nas_sync_schedule(job_id)`, coroutine `_execute_nas_sync_job(job_id)`, blocco tick `=== NAS SYNC JOBS ===`.

- [ ] **Step 1: Write the failing test**

```python
"""Test API router nas-sync (TestClient, auth override, DB in memoria)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, FileEndpoint, FileEndpointType, get_db
from routers import nas_sync_jobs
from routers.auth import get_current_user, require_operator
from services.nas_sync.models import NasSyncJob


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    db = TestSession()
    src = FileEndpoint(name="syno", endpoint_type=FileEndpointType.SYNOLOGY, host="1",
                       port=1, protocol="api", username="u", password_enc="x", extra_config={})
    dst = FileEndpoint(name="qnap", endpoint_type=FileEndpointType.QNAP, host="2",
                       port=1, protocol="api", username="u", password_enc="x",
                       extra_config={"rsync_module": "DATI", "rsync_password_enc": "x"})
    db.add_all([src, dst])
    db.commit()
    src_id, dst_id = src.id, dst.id
    db.close()

    app = FastAPI()
    app.include_router(nas_sync_jobs.router, prefix="/api/nas-sync")

    def _fake_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: object()
    app.dependency_overrides[require_operator] = lambda: object()
    return TestClient(app), src_id, dst_id


def test_create_and_list_job(client):
    c, src_id, dst_id = client
    payload = {
        "name": "replica-docs",
        "source_endpoint_id": src_id,
        "dest_endpoint_id": dst_id,
        "source_paths": ["/Condivisa/docs"],
        "dest_base_path": "/share/DATI",
    }
    r = c.post("/api/nas-sync", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sync_method"] == "auto"
    assert body["resolved_engine"] == "direct_rsync"  # calcolato alla create

    r = c.get("/api/nas-sync")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_create_rejects_missing_endpoint(client):
    c, src_id, _ = client
    r = c.post("/api/nas-sync", json={
        "name": "x", "source_endpoint_id": src_id, "dest_endpoint_id": 999,
        "source_paths": ["/A"], "dest_base_path": "/share/D",
    })
    assert r.status_code == 400


def test_capabilities_endpoint(client):
    c, src_id, _ = client
    r = c.get(f"/api/nas-sync/endpoints/{src_id}/capabilities")
    assert r.status_code == 200
    caps = r.json()
    assert caps["rsync_source"] is True
    assert caps["smb"] is True


def test_stats_summary(client):
    c, _, _ = client
    r = c.get("/api/nas-sync/stats/summary")
    assert r.status_code == 200
    assert r.json()["total"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_nas_sync_router.py -v`
Expected: FAIL con ModuleNotFoundError (`routers.nas_sync_jobs`)

- [ ] **Step 3: Write schemas**

`backend/services/nas_sync/schemas.py`:

```python
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
```

- [ ] **Step 4: Write router**

`backend/routers/nas_sync_jobs.py`:

```python
"""Router CRUD e azioni job Repliche dati v2 (/api/nas-sync)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import FileEndpoint, JobLog, get_db
from routers.auth import User, get_current_user, require_operator
from services.file_replication.path_utils import compact_source_paths
from services.nas_sync.capabilities import resolve_capabilities, resolve_engine
from services.nas_sync.du_catalog import (
    get_catalog_progress,
    refresh_job_du_catalog,
)
from services.nas_sync.execution import (
    execute_nas_sync_job,
    get_job_progress,
    is_job_busy,
    stop_nas_sync_job,
)
from services.nas_sync.models import NasSyncJob
from services.nas_sync.preflight import run_preflight
from services.nas_sync.schemas import NasSyncJobCreate, NasSyncJobOut, NasSyncJobUpdate
from services.nas_sync.state import catalog_summary
from services.scheduler import scheduler_service

logger = logging.getLogger(__name__)
router = APIRouter()


def _latest_log_errors(db: Session, job_ids: list[int]) -> dict[int, str]:
    if not job_ids:
        return {}
    logs = (
        db.query(JobLog)
        .filter(JobLog.job_type == "nas_sync", JobLog.job_id.in_(job_ids))
        .order_by(JobLog.job_id, JobLog.id.desc())
        .all()
    )
    latest: dict[int, JobLog] = {}
    for log in logs:
        latest.setdefault(log.job_id, log)
    return {
        jid: (log.error or log.message or "")
        for jid, log in latest.items()
        if log.status == "failed"
    }


def _engine_info(db: Session, job: NasSyncJob) -> tuple[Optional[str], Optional[str]]:
    source = db.query(FileEndpoint).filter(FileEndpoint.id == job.source_endpoint_id).first()
    dest = db.query(FileEndpoint).filter(FileEndpoint.id == job.dest_endpoint_id).first()
    if not source or not dest:
        return None, None
    try:
        return resolve_engine(job.sync_method or "auto", source, dest)
    except ValueError as exc:
        return None, str(exc)


def _job_out(db: Session, job: NasSyncJob, last_run_error: Optional[str] = None) -> NasSyncJobOut:
    engine, reason = _engine_info(db, job)
    src = db.query(FileEndpoint).filter(FileEndpoint.id == job.source_endpoint_id).first()
    dst = db.query(FileEndpoint).filter(FileEndpoint.id == job.dest_endpoint_id).first()
    return NasSyncJobOut(
        id=job.id,
        name=job.name,
        description=job.description,
        source_endpoint_id=job.source_endpoint_id,
        dest_endpoint_id=job.dest_endpoint_id,
        source_paths=job.source_paths or [],
        dest_base_path=job.dest_base_path,
        sync_method=job.sync_method or "auto",
        resolved_engine=job.resolved_engine or engine,
        engine_reason=reason,
        delete_on_dest=bool(job.delete_on_dest),
        rclone_size_only=bool(job.rclone_size_only),
        exclude_presets=job.exclude_presets or [],
        exclude_patterns=job.exclude_patterns or [],
        bandwidth_limit_kb=job.bandwidth_limit_kb,
        snapshot_policy_hint=job.snapshot_policy_hint,
        schedule=job.schedule,
        schedule_config=job.schedule_config,
        is_active=bool(job.is_active),
        current_status=job.current_status,
        last_run_at=job.last_run_at,
        last_run_status=job.last_run_status,
        last_run_duration_sec=job.last_run_duration_sec,
        last_bytes_transferred=job.last_bytes_transferred,
        last_files_transferred=job.last_files_transferred,
        next_run_at=job.next_run_at,
        notify_mode=job.notify_mode,
        notify_subject=job.notify_subject,
        source_endpoint_name=src.name if src else None,
        dest_endpoint_name=dst.name if dst else None,
        last_run_error=last_run_error,
        **catalog_summary(job.run_state or {}),
    )


def _validate_endpoints(db: Session, source_id: int, dest_id: int) -> tuple[FileEndpoint, FileEndpoint]:
    source = db.query(FileEndpoint).filter(FileEndpoint.id == source_id).first()
    dest = db.query(FileEndpoint).filter(FileEndpoint.id == dest_id).first()
    if not source:
        raise HTTPException(status_code=400, detail="Endpoint sorgente non trovato")
    if not dest:
        raise HTTPException(status_code=400, detail="Endpoint destinazione non trovato")
    caps = resolve_capabilities(dest)
    if not caps["rsync_dest"] and not caps["smb"]:
        raise HTTPException(
            status_code=400,
            detail="L'endpoint destinazione non ha capacità valide (né rsync né SMB)",
        )
    return source, dest


@router.get("/stats/summary")
def stats_summary(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    total = db.query(NasSyncJob).count()
    active = db.query(NasSyncJob).filter(NasSyncJob.is_active == True).count()  # noqa: E712
    running = db.query(NasSyncJob).filter(NasSyncJob.current_status == "running").count()
    paused = db.query(NasSyncJob).filter(NasSyncJob.current_status == "paused").count()
    failed = db.query(NasSyncJob).filter(NasSyncJob.last_run_status == "failed").count()
    return {"total": total, "active": active, "running": running, "paused": paused, "failed": failed}


@router.get("/endpoints/{endpoint_id}/capabilities")
def endpoint_capabilities(
    endpoint_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    ep = db.query(FileEndpoint).filter(FileEndpoint.id == endpoint_id).first()
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint non trovato")
    return resolve_capabilities(ep)


@router.get("", response_model=list[NasSyncJobOut])
def list_jobs(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    jobs = db.query(NasSyncJob).order_by(NasSyncJob.name).all()
    errors = _latest_log_errors(db, [j.id for j in jobs])
    return [
        _job_out(db, j, None if j.current_status == "running" else errors.get(j.id))
        for j in jobs
    ]


@router.post("", response_model=NasSyncJobOut)
def create_job(
    body: NasSyncJobCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_operator),
):
    source, dest = _validate_endpoints(db, body.source_endpoint_id, body.dest_endpoint_id)
    try:
        engine, _ = resolve_engine(body.sync_method, source, dest)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job = NasSyncJob(
        name=body.name,
        description=body.description,
        source_endpoint_id=body.source_endpoint_id,
        dest_endpoint_id=body.dest_endpoint_id,
        source_paths=compact_source_paths(body.source_paths),
        dest_base_path=body.dest_base_path.strip() or "/",
        sync_method=body.sync_method,
        resolved_engine=engine,
        delete_on_dest=body.delete_on_dest,
        rclone_size_only=body.rclone_size_only,
        exclude_presets=body.exclude_presets,
        exclude_patterns=body.exclude_patterns,
        bandwidth_limit_kb=body.bandwidth_limit_kb,
        snapshot_policy_hint=body.snapshot_policy_hint or {},
        schedule=body.schedule,
        schedule_config=body.schedule_config,
        is_active=body.is_active,
        notify_mode=body.notify_mode,
        notify_subject=body.notify_subject,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    if job.schedule and job.is_active:
        scheduler_service.update_nas_sync_schedule(job.id, job.schedule)
    return _job_out(db, job)


@router.get("/{job_id}", response_model=NasSyncJobOut)
def get_job(job_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    return _job_out(db, job)


@router.put("/{job_id}", response_model=NasSyncJobOut)
def update_job(
    job_id: int,
    body: NasSyncJobUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_operator),
):
    job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    data = body.model_dump(exclude_unset=True)
    if data.get("source_paths") is not None:
        data["source_paths"] = compact_source_paths(data["source_paths"])
    for key, value in data.items():
        setattr(job, key, value)
    job.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    if job.schedule and job.is_active:
        scheduler_service.update_nas_sync_schedule(job.id, job.schedule)
    else:
        scheduler_service.remove_nas_sync_schedule(job.id)
    return _job_out(db, job)


@router.delete("/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db), _user: User = Depends(require_operator)):
    job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    scheduler_service.remove_nas_sync_schedule(job.id)
    db.delete(job)
    db.commit()
    return {"ok": True}


@router.post("/{job_id}/run")
async def run_job(
    job_id: int,
    fresh: bool = Query(False, description="Ignora checkpoint e riparti da capo"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_operator),
):
    job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    if is_job_busy(job_id) or job.current_status == "running":
        raise HTTPException(status_code=409, detail="Job già in esecuzione o catalogo in aggiornamento")
    asyncio.create_task(execute_nas_sync_job(job_id, fresh=fresh))
    if fresh:
        message = "Esecuzione avviata da capo"
    elif job.current_status == "paused":
        message = "Ripresa esecuzione dal checkpoint"
    else:
        message = "Esecuzione avviata"
    return {"ok": True, "message": message}


@router.post("/{job_id}/stop")
async def stop_job(job_id: int, db: Session = Depends(get_db), _user: User = Depends(require_operator)):
    job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    result = await stop_nas_sync_job(job_id)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("message", "Job non in esecuzione"))
    return result


@router.post("/{job_id}/toggle", response_model=NasSyncJobOut)
def toggle_job(job_id: int, db: Session = Depends(get_db), _user: User = Depends(require_operator)):
    job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    job.is_active = not job.is_active
    db.commit()
    db.refresh(job)
    if job.is_active and job.schedule:
        scheduler_service.update_nas_sync_schedule(job.id, job.schedule)
    else:
        scheduler_service.remove_nas_sync_schedule(job.id)
    return _job_out(db, job)


@router.post("/{job_id}/refresh-catalog")
async def refresh_catalog(job_id: int, db: Session = Depends(get_db), _user: User = Depends(require_operator)):
    job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    if is_job_busy(job_id):
        raise HTTPException(status_code=409, detail="Replica o catalogo già in corso")
    source = db.query(FileEndpoint).filter(FileEndpoint.id == job.source_endpoint_id).first()
    if not source:
        raise HTTPException(status_code=400, detail="Endpoint sorgente mancante")
    caps = resolve_capabilities(source)
    if not caps["rsync_source"]:
        raise HTTPException(
            status_code=400,
            detail="Il catalogo du richiede SSH sulla sorgente (non disponibile per questo endpoint)",
        )
    asyncio.create_task(refresh_job_du_catalog(job_id))
    return {"ok": True, "message": "Aggiornamento catalogo du avviato"}


@router.post("/{job_id}/preflight")
async def preflight(job_id: int, db: Session = Depends(get_db), _user: User = Depends(require_operator)):
    job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    source = db.query(FileEndpoint).filter(FileEndpoint.id == job.source_endpoint_id).first()
    dest = db.query(FileEndpoint).filter(FileEndpoint.id == job.dest_endpoint_id).first()
    if not source or not dest:
        raise HTTPException(status_code=400, detail="Endpoint mancante")
    return await run_preflight(job, source, dest)


@router.get("/{job_id}/logs")
def job_logs(job_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    logs = (
        db.query(JobLog)
        .filter(JobLog.job_type == "nas_sync", JobLog.job_id == job_id)
        .order_by(JobLog.id.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": log.id,
            "status": log.status,
            "message": log.message,
            "output": log.output,
            "error": log.error,
            "duration": log.duration,
            "transferred": log.transferred,
            "created_at": log.started_at,
            "completed_at": log.completed_at,
        }
        for log in logs
    ]


@router.get("/{job_id}/progress")
def job_progress(job_id: int, _user: User = Depends(get_current_user)):
    prog = get_job_progress(job_id)
    if prog:
        return prog
    cat = get_catalog_progress(job_id)
    if cat:
        return cat
    return {"status": "idle"}
```

IMPORTANTE ordine rotte FastAPI: `/stats/summary` e `/endpoints/{id}/capabilities` DEVONO stare PRIMA di `/{job_id}` nel file (come sopra), altrimenti `stats` matcha `{job_id}`.

NOTA scope: la spec §6 cita anche `POST /endpoints/{id}/test-capability` (test live per singola capacità). È RINVIATO deliberatamente (YAGNI): il test live dei prerequisiti è coperto dal preflight a livello job (`POST /{job_id}/preflight`). Non implementarlo.

- [ ] **Step 5: Registrazioni (main.py, scheduler.py)**

`backend/main.py` — nella zona import router (cercare `from routers import` con `grep -n "file_replication_jobs" backend/main.py`), aggiungere `nas_sync_jobs` all'import esistente dei router. Poi, nel blocco `if dapx_mode == "full":`, SUBITO DOPO la riga `app.include_router(file_replication_jobs.router, prefix="/api/file-replication", ...)`, aggiungere:

```python
    app.include_router(nas_sync_jobs.router, prefix="/api/nas-sync", tags=["Repliche dati (NAS Sync v2)"])
```

`backend/services/scheduler.py` — tre aggiunte additive, modellate ESATTAMENTE sul pattern `file_replication` esistente:

1. Nel metodo tick, individuare il blocco `# === FILE REPLICATION JOBS ===` (circa riga 537) e aggiungere DOPO la sua chiusura (dopo l'`except` del `for`), allo stesso livello di indentazione:

```python
            # === NAS SYNC JOBS (Repliche dati v2) ===
            from services.nas_sync.models import NasSyncJob

            nas_sync_jobs_q = db.query(NasSyncJob).filter(
                NasSyncJob.is_active == True,
                NasSyncJob.schedule.isnot(None),
                NasSyncJob.schedule != "",
            ).all()

            for job in nas_sync_jobs_q:
                try:
                    job_key = f"nas_sync_{job.id}"
                    if job_key not in self._jobs:
                        self._jobs[job_key] = compute_initial_next_run(
                            job.schedule, job.last_run_at, now
                        )
                    next_run = self._jobs[job_key]
                    if now >= next_run:
                        if self._try_lock(job_key):
                            logger.info(
                                f"Esecuzione NasSyncJob schedulato: {job.name} (ID: {job.id})"
                            )
                            asyncio.create_task(
                                self._guarded_execute(
                                    job_key,
                                    self._execute_nas_sync_job,
                                    job.id,
                                )
                            )
                            cron = croniter(job.schedule, now)
                            self._jobs[job_key] = cron.get_next(datetime)
                        else:
                            logger.info(
                                f"NasSyncJob {job.id} ancora in esecuzione: skip fire schedulato"
                            )
                except Exception as e:
                    logger.error(f"Errore scheduling NasSyncJob {job.id}: {e}")
```

2. Accanto a `_execute_file_replication_job` (circa riga 843), aggiungere:

```python
    async def _execute_nas_sync_job(self, job_id: int):
        """Esegue un job Repliche dati v2 schedulato."""
        from services.nas_sync.execution import execute_nas_sync_job

        await execute_nas_sync_job(job_id)
```

3. Accanto a `update_file_replication_schedule`/`remove_file_replication_schedule` (circa riga 906), aggiungere:

```python
    def update_nas_sync_schedule(
        self,
        job_id: int,
        schedule: str,
        last_run: Optional[datetime] = None,
    ) -> None:
        key = f"nas_sync_{job_id}"
        if schedule:
            self._jobs[key] = compute_initial_next_run(schedule, last_run, datetime.utcnow())
        elif key in self._jobs:
            del self._jobs[key]

    def remove_nas_sync_schedule(self, job_id: int) -> None:
        self._jobs.pop(f"nas_sync_{job_id}", None)
```

Infine, in `backend/main.py`, nel lifespan dove viene chiamato `update_schema()` (individuare con `grep -n "update_schema" backend/main.py`), aggiungere SUBITO DOPO:

```python
    try:
        from services.nas_sync.execution import reconcile_stale_running_jobs as _nas2_reconcile
        _nas2_reconcile()
    except Exception as _exc:  # noqa: BLE001 — il reconcile non deve bloccare l'avvio
        logger.warning(f"nas_sync reconcile all'avvio fallito: {_exc}")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_nas_sync_router.py -v`
Expected: 4 PASS

Run: `cd backend && ./venv/bin/python -c "import main; print('main ok')"`
Expected: `main ok` (nessun errore import/registrazione)

- [ ] **Step 7: Verifica non-regressione modulo esistente**

Run: `cd backend && ./venv/bin/python -m pytest tests/ -x -q 2>&1 | tail -5`
Expected: nessun test esistente rotto (stessi pass/fail di prima del piano — se un test già falliva PRIMA di questo lavoro, annotarlo e NON tentare di sistemarlo).

- [ ] **Step 8: Commit**

```bash
git add backend/services/nas_sync/schemas.py backend/routers/nas_sync_jobs.py backend/main.py backend/services/scheduler.py backend/tests/test_nas_sync_router.py
git commit -m "feat(nas-sync): router /api/nas-sync, scheduler e registrazione app"
```

---

### Task 12: Frontend — service TS, route, voce menù «Repliche dati»

**Files:**
- Create: `frontend/src/services/nasSync.ts`
- Modify: `frontend/src/router/index.ts` (una entry additiva)
- Modify: `frontend/src/layouts/MainLayout.vue` (una voce menù additiva)
- Create: `frontend/src/views/NasSync.vue` (placeholder minimo in questo task; la view completa arriva nel Task 15)

**Interfaces:**
- Produces: `nasSyncApi` con metodi `list, get, create, update, delete, run(id, fresh?), stop, toggle, logs, progress, stats, refreshCatalog, preflight, capabilities(endpointId)`; tipi `NasSyncJob`, `PreflightCheck`, `EndpointCapabilities`.

- [ ] **Step 1: Write service**

`frontend/src/services/nasSync.ts`:

```typescript
import apiClient from './api'

export interface NasSyncJob {
  id: number
  name: string
  description?: string | null
  source_endpoint_id: number
  dest_endpoint_id: number
  source_paths: string[]
  dest_base_path: string
  sync_method: 'auto' | 'direct_rsync' | 'rclone_smb'
  resolved_engine?: 'direct_rsync' | 'rclone_smb' | null
  engine_reason?: string | null
  delete_on_dest: boolean
  rclone_size_only?: boolean
  exclude_presets: string[]
  exclude_patterns: string[]
  bandwidth_limit_kb?: number | null
  snapshot_policy_hint?: Record<string, unknown> | null
  schedule?: string | null
  is_active: boolean
  current_status?: string | null
  last_run_at?: string | null
  last_run_status?: string | null
  last_run_duration_sec?: number | null
  last_bytes_transferred?: number | null
  last_files_transferred?: number | null
  next_run_at?: string | null
  notify_mode?: string | null
  notify_subject?: string | null
  source_endpoint_name?: string | null
  dest_endpoint_name?: string | null
  last_run_error?: string | null
  catalog_bytes_est?: number | null
  catalog_files_est?: number | null
  catalog_updated_at?: string | null
  catalog_folder_count?: number | null
  catalog_has_du?: boolean | null
}

export interface PreflightCheck {
  check: string
  ok: boolean
  message: string
  hint?: string | null
}

export interface EndpointCapabilities {
  rsync_source: boolean
  rsync_dest: boolean
  smb: boolean
  reasons: Record<string, string>
}

export interface NasSyncStats {
  total: number
  active: number
  running: number
  paused: number
  failed: number
}

export const nasSyncApi = {
  list: () => apiClient.get<NasSyncJob[]>('/nas-sync'),
  get: (id: number) => apiClient.get<NasSyncJob>(`/nas-sync/${id}`),
  create: (data: Record<string, unknown>) => apiClient.post<NasSyncJob>('/nas-sync', data),
  update: (id: number, data: Record<string, unknown>) =>
    apiClient.put<NasSyncJob>(`/nas-sync/${id}`, data),
  delete: (id: number) => apiClient.delete(`/nas-sync/${id}`),
  run: (id: number, fresh = false) =>
    apiClient.post(`/nas-sync/${id}/run`, null, { params: fresh ? { fresh: true } : {} }),
  stop: (id: number) => apiClient.post(`/nas-sync/${id}/stop`),
  toggle: (id: number) => apiClient.post<NasSyncJob>(`/nas-sync/${id}/toggle`),
  logs: (id: number) => apiClient.get(`/nas-sync/${id}/logs`),
  progress: (id: number) => apiClient.get(`/nas-sync/${id}/progress`),
  stats: () => apiClient.get<NasSyncStats>('/nas-sync/stats/summary'),
  refreshCatalog: (id: number) => apiClient.post(`/nas-sync/${id}/refresh-catalog`),
  preflight: (id: number) => apiClient.post<PreflightCheck[]>(`/nas-sync/${id}/preflight`),
  capabilities: (endpointId: number) =>
    apiClient.get<EndpointCapabilities>(`/nas-sync/endpoints/${endpointId}/capabilities`),
}
```

- [ ] **Step 2: Placeholder view**

`frontend/src/views/NasSync.vue` (placeholder, sostituito nel Task 15):

```vue
<script setup lang="ts">
// Placeholder: la view completa arriva col Task 15.
</script>

<template>
  <div class="p-4">
    <h1>Repliche dati</h1>
    <p>Modulo in costruzione.</p>
  </div>
</template>
```

- [ ] **Step 3: Route + menù**

`frontend/src/router/index.ts` — SUBITO DOPO il blocco della route `file-replication` (cercare `name: 'file-replication'`), aggiungere:

```typescript
                {
                    path: 'nas-sync',
                    name: 'nas-sync',
                    component: () => import('../views/NasSync.vue')
                },
```

`frontend/src/layouts/MainLayout.vue` — individuare la voce menù esistente (riga ~42):

```html
          <router-link :to="{ name: 'file-replication' }" class="nav-item" active-class="active">
```

e SUBITO DOPO la chiusura di quel `<router-link>` (leggere il file per il markup esatto della voce: icona + `<span>Replica file NAS</span>` + `</router-link>`), aggiungere una voce identica nella struttura:

```html
          <router-link :to="{ name: 'nas-sync' }" class="nav-item" active-class="active">
            <span class="nav-icon">⇄</span>
            <span>Repliche dati</span>
          </router-link>
```

NOTA: replicare ESATTAMENTE il markup della voce sopra (stessa classe icona: se le altre voci usano un componente icona o emoji diverso, copiarne la struttura sostituendo solo testo/route). Verificare con la voce `file-replication` esistente.

- [ ] **Step 4: Build check**

Run: `cd frontend && npm run build 2>&1 | tail -5`
Expected: build OK senza errori TS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/nasSync.ts frontend/src/views/NasSync.vue frontend/src/router/index.ts frontend/src/layouts/MainLayout.vue
git commit -m "feat(nas-sync): service TS, route /nas-sync e voce menù Repliche dati"
```

---

### Task 13: Frontend — form endpoint con capacità (SSH + servizio rsync)

**Files:**
- Create: `frontend/src/components/nas-sync/NasSyncEndpointForm.vue`

**Interfaces:**
- Consumes: `fileEndpointsApi` (CRUD endpoint condiviso, INVARIATO), `nasSyncApi.capabilities`.
- Produces: componente con props `{ endpoint?: FileEndpoint | null }`, emit `saved(endpoint)`, `cancel`. Salva i campi capacità dentro `extra_config`: `ssh_port`, `rsync_module`, `rsync_user`, `rsync_password` (il backend la cifra → `rsync_password_enc`), `rsync_port`.

NOTA BACKEND PREREQUISITO: il CRUD `/api/file-endpoints` accetta `extra_config` passthrough. La cifratura di `rsync_password` → `rsync_password_enc` NON esiste ancora: farla nel router NUOVO. Aggiungere in `backend/routers/nas_sync_jobs.py` (Task 11, file già nostro) questo endpoint, e usarlo dal form per salvare i campi rsync:

```python
@router.put("/endpoints/{endpoint_id}/rsync-config")
def set_endpoint_rsync_config(
    endpoint_id: int,
    body: dict,
    db: Session = Depends(get_db),
    _user: User = Depends(require_operator),
):
    """Salva config servizio rsync dell'endpoint (password cifrata, mai in chiaro)."""
    from services.file_replication.endpoint_crypto import encrypt_password

    ep = db.query(FileEndpoint).filter(FileEndpoint.id == endpoint_id).first()
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint non trovato")
    extra = dict(ep.extra_config or {})
    for key in ("ssh_port", "rsync_module", "rsync_user", "rsync_port"):
        if key in body and body[key] not in (None, ""):
            extra[key] = body[key]
        elif key in body:
            extra.pop(key, None)
    if body.get("rsync_password"):
        extra["rsync_password_enc"] = encrypt_password(str(body["rsync_password"]))
    ep.extra_config = extra
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(ep, "extra_config")
    ep.updated_at = datetime.utcnow()
    db.commit()
    from services.nas_sync.capabilities import resolve_capabilities as _caps
    return _caps(ep)
```

(aggiungere questo endpoint nel Task 13 stesso, con commit qui; verificare la firma di `encrypt_password` con `grep -n "def encrypt_password" backend/services/file_replication/endpoint_crypto.py`). Aggiungere il metodo al service TS: `setRsyncConfig: (endpointId: number, data: Record<string, unknown>) => apiClient.put(`/nas-sync/endpoints/${endpointId}/rsync-config`, data),` in `nasSyncApi`.

- [ ] **Step 1: Componente**

Creare `frontend/src/components/nas-sync/NasSyncEndpointForm.vue` COPIANDO la struttura di `frontend/src/components/file-replication/FileEndpointForm.vue` (leggerlo, non modificarlo) con queste differenze esatte:

1. Import aggiuntivo: `import { nasSyncApi, type EndpointCapabilities } from '../../services/nasSync'`
2. Nel `form` reactive aggiungere: `ssh_port: 22`, `rsync_module: ''`, `rsync_user: ''`, `rsync_password: ''`, `rsync_port: 873`.
3. In `loadFromEndpoint`, popolare i nuovi campi da `ep.extra_config` (`ssh_port ?? 22`, `rsync_module ?? ''`, `rsync_user ?? ''`, `rsync_port ?? 873`; `rsync_password` sempre `''`).
4. Etichetta ruolo: `<option value="destination">Destinazione</option>` (togliere «QNAP» dal testo; SOLO in questo file nuovo).
5. Dopo il salvataggio endpoint riuscito (in `save()`), se `endpoint_type !== 'windows'`, chiamare:

```typescript
await nasSyncApi.setRsyncConfig(data.id, {
  ssh_port: form.ssh_port || null,
  rsync_module: form.rsync_module || null,
  rsync_user: form.rsync_user || null,
  rsync_password: form.rsync_password || null,
  rsync_port: form.rsync_port || null,
})
```

6. Sezione template aggiuntiva (dopo il blocco password), visibile se `form.endpoint_type !== 'windows'`:

```html
      <fieldset class="span-2 caps-box">
        <legend>Accesso SSH (replica diretta e catalogo du)</legend>
        <div class="form-group">
          <label>Porta SSH</label>
          <input v-model.number="form.ssh_port" type="number" class="form-input" placeholder="22" />
          <small class="text-muted">Usata da dapx per lanciare rsync/du sulla sorgente.</small>
        </div>
      </fieldset>
      <fieldset v-if="form.role !== 'source'" class="span-2 caps-box">
        <legend>Servizio rsync (per ruolo destinazione — motore diretto)</legend>
        <div class="grid-2">
          <div class="form-group">
            <label>Modulo rsync</label>
            <input v-model="form.rsync_module" class="form-input" placeholder="DATI" />
            <small class="text-muted">
              Nome modulo configurato sul NAS (DSM: Servizi file → rsync; QTS: Rsync Server).
            </small>
          </div>
          <div class="form-group">
            <label>Porta</label>
            <input v-model.number="form.rsync_port" type="number" class="form-input" placeholder="873" />
          </div>
          <div class="form-group">
            <label>Utente rsync</label>
            <input v-model="form.rsync_user" class="form-input" />
          </div>
          <div class="form-group">
            <label>Password rsync</label>
            <input v-model="form.rsync_password" type="password" class="form-input"
                   :placeholder="isEdit ? 'Lascia vuoto per non cambiare' : ''" />
          </div>
        </div>
      </fieldset>
```

7. Sotto i bottoni, badge capacità (caricate con `nasSyncApi.capabilities(id)` dopo save/on load se `isEdit`):

```html
      <p v-if="caps" class="span-2 caps-badges">
        <span class="badge" :class="caps.rsync_source ? 'badge-ok' : 'badge-off'"
              :title="caps.reasons.rsync_source || ''">rsync sorgente {{ caps.rsync_source ? '✓' : '✗' }}</span>
        <span class="badge" :class="caps.rsync_dest ? 'badge-ok' : 'badge-off'"
              :title="caps.reasons.rsync_dest || ''">rsync destinazione {{ caps.rsync_dest ? '✓' : '✗' }}</span>
        <span class="badge" :class="caps.smb ? 'badge-ok' : 'badge-off'">SMB {{ caps.smb ? '✓' : '✗' }}</span>
      </p>
```

con nello script: `const caps = ref<EndpointCapabilities | null>(null)` e funzione `async function loadCaps(id: number) { const { data } = await nasSyncApi.capabilities(id); caps.value = data }` chiamata nel watch su `props.endpoint` (se `ep?.id`) e dopo `save()`.

8. Stile scoped aggiuntivo:

```css
.caps-box { border: 1px solid var(--border-color, #333); border-radius: 8px; padding: 10px 14px; }
.caps-badges { display: flex; gap: 8px; }
.badge-ok { background: rgba(46, 204, 113, .18); color: #2ecc71; }
.badge-off { background: rgba(255,255,255,.06); opacity: .6; }
```

- [ ] **Step 2: Build check**

Run: `cd frontend && npm run build 2>&1 | tail -5`
Expected: build OK

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/nas-sync/NasSyncEndpointForm.vue frontend/src/services/nasSync.ts backend/routers/nas_sync_jobs.py
git commit -m "feat(nas-sync): form endpoint con config SSH/rsync e badge capacità"
```

---

### Task 14: Frontend — wizard job con pannello Motore e preflight

**Files:**
- Create: `frontend/src/components/nas-sync/NasSyncJobModal.vue`

**Interfaces:**
- Consumes: `nasSyncApi`, `fileEndpointsApi`, componenti riusati via import cross-cartella (SENZA copiarli né modificarli): `FolderBrowser.vue`, `FileReplPathMapping.vue`, `QnapImmutabilityHint.vue` da `../file-replication/`.
- Produces: componente con props `{ job?: NasSyncJob | null }`, emit `saved`, `close`.

- [ ] **Step 1: Componente**

Creare `frontend/src/components/nas-sync/NasSyncJobModal.vue` partendo dalla struttura di `frontend/src/components/file-replication/FileReplJobModal.vue` (leggerlo, non modificarlo), con queste differenze esatte:

1. Import: sostituire i service con `nasSyncApi, type NasSyncJob` da `../../services/nasSync`; componenti condivisi importati da `../file-replication/FolderBrowser.vue`, `../file-replication/FileReplPathMapping.vue`, `../file-replication/QnapImmutabilityHint.vue`.
2. `form` con campi: `name, source_endpoint_id, dest_endpoint_id, source_paths, dest_base_path ('/share/DATI'), sync_method ('auto'), delete_on_dest (false), rclone_size_only (false), exclude_presets, exclude_patterns, bandwidth_limit_kb (null), schedule ('0 2 * * *'), notify_mode ('daily'), notify_subject ('')` + campi snapshot hint come nell'originale.
3. Filtro destinazioni per capacità (al posto del filtro `endpoint_type === 'qnap'`):

```typescript
const endpointCaps = ref<Record<number, EndpointCapabilities>>({})

async function loadEndpoints() {
  const { data } = await fileEndpointsApi.list()
  endpoints.value = data
  await Promise.all(
    data.map(async (ep) => {
      try {
        const { data: caps } = await nasSyncApi.capabilities(ep.id)
        endpointCaps.value[ep.id] = caps
      } catch { /* endpoint senza capacità: escluso dai filtri */ }
    }),
  )
}

const destEndpoints = computed(() =>
  endpoints.value.filter((e) => {
    if (e.role !== 'destination' && e.role !== 'both') return false
    const caps = endpointCaps.value[e.id]
    return !!caps && (caps.rsync_dest || caps.smb)
  }),
)
```

4. Pannello Motore nello step 4, PRIMA delle altre opzioni:

```html
        <div class="engine-panel">
          <h4>Motore di replica</h4>
          <select v-model="form.sync_method" class="form-input">
            <option value="auto">Automatico (consigliato)</option>
            <option value="direct_rsync">Diretto rsync (NAS→NAS)</option>
            <option value="rclone_smb">rclone SMB (via server dapx)</option>
          </select>
          <p v-if="engineHint" class="text-muted">{{ engineHint }}</p>
          <button
            v-if="isEdit"
            type="button"
            class="btn btn-sm btn-secondary mt-2"
            :disabled="preflightRunning"
            @click="runPreflight"
          >
            {{ preflightRunning ? 'Verifica…' : 'Verifica prerequisiti' }}
          </button>
          <ul v-if="preflightChecks.length" class="preflight-list">
            <li v-for="c in preflightChecks" :key="c.check"
                :class="c.ok ? 'text-success' : 'text-danger'">
              {{ c.ok ? '✓' : '✗' }} {{ c.message }}
              <small v-if="c.hint" class="d-block text-muted">{{ c.hint }}</small>
            </li>
          </ul>
        </div>
```

con nello script:

```typescript
const preflightChecks = ref<PreflightCheck[]>([])
const preflightRunning = ref(false)

const engineHint = computed(() => {
  const src = endpointCaps.value[form.source_endpoint_id ?? -1]
  const dst = endpointCaps.value[form.dest_endpoint_id ?? -1]
  if (!src || !dst) return ''
  if (form.sync_method === 'auto') {
    if (src.rsync_source && dst.rsync_dest)
      return 'Verrà usato il motore diretto rsync: i dati non passano dal server dapx.'
    return 'Verrà usato rclone SMB (fallback): ' +
      (src.reasons.rsync_source || dst.reasons.rsync_dest || '')
  }
  return ''
})

async function runPreflight() {
  if (!props.job?.id) return
  preflightRunning.value = true
  try {
    const { data } = await nasSyncApi.preflight(props.job.id)
    preflightChecks.value = data
  } finally {
    preflightRunning.value = false
  }
}
```

5. Opzioni condizionali al motore nello step 4: la checkbox `rclone_size_only` e i testi su `--no-traverse`/`--fast-list` vanno racchiusi in `<template v-if="form.sync_method !== 'direct_rsync'">…</template>`. La checkbox `delete_on_dest` resta sempre visibile con testo neutro: «Elimina sulla destinazione i file non più presenti nella sorgente (mirror)». Aggiungere campo bwlimit sempre visibile:

```html
        <div class="form-group">
          <label>Limite banda (KB/s, vuoto = nessun limite)</label>
          <input v-model.number="form.bandwidth_limit_kb" type="number" class="form-input" />
        </div>
```

6. `QnapImmutabilityHint` mostrato SOLO se l'endpoint destinazione selezionato è `endpoint_type === 'qnap'`.
7. Testi: titolo modal «Nuovo job Repliche dati» / «Modifica job Repliche dati»; step 3 label «Endpoint destinazione»; hint cartelle senza riferimenti hardcoded a QNAP («La struttura sorgente viene replicata sotto il percorso base di destinazione»). Nello step 2, aggiungere la nota di convivenza (spec §10): `<p class="text-muted">Non schedulare le stesse cartelle sia qui che nel modulo «Replica file»: i due moduli non si coordinano tra loro.</p>`
8. `buildPayload()` invia: `name, source_paths, dest_base_path, sync_method, delete_on_dest, rclone_size_only, exclude_presets, exclude_patterns (split \n), bandwidth_limit_kb, schedule|null, notify_mode, notify_subject|null, snapshot_policy_hint` e in create anche `source_endpoint_id`, `dest_endpoint_id`.
9. Stile scoped aggiuntivo:

```css
.engine-panel { border: 1px solid var(--border-color, #333); border-radius: 8px; padding: 12px 16px; margin-bottom: 12px; }
.preflight-list { list-style: none; padding: 8px 0 0; margin: 0; font-size: .85rem; }
```

- [ ] **Step 2: Build check**

Run: `cd frontend && npm run build 2>&1 | tail -5`
Expected: build OK

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/nas-sync/NasSyncJobModal.vue
git commit -m "feat(nas-sync): wizard job con pannello motore e preflight"
```

---

### Task 15: Frontend — view completa «Repliche dati» + log modal

**Files:**
- Create: `frontend/src/components/nas-sync/NasSyncLogModal.vue` (copia-adatta)
- Modify: `frontend/src/views/NasSync.vue` (sostituisce il placeholder del Task 12 con la view completa, copia-adatta di `FileReplication.vue`)

- [ ] **Step 1: Log modal (copia + swap service)**

```bash
cp frontend/src/components/file-replication/FileReplLogModal.vue frontend/src/components/nas-sync/NasSyncLogModal.vue
```

Poi in `NasSyncLogModal.vue` applicare SOLO queste sostituzioni:

1. `import { fileReplicationApi } from '../../services/fileReplication'` → `import { nasSyncApi } from '../../services/nasSync'`
2. `import type { FileReplicationJob } from '../../services/fileReplication'` → `import type { NasSyncJob } from '../../services/nasSync'`
3. Ogni occorrenza del tipo `FileReplicationJob` → `NasSyncJob`
4. `fileReplicationApi.logs(` → `nasSyncApi.logs(` e `fileReplicationApi.progress(` → `nasSyncApi.progress(`
5. Import componenti locali: `./FileReplPathMapping.vue` → `../file-replication/FileReplPathMapping.vue`; `./FileReplFolderCatalog.vue` → `../file-replication/FileReplFolderCatalog.vue`
6. Se il componente referenzia campi che v2 non popola (es. `dest_staging_path`): sostituire `dest_staging_path` → `dest_base_path`. Verificare con `grep -n "dest_staging_path" frontend/src/components/nas-sync/NasSyncLogModal.vue` e sostituire tutte le occorrenze.

- [ ] **Step 2: View completa (copia + adattamenti)**

Sostituire il contenuto di `frontend/src/views/NasSync.vue` con una copia di `frontend/src/views/FileReplication.vue` adattata. Procedura:

```bash
cp frontend/src/views/FileReplication.vue frontend/src/views/NasSync.vue
```

Poi applicare in `NasSync.vue` queste sostituzioni esatte (usare l'editor, NON sed cieco, verificando ogni occorrenza):

1. Import componenti:
   - `../components/file-replication/FileEndpointForm.vue` → `../components/nas-sync/NasSyncEndpointForm.vue` (e il nome `FileEndpointForm` → `NasSyncEndpointForm` in import, template e ovunque usato)
   - `../components/file-replication/FileReplJobModal.vue` → `../components/nas-sync/NasSyncJobModal.vue` (nome `FileReplJobModal` → `NasSyncJobModal`)
   - `../components/file-replication/FileReplLogModal.vue` → `../components/nas-sync/NasSyncLogModal.vue` (nome `FileReplLogModal` → `NasSyncLogModal`)
   - `FileReplPathMapping` e `FileReplFolderCatalog`: lasciare l'import dai path `../components/file-replication/…` (riuso senza copia)
2. Service: `import { fileReplicationApi, type FileReplicationJob } from '../services/fileReplication'` → `import { nasSyncApi, type NasSyncJob } from '../services/nasSync'`; poi OGNI `fileReplicationApi.` → `nasSyncApi.` e OGNI tipo `FileReplicationJob` → `NasSyncJob`.
3. Campo dest: ogni `dest_staging_path` → `dest_base_path` (`grep -n "dest_staging_path" frontend/src/views/NasSync.vue` deve risultare vuoto a fine lavoro).
4. Header: sostituire il blocco titolo con:

```html
        <h1>Repliche dati</h1>
        <p class="repl-sub">
          Replica cartelle NAS→NAS: motore diretto rsync (i dati non passano dal server dapx)
          o rclone SMB come fallback. Sorgenti Synology, QNAP, Linux, Windows; destinazioni QNAP e Synology.
        </p>
```

5. Colonna capacità nella tabella endpoint: nell'`<thead>` degli endpoint aggiungere `<th>Capacità</th>` dopo `<th>Ruolo</th>`; nel `<tbody>` aggiungere dopo la cella ruolo:

```html
              <td class="caps-cell">
                <template v-if="endpointCaps[ep.id]">
                  <span class="badge" :class="endpointCaps[ep.id].rsync_source ? 'badge-ok' : 'badge-off'">SSH</span>
                  <span class="badge" :class="endpointCaps[ep.id].rsync_dest ? 'badge-ok' : 'badge-off'">rsync</span>
                  <span class="badge" :class="endpointCaps[ep.id].smb ? 'badge-ok' : 'badge-off'">SMB</span>
                </template>
                <span v-else class="muted">—</span>
              </td>
```

con nello script (dopo il load endpoint esistente):

```typescript
import type { EndpointCapabilities } from '../services/nasSync'
const endpointCaps = ref<Record<number, EndpointCapabilities>>({})

async function loadCapabilities() {
  await Promise.all(
    endpoints.value.map(async (ep) => {
      try {
        const { data } = await nasSyncApi.capabilities(ep.id)
        endpointCaps.value[ep.id] = data
      } catch { /* ignore */ }
    }),
  )
}
```

chiamando `loadCapabilities()` alla fine della funzione di refresh/caricamento endpoint esistente.

6. Chip motore nella tabella job: nella cella della colonna «Replica» (quella con `FileReplPathMapping`), PRIMA del componente mapping aggiungere:

```html
                <span class="engine-chip" :class="job.resolved_engine === 'direct_rsync' ? 'engine-direct' : 'engine-rclone'">
                  {{ job.resolved_engine === 'direct_rsync' ? 'rsync diretto' : 'rclone SMB' }}
                </span>
```

7. Stile scoped: aggiungere in coda allo `<style scoped>`:

```css
.engine-chip { display: inline-block; font-size: .7rem; padding: 1px 8px; border-radius: 10px; margin-bottom: 4px; }
.engine-direct { background: rgba(46, 204, 113, .15); color: #2ecc71; }
.engine-rclone { background: rgba(241, 196, 15, .15); color: #f1c40f; }
.caps-cell .badge { margin-right: 4px; font-size: .7rem; }
.badge-ok { background: rgba(46, 204, 113, .18); color: #2ecc71; }
.badge-off { background: rgba(255,255,255,.06); opacity: .55; }
```

8. Se la view originale referenzia campi assenti in `NasSyncJob` (verificare con la build TS): `rclone_size_only` esiste; eventuali altri campi mancanti (`resume_*`) → rimuovere il blocco che li usa o sostituirli con `job.current_status === 'paused'`.

- [ ] **Step 3: Build check + lint**

Run: `cd frontend && npm run build 2>&1 | tail -5`
Expected: build OK

Run: `cd frontend && npm run lint 2>&1 | tail -3`
Expected: nessun nuovo errore bloccante

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/NasSync.vue frontend/src/components/nas-sync/NasSyncLogModal.vue
git commit -m "feat(nas-sync): view Repliche dati completa con capacità e chip motore"
```

---

### Task 16: CHANGELOG + verifica finale complessiva

**Files:**
- Modify: `CHANGELOG.md` (sezione `[Unreleased]`)

- [ ] **Step 1: CHANGELOG**

In `CHANGELOG.md`, sotto `## [Unreleased]` → `### Aggiunte`, aggiungere in testa:

```markdown
- **Repliche dati (v2)**: nuovo modulo parallelo con motore diretto rsync NAS→NAS (dati senza transito da dapx) e fallback rclone SMB; matrice capacità endpoint, preflight prerequisiti, pausa/riprendi, catalogo du generico; nuova voce menù, API `/api/nas-sync`, tabella `nas_sync_jobs` (`backend/services/nas_sync/`, `backend/routers/nas_sync_jobs.py`, `NasSync.vue`). Il modulo «Replica file» esistente resta invariato.
```

- [ ] **Step 2: Suite completa backend**

Run: `cd backend && ./venv/bin/python -m pytest tests/ -q 2>&1 | tail -5`
Expected: tutti i test nas_sync PASS; nessun test preesistente peggiorato.

- [ ] **Step 3: Verifica isolamento (OBBLIGATORIA)**

```bash
git diff --name-only $(git log --format=%H --reverse -20 | head -1)~1 2>/dev/null | sort -u
git status --short
```

Verificare che NESSUN file della lista vietata (Global Constraints) compaia tra i modificati dai commit di questo piano. I soli file esistenti toccati devono essere: `backend/main.py`, `backend/services/scheduler.py`, `backend/update_db_schema.py`, `frontend/src/router/index.ts`, `frontend/src/layouts/MainLayout.vue`, `CHANGELOG.md`. Se altro risulta modificato: FERMARSI e segnalare, non committare.

- [ ] **Step 4: Avvio locale smoke test (se possibile)**

Run: `cd backend && ./venv/bin/python -c "import main" && echo IMPORT_OK`
Expected: `IMPORT_OK`

- [ ] **Step 5: Commit finale**

```bash
git add CHANGELOG.md
git commit -m "docs(nas-sync): changelog modulo Repliche dati v2"
```

---

## Note di verifica per il revisore (non per l'esecutore)

1. Il modulo vecchio deve risultare intoccato: `git diff main -- backend/services/file_replication backend/routers/file_replication_jobs.py frontend/src/components/file-replication frontend/src/views/FileReplication.vue` vuoto.
2. Nessuna password in argv: `grep -rn "sshpass -p" backend/services/nas_sync/` deve essere vuoto.
3. Rotte registrate: `curl -s localhost:8420/openapi.json | grep nas-sync` (in ambiente di test).
4. Fix §11 spec (sshpass nel modulo VECCHIO): NON incluso in questo piano — a carico del revisore, commit separato.


