"""Test build comandi rsync replica file."""

from database import FileEndpoint, FileEndpointRole, FileEndpointType, FileReplicationJob
from services.file_replication.file_sync_service import _ssh_port, build_rsync_legs


def test_synology_api_endpoint_uses_ssh_port_22(db):
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

    assert _ssh_port(src) == 22
    assert _ssh_port(dest) == 22

    legs = build_rsync_legs(job, src, dest, "/tmp/exclude.txt", "/tmp/staging")
    pull = legs[0]
    push = legs[1]
    assert "-e" in pull
    pull_e = pull[pull.index("-e") + 1]
    assert "ssh -p 22" in pull_e
    push_e = push[push.index("-e") + 1]
    assert "ssh -p 22" in push_e
    assert "qnap@172.16.1.120:/volume1/DATI/archivio/" in pull
    assert "--rsync-path=/usr/bin/rsync" in pull
    assert "replica@172.16.1.125:/share/DATI/archivio/" in push
