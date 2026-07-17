"""Messaggi errore connessione verso endpoint NAS."""

from __future__ import annotations

import httpx


def format_connection_error(host: str, port: int, exc: Exception) -> str:
    target = f"{host}:{port}"
    if isinstance(exc, httpx.ConnectTimeout):
        return (
            f"Timeout connessione a {target}: il server dapx non raggiunge il NAS "
            f"(rete, routing o firewall)."
        )
    if isinstance(exc, httpx.ConnectError):
        msg = str(exc).lower()
        if "certificate" in msg or "ssl" in msg or "tls" in msg:
            return (
                f"Errore certificato SSL su {target}: il Synology usa un certificato "
                f"auto-firmato. Disabilita «Verifica certificato SSL» nell'endpoint."
            )
        return (
            f"Host {target} non raggiungibile dal server dapx. "
            f"Controlla IP, porta e firewall."
        )
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code} da {target}"
    if isinstance(exc, httpx.TimeoutException):
        return f"Timeout risposta da {target}"
    return str(exc)
