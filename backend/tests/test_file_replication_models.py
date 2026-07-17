"""Test modelli replica file."""

from database import FileEndpoint, FileEndpointRole, FileEndpointType, FileReplicationJob


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
