"""Test piano sync Synology SMB."""

from database import FileEndpoint, FileEndpointRole, FileEndpointType, FileReplicationJob
from services.file_replication.file_sync_service import build_sync_plan


def test_synology_uses_smb_pull_not_ssh(db):
    src = FileEndpoint(
        name="syn",
        endpoint_type=FileEndpointType.SYNOLOGY,
        role=FileEndpointRole.SOURCE,
        host="172.16.1.120",
        port=5001,
        protocol="api",
        username="qnap",
        password_enc="enc",
    )
    dest = FileEndpoint(
        name="qnap",
        endpoint_type=FileEndpointType.QNAP,
        role=FileEndpointRole.DESTINATION,
        host="172.16.1.125",
        port=443,
        protocol="api",
        username="domarc",
        password_enc="enc",
    )
    job = FileReplicationJob(
        name="t",
        source_endpoint_id=1,
        dest_endpoint_id=2,
        source_paths=["/Comune/AArchivio"],
        dest_staging_path="/share/DATI/archivio",
    )
    db.add_all([src, dest, job])
    db.commit()

    plan = build_sync_plan(job, src, dest, "/tmp/exclude.txt", "/tmp/staging")
    assert len(plan) == 1
    assert plan[0]["type"] == "rclone_sync"
    assert plan[0]["delete_on_dest"] is True
    assert plan[0]["dest_dir"] == "/share/DATI/archivio/AArchivio/"
