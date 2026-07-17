"""Test API file endpoints."""

from database import FileEndpoint, FileEndpointRole, FileEndpointType


def test_create_and_list_endpoint(client, auth_headers):
    r = client.post(
        "/api/file-endpoints",
        headers=auth_headers,
        json={
            "name": "linux-src",
            "endpoint_type": "linux",
            "role": "source",
            "host": "192.168.1.50",
            "port": 22,
            "protocol": "ssh",
            "username": "backup",
            "password": "secret",
        },
    )
    assert r.status_code == 200
    eid = r.json()["id"]
    r2 = client.get("/api/file-endpoints", headers=auth_headers)
    assert r.status_code == 200
    assert any(x["id"] == eid for x in r2.json())


def test_delete_endpoint_in_use_returns_409(client, auth_headers, db):
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
    dest = FileEndpoint(
        name="dest",
        endpoint_type=FileEndpointType.QNAP,
        role=FileEndpointRole.DESTINATION,
        host="10.0.0.2",
        port=8080,
        protocol="api",
        username="u",
        password_enc="x",
    )
    db.add_all([src, dest])
    db.commit()

    from database import FileReplicationJob

    job = FileReplicationJob(
        name="j1",
        source_endpoint_id=src.id,
        dest_endpoint_id=dest.id,
        source_paths=["/data"],
        dest_staging_path="/staging/data",
    )
    db.add(job)
    db.commit()

    r = client.delete(f"/api/file-endpoints/{src.id}", headers=auth_headers)
    assert r.status_code == 409
