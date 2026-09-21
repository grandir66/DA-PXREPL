"""La corsa di replica segue la VM (3.23.0): prove sul percorso di esecuzione.

Il localizzatore ha le sue prove (test_vm_locator.py); qui si guarda cosa fa
`execute_sync_job_task` con i suoi esiti: parte dal nodo risolto e lo
persiste, rifiuta PRIMA di partire con un motivo leggibile, riconosce il
rifiuto di syncoid «no snapshots matching» e lo traduce, e la corsa una
tantum «replica completa» passa --force-delete a syncoid.
"""

from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest

from database import JobLog, Node, SyncJob
from services import vm_locator
from tests.conftest import TestingSessionLocal
from services.ssh_service import SSHResult
from services.vm_locator import Posizione


def _posizione(db, esito, nodo_id, nodo_pve, messaggio):
    """Un finto `risolvi_nodo_sorgente` che carica il Node quando viene
    chiamato: la corsa chiude la sessione, un Node preso prima sarebbe detached."""
    async def finto(*a, **k):
        return Posizione(esito, db.get(Node, nodo_id) if nodo_id else None, nodo_pve, messaggio)
    return AsyncMock(side_effect=finto)


def _corsa(db, posizione, run):
    """I doppi comuni a ogni corsa: sessione, localizzatore, syncoid, ssh, poller, notifiche.
    All'uscita `db` scarta quel che ha in memoria: la corsa ha scritto da un'altra sessione."""
    stack = ExitStack()
    stack.callback(db.expire_all)
    # La corsa apre la SUA sessione (come in esercizio, autoflush attivo:
    # `db_session.refresh(log_entry)` nel codice conta sul flush automatico
    # per non perdere lo stato appena scritto). Stesso engine del `db` di prova.
    stack.enter_context(patch("database.SessionLocal", side_effect=lambda: TestingSessionLocal(autoflush=True)))
    stack.enter_context(patch("services.vm_locator.risolvi_nodo_sorgente", posizione))
    stack.enter_context(patch("services.syncoid_service.syncoid_service.run_sync", run))
    stack.enter_context(patch(
        "services.ssh_service.ssh_service.execute",
        AsyncMock(return_value=SSHResult(success=True, stdout="ZFS/replica\n", stderr="", exit_code=0)),
    ))
    stack.enter_context(patch("services.sync_job_execution._poll_sync_progress", AsyncMock()))
    stack.enter_context(patch("services.sync_job_execution.send_job_notification_helper", AsyncMock()))
    stack.enter_context(patch("services.sync_job_execution._try_register_vm_after_sync", AsyncMock()))
    return stack


@pytest.fixture(autouse=True)
def _cache_pulita():
    vm_locator.svuota_cache()
    yield
    vm_locator.svuota_cache()


@pytest.fixture
def scenario(db):
    n1 = Node(name="px-01", hostname="px-01", node_type="pve", is_active=True, is_online=True)
    n2 = Node(name="px-02", hostname="px-02", node_type="pve", is_active=True, is_online=True)
    n4 = Node(name="px-04", hostname="px-04", node_type="pve", is_active=True, is_online=True)
    db.add_all([n1, n2, n4])
    db.flush()
    jobs = []
    for d in ("scsi0", "scsi1"):
        j = SyncJob(
            name=f"VM 101 {d}", source_node_id=n1.id, dest_node_id=n4.id,
            source_dataset=f"rpool/data/vm-101-{d}", dest_dataset=f"ZFS/replica/vm-101-{d}",
            vm_id=101, dest_vm_id=9101, vm_group_id="grp-101", disk_name=d,
            register_vm=False, sync_method="syncoid", is_active=True,
        )
        db.add(j)
        jobs.append(j)
    db.commit()
    return n1, n2, n4, jobs


def _syncoid_ok():
    return AsyncMock(return_value={"success": True, "duration": 3, "output": "ok", "transferred": "1G"})


def _syncoid_senza_snapshot():
    return AsyncMock(return_value={
        "success": False, "duration": 1, "command": "syncoid …",
        "error": "CRITICAL ERROR: Target ZFS/replica/vm-101-scsi0 exists but has no snapshots matching with rpool/data/vm-101-scsi0!",
        "output": "Cowardly refusing to destroy your existing target.",
    })


@pytest.mark.asyncio
async def test_parte_dal_nodo_risolto_e_lo_ricorda(db, scenario):
    n1, n2, n4, jobs = scenario
    from services.sync_job_execution import execute_sync_job_task

    ids = [j.id for j in jobs]
    n2_id = n2.id
    spostata = _posizione(db, "spostata", n2_id, "px-02", "VM 101 trovata su px-02 (era registrata su px-01): eseguo da px-02")
    run = _syncoid_ok()
    with _corsa(db, spostata, run):
        await execute_sync_job_task(ids[0])

    assert run.await_args.kwargs["executor_host"] == "px-02"
    assert run.await_args.kwargs["force_delete"] is False
    for jid in ids:
        assert db.get(SyncJob, jid).source_node_id == n2_id  # tutti i dischi del gruppo
    log = db.query(JobLog).filter(JobLog.job_id == ids[0]).one()
    assert log.status == "success", log.error
    assert "Posizione VM: VM 101 trovata su px-02" in log.output
    assert log.node_name == "px-02 -> px-04"


