"""Cifratura password endpoint replica file.

Wrapper di compatibilità: la logica vive in services.secrets (stessa chiave,
stesso algoritmo — i token già salvati restano validi).
"""

from services.secrets import decrypt_secret, encrypt_secret


def encrypt_password(plain: str) -> str:
    return encrypt_secret(plain)


def decrypt_password(token: str) -> str:
    try:
        return decrypt_secret(token)
    except ValueError as exc:
        raise ValueError("password endpoint non decifrabile") from exc
