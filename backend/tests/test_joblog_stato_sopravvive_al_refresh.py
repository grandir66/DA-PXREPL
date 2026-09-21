"""Il JobLog di una corsa syncoid deve chiudersi `success`/`failed` con l'errore.

Difetto preesistente (visto il 2026-09-22 scrivendo «il job segue la VM»):
`execute_sync_job_task` scriveva `log_entry.status/message/error` e SUBITO
DOPO faceva `db_session.refresh(log_entry)` per rileggere l'output scritto
dal callback di avanzamento. Con `autoflush=False` (com'è `SessionLocal`)
`refresh()` scarta le modifiche pendenti: il log restava `started` con
`completed_at` valorizzato — «corretto automaticamente» dalla riconciliazione
al giro dopo — e l'errore leggibile andava perso. Qui si pretende che stato
ed errore sopravvivano quando syncoid ha prodotto output (cioè sempre).
"""

from unittest.mock import AsyncMock, patch

import pytest

from database import JobLog, Node, SyncJob
from services.ssh_service import SSHResult
from tests.conftest import TestingSessionLocal


@pytest.fixture
def job(db):
    n1 = Node(name="px-01", hostname="px-01", node_type="pve", is_active=True, is_online=True)
    n4 = Node(name="px-04", hostname="px-04", node_type="pve", is_active=True, is_online=True)
    db.add_all([n1, n4])
    db.flush()
    j = SyncJob(
        name="VM 101", source_node_id=n1.id, dest_node_id=n4.id,
        source_dataset="rpool/data/vm-101-disk-0", dest_dataset="ZFS/replica/vm-101-disk-0",
        vm_id=101, sync_method="syncoid", is_active=True,
    )
    db.add(j)
    db.commit()
    return j.id, n1.id


async def _corsa(db, jid, n1_id, esito_syncoid):
    from services.sync_job_execution import execute_sync_job_task

    # ssh finto per tutto (dataset parent, cluster): ogni comando «riesce» con
    # un testo qualsiasi, quindi la corsa parte dal nodo registrato.
    with patch("database.SessionLocal", side_effect=lambda: TestingSessionLocal(autoflush=False)), \
         patch("services.syncoid_service.syncoid_service.run_sync", AsyncMock(return_value=esito_syncoid)), \
         patch("services.ssh_service.ssh_service.execute",
               AsyncMock(return_value=SSHResult(success=True, stdout="ZFS/replica\n", stderr="", exit_code=0))), \
         patch("services.sync_job_execution._poll_sync_progress", AsyncMock()), \
         patch("services.sync_job_execution.send_job_notification_helper", AsyncMock()), \
         patch("services.sync_job_execution._try_register_vm_after_sync", AsyncMock()):
        await execute_sync_job_task(jid)
    db.expire_all()
    return db.query(JobLog).filter(JobLog.job_id == jid).one()


@pytest.mark.asyncio
async def test_successo_con_output_chiude_il_log_success(db, job):
    jid, n1_id = job
    log = await _corsa(db, jid, n1_id, {"success": True, "duration": 3, "output": "NEWEST SNAPSHOT: …", "transferred": "1G"})
    assert log.status == "success"
    assert "Sincronizzazione completata" in (log.message or "")
    assert log.completed_at is not None


@pytest.mark.asyncio
async def test_fallimento_con_output_conserva_l_errore(db, job):
    jid, n1_id = job
    log = await _corsa(db, jid, n1_id, {
        "success": False, "duration": 1, "command": "syncoid …",
        "error": "CRITICAL ERROR: cannot receive", "output": "some output with error",
    })
    assert log.status == "failed"
    assert log.error and "CRITICAL ERROR: cannot receive" in log.error
