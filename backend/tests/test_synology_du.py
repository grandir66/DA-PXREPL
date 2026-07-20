"""Test du Synology via SSH."""

import pytest

from services.file_replication.synology_du import _DU_BYTES_RE, synology_du_bytes


def test_du_bytes_regex():
    assert _DU_BYTES_RE.match("2684354560000").group(1) == "2684354560000"


@pytest.mark.asyncio
async def test_synology_du_parses_stdout(monkeypatch):
    class FakeProc:
        returncode = 0

        async def communicate(self):
            return b"2684354560000\n", b""

    async def fake_exec(*_args, **_kwargs):
        return FakeProc()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    class Ep:
        endpoint_type = "synology"
        host = "172.16.1.120"
        username = "qnap"
        password_enc = "x"
        ssh_key_path = None
        protocol = "ssh"
        port = 22
        extra_config = {}

    monkeypatch.setattr(
        "services.file_replication.synology_du.decrypt_password",
        lambda _enc: "secret",
    )

    n = await synology_du_bytes(Ep(), "/Comune")
    assert n == 2684354560000
