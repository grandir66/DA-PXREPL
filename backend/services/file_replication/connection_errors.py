"""Messaggi errore connessione verso endpoint NAS."""

from __future__ import annotations

import httpx


def format_connection_error(host: str, port: int, exc: Exception) -> str:
    target = f"{host}:{port}"
    if isinstance(exc, httpx.ConnectTimeout):
        return (
            f"Timeout connessione a {target}: il server dapx non raggiunge il NAS "
            f"(rete, routing o firewall). Verifica che l'host sia raggiungibile da "
            f"192.168.4.199."
        )
    if isinstance(exc, httpx.ConnectError):
        return (
            f"Host {target} non raggiungibile dal server dapx. "
            f"Controlla IP, porta e routing tra le VLAN."
        )
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code} da {target}"
    if isinstance(exc, httpx.TimeoutException):
        return f"Timeout risposta da {target}"
    return str(exc)
