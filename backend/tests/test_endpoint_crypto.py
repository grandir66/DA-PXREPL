"""Test cifratura endpoint."""

import os

import pytest

from services.file_replication.endpoint_crypto import decrypt_password, encrypt_password


def test_encrypt_decrypt_roundtrip():
    os.environ["DAPX_SECRET_KEY"] = "test-secret-key-for-testing-only"
    enc = encrypt_password("s3cr3t!")
    assert enc != "s3cr3t!"
    assert decrypt_password(enc) == "s3cr3t!"


def test_decrypt_invalid_raises():
    with pytest.raises(ValueError):
        decrypt_password("not-valid-token")
