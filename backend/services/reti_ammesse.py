"""Reti da cui l'app accetta richieste (filtro prima delle rotte).

Incidente del 25/11/2026: l'app ascolta su tutte le interfacce e su un Proxmox
con IP pubblico (OVH) rispondeva a chiunque, pagina di accesso e rotte senza
login comprese (`/api/auth/setup` crea l'admin se non c'è ancora un utente).

Chiave `DAPX_ALLOWED_NETS` (in `/etc/dapx-unified/dapx-unified.env`):
- assente o vuota: solo reti private, loopback, link-local e CGNAT (le VPN);
- elenco separato da virgole di reti o indirizzi (`10.0.0.0/8,203.0.113.7`):
  solo quelle, più il loopback;
- `*`: nessun filtro (scelta esplicita, si vede nel log all'avvio).

Fallisce chiuso: una voce illeggibile si scarta e si scrive nel log; un
indirizzo del chiamante che non si riesce a leggere viene rifiutato.
"""

from __future__ import annotations

import ipaddress
import logging
import os
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

CHIAVE = "DAPX_ALLOWED_NETS"

_LOOPBACK = ("127.0.0.0/8", "::1/128")
_PRIVATE = _LOOPBACK + (
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "100.64.0.0/10",   # CGNAT: NetBird, Tailscale
    "fc00::/7",
    "fe80::/10",
)

_MAX_IP_NEL_LOG = 500


def _reti(voci: Iterable[str]) -> list:
    reti = []
    for voce in voci:
        try:
            reti.append(ipaddress.ip_network(voce.strip(), strict=False))
        except ValueError:
            logger.error("%s: voce non valida scartata: %r", CHIAVE, voce)
    return reti


def leggi_reti(valore: Optional[str] = None) -> Optional[list]:
    """Le reti ammesse; None vuol dire «tutte» (solo con `*`)."""
    if valore is None:
        valore = os.environ.get(CHIAVE, "")
    valore = valore.strip()
    if valore == "*":
        return None
    voci = [v for v in valore.split(",") if v.strip()]
    if not voci:
        return _reti(_PRIVATE)
    reti = _reti(voci)
    if not reti:
        logger.error("%s senza voci valide: si torna alle sole reti private", CHIAVE)
        return _reti(_PRIVATE)
    return reti + _reti(_LOOPBACK)


def ammesso(host: Optional[str], reti: Optional[list]) -> bool:
    if reti is None:
        return True
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    mappato = getattr(ip, "ipv4_mapped", None)
    if mappato is not None:
        ip = mappato
    return any(ip.version == rete.version and ip in rete for rete in reti)


class FiltroReti:
    """Middleware ASGI: 403 a chi arriva da una rete non ammessa."""

    def __init__(self, app, reti: Optional[list] = None, leggi_env: bool = True):
        self.app = app
        self.reti = leggi_reti() if leggi_env else reti
        self._gia_scritti: set = set()
        if self.reti is None:
            logger.warning("%s=*: l'app risponde a qualunque indirizzo", CHIAVE)
        else:
            logger.info("Reti ammesse: %s", ", ".join(str(r) for r in self.reti))

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        host = client[0] if client else None
        if ammesso(host, self.reti):
            await self.app(scope, receive, send)
            return
        if host not in self._gia_scritti and len(self._gia_scritti) < _MAX_IP_NEL_LOG:
            self._gia_scritti.add(host)
            logger.warning("Richiesta rifiutata: %s non è in una rete ammessa (%s)", host, CHIAVE)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        corpo = b"Forbidden"
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [(b"content-type", b"text/plain"), (b"content-length", str(len(corpo)).encode())],
        })
        await send({"type": "http.response.body", "body": corpo})
