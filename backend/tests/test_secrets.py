"""Test cifratura segreti a riposo con fallback trasparente (S-06)."""

import os

import pytest

from services.secrets import decrypt_secret, encrypt_secret, is_encrypted


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("DAPX_SECRET_KEY", "test-secret-key-for-testing-only")


def test_roundtrip():
    enc = encrypt_secret("s3cr3t-smtp!")
    assert enc.startswith("enc:v1:")
    assert enc != "s3cr3t-smtp!"
    assert decrypt_secret(enc) == "s3cr3t-smtp!"


def test_plaintext_passthrough():
    # Valore legacy in chiaro (senza prefisso) → ritornato invariato (non-breaking)
    assert decrypt_secret("password-in-chiaro") == "password-in-chiaro"
    assert is_encrypted("password-in-chiaro") is False


def test_encrypt_idempotent():
    enc = encrypt_secret("abc")
    assert encrypt_secret(enc) == enc  # non ri-cifra


def test_empty_and_none():
    assert encrypt_secret("") == ""
    assert encrypt_secret(None) is None
    assert decrypt_secret("") == ""
    assert decrypt_secret(None) is None


def test_bad_token_returns_raw():
    # Prefisso presente ma token non valido → ritorna grezzo, niente eccezione
    assert decrypt_secret("enc:v1:not-a-valid-token") == "enc:v1:not-a-valid-token"


def test_decrypt_wrong_key_returns_raw(monkeypatch):
    enc = encrypt_secret("abc")
    monkeypatch.setenv("DAPX_SECRET_KEY", "chiave-diversa-che-non-decifra")
    # Con chiave diversa non decifra: ritorna il token grezzo, non solleva
    assert decrypt_secret(enc) == enc
