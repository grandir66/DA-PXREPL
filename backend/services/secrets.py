"""Cifratura segreti a riposo con FALLBACK TRASPARENTE sui valori legacy in chiaro.

Design non-breaking (S-06):
- I valori cifrati sono marcati dal prefisso ``enc:v1:``.
- ``decrypt_secret`` su un valore SENZA prefisso lo ritorna tale e quale
  (i segreti già salvati in chiaro continuano a funzionare senza migrazione).
- ``encrypt_secret`` è idempotente (non ri-cifra un valore già cifrato).
- Un token cifrato ma non decifrabile viene ritornato com'è, mai un'eccezione
  che bloccherebbe notifiche/invii.

Usa la stessa chiave (`DAPX_SECRET_KEY`) del resto del sistema.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    secret = os.environ.get("DAPX_SECRET_KEY") or os.environ.get("SANOID_MANAGER_SECRET_KEY")
    if not secret:
        raise RuntimeError("DAPX_SECRET_KEY non configurata")
    digest = hashlib.sha256(secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def is_encrypted(value: Optional[str]) -> bool:
    return bool(value) and isinstance(value, str) and value.startswith(_PREFIX)


def encrypt_secret(plain: Optional[str]) -> Optional[str]:
    """Cifra un segreto. None/'' passano invariati; un valore già cifrato resta tale."""
    if not plain:
        return plain
    if is_encrypted(plain):
        return plain
    try:
        return _PREFIX + _fernet().encrypt(plain.encode()).decode()
    except Exception as exc:  # noqa: BLE001 — non bloccare il salvataggio
        logger.warning("encrypt_secret fallita, salvo in chiaro come fallback: %s", exc)
        return plain


def decrypt_secret(value: Optional[str]) -> Optional[str]:
    """Decifra se cifrato; altrimenti (legacy plaintext) ritorna il valore invariato."""
    if not is_encrypted(value):
        return value
    try:
        return _fernet().decrypt(value[len(_PREFIX):].encode()).decode()
    except InvalidToken:
        logger.warning("decrypt_secret: token non valido, ritorno il valore grezzo")
        return value
