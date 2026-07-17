"""Test build comandi rsync replica file."""

from database import FileEndpoint, FileEndpointRole, FileEndpointType, FileReplicationJob
from services.file_replication.file_sync_service import build_rsync_legs, build_sync_plan


def test_synology_push_only_in_rsync_legs_compat(db):
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
        username="replica",
        password_enc="enc",
    )
    job = FileReplicationJob(
        name="t",
        source_endpoint_id=1,
        dest_endpoint_id=2,
        source_paths=["/DATI/archivio"],
        dest_staging_path="/share/DATI/archivio",
    )
    db.add_all([src, dest, job])
    db.commit()

    legs = build_rsync_legs(job, src, dest, "/tmp/exclude.txt", "/tmp/staging")
    assert len(legs) == 1
    push = legs[0]
    push_e = push[push.index("-e") + 1]
    assert "ssh -p 22" in push_e
    assert "domarc@172.16.1.125:/share/DATI/archivio/" in push

    plan = build_sync_plan(job, src, dest, "/tmp/exclude.txt", "/tmp/staging")
    assert plan[0]["type"] == "stream_tar"
