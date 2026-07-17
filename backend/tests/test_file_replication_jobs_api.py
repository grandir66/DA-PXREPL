"""Test API file replication jobs."""

from database import FileEndpoint, FileEndpointRole, FileEndpointType, FileReplicationJob


def _seed_endpoints(db):
    src = FileEndpoint(
        name="src-linux",
        endpoint_type=FileEndpointType.LINUX,
        role=FileEndpointRole.SOURCE,
        host="10.0.0.1",
        port=22,
        protocol="ssh",
        username="backup",
        password_enc="enc",
    )
    dest = FileEndpoint(
        name="dest-qnap",
        endpoint_type=FileEndpointType.QNAP,
        role=FileEndpointRole.DESTINATION,
        host="10.0.0.2",
        port=8080,
        protocol="ssh",
        username="admin",
        password_enc="enc",
    )
    db.add_all([src, dest])
    db.commit()
    db.refresh(src)
    db.refresh(dest)
    return src, dest


def test_create_file_replication_job(client, auth_headers, db):
    src, dest = _seed_endpoints(db)
    r = client.post(
        "/api/file-replication",
        headers=auth_headers,
        json={
            "name": "archivio-test",
            "source_endpoint_id": src.id,
            "dest_endpoint_id": dest.id,
            "source_paths": ["/documenti"],
            "dest_staging_path": "/staging/archivio",
            "schedule": "0 2 * * *",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "archivio-test"
    assert data["dest_endpoint_name"] == "dest-qnap"


def test_reject_non_qnap_destination(client, auth_headers, db):
    src = FileEndpoint(
        name="src",
        endpoint_type=FileEndpointType.LINUX,
        role=FileEndpointRole.SOURCE,
        host="10.0.0.1",
        port=22,
        protocol="ssh",
        username="u",
        password_enc="x",
    )
    bad_dest = FileEndpoint(
        name="bad",
        endpoint_type=FileEndpointType.LINUX,
        role=FileEndpointRole.DESTINATION,
        host="10.0.0.3",
        port=22,
        protocol="ssh",
        username="u",
        password_enc="x",
    )
    db.add_all([src, bad_dest])
    db.commit()

    r = client.post(
        "/api/file-replication",
        headers=auth_headers,
        json={
            "name": "bad-job",
            "source_endpoint_id": src.id,
            "dest_endpoint_id": bad_dest.id,
            "source_paths": ["/data"],
            "dest_staging_path": "/staging/data",
        },
    )
    assert r.status_code == 400
