"""La riprova automatica: una replica non è fallita al primo colpo.

`retry_on_failure`, `max_retries` e `retry_delay_minutes` stavano nel
database di ogni job e nelle API **dal primo giorno**, e nessun servizio di
esecuzione li leggeva: configurazione promessa e mai applicata, scoperta il
2026-09-08. Questi test tengono ferma l'implementazione.

Perché serve: syncoid cade anche per un «dataset is busy» o uno snapshot
ancora in corso — cose che un'ora dopo non ci sono più. Fallita è la replica
che non passa **nemmeno alla riprova**.
"""

import asyncio
from datetime import datetime, timedelta

import pytest

from database import Node, SyncJob
from services.scheduler import SchedulerService


@pytest.fixture
def job_fallito(db):
    db.add(Node(name="px1", hostname="10.0.0.1", ssh_port=22, ssh_user="root",
                ssh_key_path="/k"))
    db.commit()
    j = SyncJob(name="repl", source_node_id=1, dest_node_id=1, source_dataset="a",
                dest_dataset="b", is_active=True, schedule="0 2 * * *",
                last_status="failed", retry_on_failure=True, max_retries=1,
                retry_delay_minutes=60)
    db.add(j)
    db.commit()
    return j


@pytest.fixture
def scheduler(monkeypatch, db):
    s = SchedulerService()
    from services import scheduler as modulo
    monkeypatch.setattr(modulo, "SessionLocal", lambda: db)
    # `_valuta_riprova` chiude la sessione: qui è quella condivisa del test.
    monkeypatch.setattr(db, "close", lambda: None)
    return s


def test_un_fallimento_programma_la_riprova_fra_unora(scheduler, job_fallito):
    prima = datetime.utcnow()
    scheduler._valuta_riprova("sync_1", job_fallito.id, tentativo=1)

    assert "sync_1" in scheduler._riprove
    r = scheduler._riprove["sync_1"]
    assert r["tentativo"] == 2
    attesa = (r["quando"] - prima).total_seconds() / 60
    assert 59 <= attesa <= 61, f"attesa di {attesa:.0f} minuti invece di 60"


def test_una_replica_riuscita_non_programma_niente(scheduler, job_fallito, db):
    job_fallito.last_status = "success"
    db.commit()
    scheduler._valuta_riprova("sync_1", job_fallito.id, tentativo=1)
    assert scheduler._riprove == {}


def test_dopo_lultimo_tentativo_ci_si_arrende(scheduler, job_fallito):
    """`max_retries=1` vuol dire UNA riprova: al secondo fallimento è un guasto."""
    scheduler._valuta_riprova("sync_1", job_fallito.id, tentativo=2)
    assert scheduler._riprove == {}


def test_un_job_con_la_riprova_spenta_non_riprova(scheduler, job_fallito, db):
    job_fallito.retry_on_failure = False
    db.commit()
    scheduler._valuta_riprova("sync_1", job_fallito.id, tentativo=1)
    assert scheduler._riprove == {}


def test_lattesa_del_job_vince_sul_predefinito(scheduler, job_fallito, db):
    """Chi ha scelto a mano un'attesa diversa se la tiene."""
    job_fallito.retry_delay_minutes = 15
    db.commit()
    prima = datetime.utcnow()
    scheduler._valuta_riprova("sync_1", job_fallito.id, tentativo=1)
    attesa = (scheduler._riprove["sync_1"]["quando"] - prima).total_seconds() / 60
    assert 14 <= attesa <= 16


def test_la_riprova_scaduta_parte(scheduler, monkeypatch):
    partite = []

    async def finto(job_key, job_id, tentativo=1):
        partite.append((job_key, job_id, tentativo))

    monkeypatch.setattr(scheduler, "_guarded_execute_sync_job", finto)
    scheduler._riprove["sync_1"] = {
        "quando": datetime.utcnow() - timedelta(seconds=1), "job_id": 1, "tentativo": 2,
    }

    async def giro():
        await scheduler._check_riprove()
        await asyncio.sleep(0)  # lascia partire il task

    asyncio.run(giro())
    assert partite == [("sync_1", 1, 2)]
    assert scheduler._riprove == {}, "la riprova resta in coda e si ripete all'infinito"


def test_una_riprova_non_ancora_scaduta_aspetta(scheduler, monkeypatch):
    partite = []
    monkeypatch.setattr(
        scheduler, "_guarded_execute_sync_job",
        lambda *a, **k: partite.append(a),
    )
    scheduler._riprove["sync_1"] = {
        "quando": datetime.utcnow() + timedelta(minutes=30), "job_id": 1, "tentativo": 2,
    }
    asyncio.run(scheduler._check_riprove())
    assert partite == []
    assert "sync_1" in scheduler._riprove


def test_non_si_riprova_un_job_gia_in_esecuzione(scheduler, monkeypatch):
    """Se lo slot cron è arrivato prima della riprova, non si raddoppia."""
    partite = []
    monkeypatch.setattr(
        scheduler, "_guarded_execute_sync_job",
        lambda *a, **k: partite.append(a),
    )
    scheduler._try_lock("sync_1")  # qualcun altro lo sta già facendo girare
    scheduler._riprove["sync_1"] = {
        "quando": datetime.utcnow() - timedelta(seconds=1), "job_id": 1, "tentativo": 2,
    }
    asyncio.run(scheduler._check_riprove())
    assert partite == []
    assert scheduler._riprove == {}


def test_il_numero_di_tentativo_arriva_al_job_log():
    """È `attempt_number` a distinguere una riprova da un nuovo slot cron."""
    import inspect
    from services import sync_job_execution
    sorgente = inspect.getsource(sync_job_execution.execute_sync_job_task)
    assert "tentativo: int = 1" in inspect.signature(
        sync_job_execution.execute_sync_job_task
    ).__str__() or "tentativo" in sorgente
    assert "attempt_number=tentativo" in sorgente
