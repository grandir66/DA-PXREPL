"""Cifratura password endpoint replica file."""

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


def encrypt_password(plain: str) -> str:
    if not plain:
        return ""
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_password(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        logger.warning("decrypt_password: token invalido")
        raise ValueError("password endpoint non decifrabile") from exc
