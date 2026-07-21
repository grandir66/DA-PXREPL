"""Cifratura simmetrica dei segreti applicativi.

Fernet con chiave derivata SHA-256 da DAPX_SECRET_KEY: identica alla logica
storica di services/file_replication/endpoint_crypto.py, di cui questo modulo
è la generalizzazione (i token esistenti restano decifrabili).
"""

import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


def _fernet() -> Fernet:
    secret = os.environ.get("DAPX_SECRET_KEY") or os.environ.get("SANOID_MANAGER_SECRET_KEY")
    if not secret:
        raise RuntimeError("DAPX_SECRET_KEY non configurata")
    digest = hashlib.sha256(secret.encode()).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(plain: str) -> str:
    if not plain:
        return ""
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        logger.warning("decrypt_secret: token invalido")
        raise ValueError("segreto non decifrabile") from exc


def is_encrypted(value: str) -> bool:
    """True se value è un token Fernet decifrabile con la chiave corrente."""
    if not value:
        return False
    try:
        _fernet().decrypt(value.encode())
        return True
    except InvalidToken:
        return False
