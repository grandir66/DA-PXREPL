"""Test esecuzione job replica file."""

from unittest.mock import MagicMock, patch

import pytest

from database import FileEndpoint, FileEndpointRole, FileEndpointType, FileReplicationJob, JobLog
from services.file_replication import file_replication_execution as exec_mod


@pytest.mark.asyncio
async def test_preflight_missing_rsync(db):
    src = FileEndpoint(
        name="src",
        endpoint_type=FileEndpointType.SYNOLOGY,
        role=FileEndpointRole.SOURCE,
        host="10.0.0.1",
        port=22,
        protocol="ssh",
        username="u",
        password_enc="enc",
    )
    dest = FileEndpoint(
        name="dest",
        endpoint_type=FileEndpointType.QNAP,
        role=FileEndpointRole.DESTINATION,
        host="10.0.0.2",
        port=22,
        protocol="ssh",
        username="admin",
        password_enc="enc",
    )
    job = FileReplicationJob(
        name="t",
        source_endpoint_id=1,
        dest_endpoint_id=2,
        source_paths=["/volume1/data"],
        dest_staging_path="/share/DATI/staging",
    )
    db.add_all([src, dest, job])
    db.commit()
    job_id = job.id

    with patch.object(exec_mod, "SessionLocal", return_value=db), patch.object(
        exec_mod.shutil, "which", return_value=None
    ), patch.object(exec_mod, "decrypt_password", return_value="secret"):
        await exec_mod.execute_file_replication_job(job_id)

    # NON `db.refresh(job)`: il codice sotto prova possiede la sessione che
    # `SessionLocal` gli restituisce e nel `finally` la chiude — `close()`
    # sgancia dalla sessione tutte le istanze, e un `refresh` su un oggetto
    # sganciato alza «Instance is not persistent within this Session». La
    # sessione resta però usabile (ne apre una nuova alla prossima query), e
    # rileggere da zero è anche una verifica più forte: dice cosa c'è
    # davvero nel database, non cosa ricordava l'oggetto in memoria.
    job = (
        db.query(FileReplicationJob)
        .filter(FileReplicationJob.id == job_id)
        .first()
    )
    assert job is not None
    assert job.last_run_status == "failed"
    assert job.current_status == "failed", "un job fallito non resta 'running'"
    log = (
        db.query(JobLog)
        .filter(JobLog.job_type == "file_replication", JobLog.job_id == job_id)
        .order_by(JobLog.id.desc())
        .first()
    )
    assert log is not None
    assert log.error is not None
    assert "rsync" in log.error.lower()
