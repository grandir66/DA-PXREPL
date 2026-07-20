"""sshpass deve usare -e + SSHPASS, mai -p con password in argv."""

from database import FileEndpoint, FileEndpointType
from services.file_replication.endpoint_crypto import encrypt_password
from services.file_replication.file_sync_service import _ssh_env, _ssh_transport


def test_ssh_transport_password_uses_sshpass_e(monkeypatch):
    monkeypatch.setenv("DAPX_SECRET_KEY", "test-secret-key-for-unit-tests-32b")
    # re-import crypto binding if needed — encrypt with current key
    from services.file_replication import endpoint_crypto as crypto

    enc = crypto.encrypt_password("segreta")
    ep = FileEndpoint(
        name="s",
        endpoint_type=FileEndpointType.LINUX,
        host="10.0.0.1",
        port=22,
        protocol="ssh",
        username="u",
        password_enc=enc,
        extra_config={},
    )
    transport = _ssh_transport(ep)
    assert "sshpass -e" in transport
    assert "segreta" not in transport
    assert "-p segreta" not in transport
    env = _ssh_env(ep)
    assert env == {"SSHPASS": "segreta"}


def test_ssh_transport_key_has_no_sshpass():
    ep = FileEndpoint(
        name="s",
        endpoint_type=FileEndpointType.LINUX,
        host="10.0.0.1",
        port=22,
        protocol="ssh",
        username="u",
        password_enc=None,
        ssh_key_path="/tmp/id_rsa",
        extra_config={},
    )
    transport = _ssh_transport(ep)
    assert "sshpass" not in transport
    assert "-i /tmp/id_rsa" in transport
    assert _ssh_env(ep) == {}