@pytest.mark.asyncio
async def test_rifiutata_fallisce_prima_di_partire_con_motivo(db, scenario):
    n1, n2, n4, jobs = scenario
    from services.sync_job_execution import execute_sync_job_task

    jid, n1_id = jobs[0].id, n1.id
    rifiuto = _posizione(db, "rifiutata", None, "px-05", "VM 101 è migrata su px-05, che non è censito in DA-PXREPL: censire il nodo…")
    run = _syncoid_ok()
    notifica = AsyncMock()
    with _corsa(db, rifiuto, run), \
         patch("services.sync_job_execution.send_job_notification_helper", notifica):
        esito = await execute_sync_job_task(jid)

    assert esito is False
    run.assert_not_awaited()
    job = db.get(SyncJob, jid)
    assert job.last_status == "failed" and job.error_count == 1
    assert job.source_node_id == n1_id  # non si tocca
    log = db.query(JobLog).filter(JobLog.job_id == jid).one()
    assert log.status == "failed" and "non è censito" in log.error
    assert notifica.await_args.kwargs["status"] == "failed"
    assert "px-05" in notifica.await_args.kwargs["error"]


@pytest.mark.asyncio
async def test_non_so_usa_il_nodo_registrato_e_lo_scrive(db, scenario):
    n1, n2, n4, jobs = scenario
    from services.sync_job_execution import execute_sync_job_task

    jid = jobs[0].id
    non_so = _posizione(db, "non_so", n1.id, None, "il cluster di px-01 non risponde: uso il nodo registrato")
    run = _syncoid_ok()
    with _corsa(db, non_so, run):
        await execute_sync_job_task(jid)
    assert run.await_args.kwargs["executor_host"] == "px-01"
    log = db.query(JobLog).filter(JobLog.job_id == jid).one()
    assert "uso il nodo registrato" in log.output


@pytest.mark.asyncio
async def test_senza_snapshot_in_comune_dopo_migrazione_motivo_e_flag(db, scenario):
    n1, n2, n4, jobs = scenario
    from services.sync_job_execution import execute_sync_job_task

    jid = jobs[0].id
    spostata = _posizione(db, "spostata", n2.id, "px-02", "VM 101 trovata su px-02 (era registrata su px-01): eseguo da px-02")
    with _corsa(db, spostata, _syncoid_senza_snapshot()):
        await execute_sync_job_task(jid)

    job = db.get(SyncJob, jid)
    assert job.last_status == "failed"
    assert job.richiede_replica_completa is True
    log = db.query(JobLog).filter(JobLog.job_id == jid).one()
    assert log.error.startswith("[REPLICA-COMPLETA] VM migrata su px-02")
    assert "migrazione live" in log.error and "Esegui con replica completa" in log.error


@pytest.mark.asyncio
async def test_replica_completa_una_tantum_passa_force_delete_e_azzera_il_flag(db, scenario):
    n1, n2, n4, jobs = scenario
    from services.sync_job_execution import execute_sync_job_task

    jid, n1_id = jobs[0].id, n1.id
    jobs[0].richiede_replica_completa = True
    db.commit()
    uguale = _posizione(db, "uguale", n1_id, "px-01", "")
    run = _syncoid_ok()
    with _corsa(db, uguale, run):
        await execute_sync_job_task(jid, replica_completa=True)

    assert run.await_args.kwargs["force_delete"] is True
    assert db.get(SyncJob, jid).richiede_replica_completa is False
    log = db.query(JobLog).filter(JobLog.job_id == jid).one()
    assert "Replica COMPLETA richiesta" in log.output


@pytest.mark.asyncio
async def test_resync_dopo_migrazione_acceso_forza_solo_se_spostata(db, scenario):
    n1, n2, n4, jobs = scenario
    from services.sync_job_execution import execute_sync_job_task

    jid, n1_id, n2_id = jobs[0].id, n1.id, n2.id
    jobs[0].resync_dopo_migrazione = True
    db.commit()
    run = _syncoid_ok()
    # non spostata → niente force
    with _corsa(db, _posizione(db, "uguale", n1_id, "px-01", ""), run):
        await execute_sync_job_task(jid)
    assert run.await_args.kwargs["force_delete"] is False
    # spostata → force per quella corsa
    spostata = _posizione(db, "spostata", n2_id, "px-02", "VM 101 trovata su px-02 (era registrata su px-01): eseguo da px-02")
    with _corsa(db, spostata, run):
        await execute_sync_job_task(jid)
    assert run.await_args.kwargs["force_delete"] is True


def test_run_route_accetta_replica_completa(client, operator_user, operator_token, db, scenario):
    """`POST /sync-jobs/{id}/run?replica_completa=true` la passa al runner."""
    n1, n2, n4, jobs = scenario
    catturato = {}

    def finto_bg(job_id, job_key, user_id, replica_completa=False):
        catturato["replica_completa"] = replica_completa
        catturato["job_id"] = job_id

    with patch("routers.sync_jobs._run_vm_group_background") as gruppo, \
         patch("routers.sync_jobs._run_sync_job_background", finto_bg):
        # il job sta in un gruppo: la rotta delega al gruppo
        r = client.post(
            f"/api/sync-jobs/{jobs[0].id}/run?replica_completa=true",
            headers={"Authorization": f"Bearer {operator_token}"},
        )
    assert r.status_code == 200, r.text
    # la rotta del gruppo riceve il flag come sesto argomento
    from services.scheduler import scheduler_service
    scheduler_service.mark_done(f"vmgroup_grp-101")
    assert gruppo.called
    args = gruppo.call_args.args if gruppo.call_args else ()
    assert args and args[-1] is True


def test_group_run_route_accetta_replica_completa(client, operator_user, operator_token, db, scenario):
    n1, n2, n4, jobs = scenario
    from services.scheduler import scheduler_service

    with patch("routers.sync_jobs._run_vm_group_background") as gruppo:
        r = client.post(
            "/api/sync-jobs/vm-group/grp-101/run?replica_completa=true",
            headers={"Authorization": f"Bearer {operator_token}"},
        )
    scheduler_service.mark_done("vmgroup_grp-101")
    assert r.status_code == 200, r.text
    assert gruppo.call_args.args[-1] is True
