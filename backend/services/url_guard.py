"""Guard anti-SSRF per URL configurabili (webhook).

Blocca gli obiettivi pericolosi classici (loopback, link-local incluso l'endpoint
metadata cloud 169.254.169.254, multicast/reserved) e ammette solo http/https.
Le reti private RFC1918 restano ammesse di proposito: dapx è uno strumento
infrastrutturale e può legittimamente notificare servizi interni.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeUrlError(ValueError):
    """URL webhook rifiutato dal guard SSRF."""


def _resolved_ips(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None)
    return list({info[4][0] for info in infos})


def assert_safe_webhook_url(url: str) -> None:
    """Solleva UnsafeUrlError se l'URL non è un target webhook sicuro."""
    if not url:
        raise UnsafeUrlError("URL webhook vuoto")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrlError(f"Schema non consentito: {parsed.scheme or '—'} (solo http/https)")
    host = parsed.hostname
    if not host:
        raise UnsafeUrlError("Host webhook mancante")

    try:
        ips = _resolved_ips(host)
    except OSError as exc:
        raise UnsafeUrlError(f"Host webhook non risolvibile: {exc}") from exc

    for ip_str in ips:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            raise UnsafeUrlError(f"IP non valido nella risoluzione di {host}: {ip_str}")
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise UnsafeUrlError(
                f"Target webhook non consentito ({host} → {ip_str}): "
                "loopback/link-local/metadata/reserved bloccati"
            )
