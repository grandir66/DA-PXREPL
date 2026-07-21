"""Test cifratura segreti applicativi (services.secrets)."""

import os

import pytest

from services.file_replication.endpoint_crypto import decrypt_password, encrypt_password
from services.secrets import decrypt_secret, encrypt_secret, is_encrypted


def test_encrypt_decrypt_roundtrip():
    os.environ["DAPX_SECRET_KEY"] = "test-secret-key-for-testing-only"
    enc = encrypt_secret("s3cr3t!")
    assert enc != "s3cr3t!"
    assert decrypt_secret(enc) == "s3cr3t!"


def test_empty_values():
    assert encrypt_secret("") == ""
    assert decrypt_secret("") == ""
    assert is_encrypted("") is False


def test_decrypt_invalid_raises():
    os.environ["DAPX_SECRET_KEY"] = "test-secret-key-for-testing-only"
    with pytest.raises(ValueError):
        decrypt_secret("not-valid-token")


def test_is_encrypted():
    os.environ["DAPX_SECRET_KEY"] = "test-secret-key-for-testing-only"
    assert is_encrypted(encrypt_secret("x")) is True
    assert is_encrypted("password-in-chiaro") is False


def test_endpoint_crypto_compat():
    """I token di endpoint_crypto e secrets sono interscambiabili (stessa chiave/algoritmo)."""
    os.environ["DAPX_SECRET_KEY"] = "test-secret-key-for-testing-only"
    assert decrypt_secret(encrypt_password("abc")) == "abc"
    assert decrypt_password(encrypt_secret("abc")) == "abc"
