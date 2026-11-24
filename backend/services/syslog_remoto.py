"""Invio di tutto il log a un syslog remoto (Wazuh, Graylog, rsyslog).

Riccardo, 24/11/2026: «inviare i log completi ad un syslog, in particolare a
Wazuh». Una riga per record, RFC 3164 con il corpo in JSON (lo stesso
`JSONFormatter` dei file), cosi' Wazuh lo decodifica senza regole a mano.

Nasce spento. L'invio passa da una coda: un collettore lento o spento non deve
fermare ne' rallentare il servizio. Gli errori di invio NON si scrivono nel
log (tornerebbero qui): si contano, e `stato()` li mostra in Impostazioni.
"""
import logging
import logging.handlers
import queue
import socket
import time
from datetime import datetime
from typing import Any, Dict, Optional

PROTOCOLLI = ("udp", "tcp")
_TAG = "dapx-unified"
_FACILITY_LOCAL0 = 16
_MAX_UDP = 60000          # sotto il tetto di un datagramma
_RIPROVA_TCP_S = 30       # dopo un errore TCP non si ritenta a ogni riga
_PRIORITA = {
    logging.DEBUG: 7, logging.INFO: 6, logging.WARNING: 4,
    logging.ERROR: 3, logging.CRITICAL: 2,
}

_coda_handler: Optional[logging.Handler] = None
_ascoltatore: Optional[logging.handlers.QueueListener] = None
_invio: Optional["InvioSyslog"] = None


class InvioSyslog(logging.Handler):
    """Scrive una riga syslog per record. Non solleva e non logga mai."""

    def __init__(self, host: str, port: int, protocollo: str = "udp"):
        super().__init__()
        self.host = host
        self.port = int(port)
        self.protocollo = protocollo if protocollo in PROTOCOLLI else "udp"
        self.hostname = socket.gethostname()
        self.inviati = 0
        self.errori = 0
        self.ultimo_errore: Optional[str] = None
        self.ultimo_errore_quando: Optional[str] = None
        self._sock: Optional[socket.socket] = None
        self._non_prima_di = 0.0

    def riga(self, record: logging.LogRecord) -> bytes:
        pri = _FACILITY_LOCAL0 * 8 + _PRIORITA.get(record.levelno, 6)
        quando = datetime.fromtimestamp(record.created).strftime("%b %d %H:%M:%S")
        corpo = self.format(record).replace("\n", " ")
        return f"<{pri}>{quando} {self.hostname} {_TAG}: {corpo}".encode("utf-8", "replace")

    def _apri(self) -> socket.socket:
        if self.protocollo == "tcp":
            return socket.create_connection((self.host, self.port), timeout=3)
        famiglia = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_DGRAM)[0][0]
        s = socket.socket(famiglia, socket.SOCK_DGRAM)
        s.settimeout(3)
        return s

    def spedisci(self, dati: bytes) -> None:
        """Invia o solleva OSError: lo usa anche il «Prova» di Impostazioni."""
        if self._sock is None:
            self._sock = self._apri()
        if self.protocollo == "tcp":
            self._sock.sendall(dati + b"\n")
        else:
            self._sock.sendto(dati[:_MAX_UDP], (self.host, self.port))

    def emit(self, record: logging.LogRecord) -> None:
        if self.protocollo == "tcp" and self._sock is None and time.monotonic() < self._non_prima_di:
            self.errori += 1
            return
        try:
            self.spedisci(self.riga(record))
            self.inviati += 1
        except Exception as e:  # noqa: BLE001 - un log non deve mai rompere il servizio
            self.errori += 1
            self.ultimo_errore = f"{type(e).__name__}: {e}"[:200]
            self.ultimo_errore_quando = datetime.utcnow().isoformat() + "Z"
            self._chiudi_socket()
            self._non_prima_di = time.monotonic() + _RIPROVA_TCP_S

    def _chiudi_socket(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def close(self) -> None:
        self._chiudi_socket()
        super().close()


def ferma() -> None:
    global _coda_handler, _ascoltatore, _invio
    if _coda_handler is not None:
        logging.getLogger().removeHandler(_coda_handler)
    if _ascoltatore is not None:
        _ascoltatore.stop()
    if _invio is not None:
        _invio.close()
    _coda_handler = _ascoltatore = _invio = None


def applica(enabled: bool, host: str, port: int = 514, protocollo: str = "udp") -> bool:
    """Accende, cambia o spegne l'invio. Ritorna True se e' acceso."""
    from services.logging_config import JSONFormatter

    ferma()
    host = (host or "").strip()
    if not enabled or not host:
        return False
    global _coda_handler, _ascoltatore, _invio
    _invio = InvioSyslog(host, port, protocollo)
    _invio.setFormatter(JSONFormatter())
    coda: "queue.Queue" = queue.Queue(maxsize=10000)
    _coda_handler = _CodaSenzaBlocco(coda)
    _ascoltatore = logging.handlers.QueueListener(coda, _invio)
    _ascoltatore.start()
    logging.getLogger().addHandler(_coda_handler)
    return True


class _CodaSenzaBlocco(logging.handlers.QueueHandler):
    """Coda piena = collettore fermo da un pezzo: la riga si perde, il servizio no."""

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        return record  # il formato lo applica InvioSyslog, con exc_info intatto

    def enqueue(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            if _invio is not None:
                _invio.errori += 1


def leggi_config(db) -> Dict[str, Any]:
    from database import SystemConfig

    righe = {
        c.key: c.value
        for c in db.query(SystemConfig).filter(SystemConfig.category == "syslog").all()
    }
    try:
        port = int(righe.get("syslog_port") or 514)
    except ValueError:
        port = 514
    protocollo = (righe.get("syslog_protocol") or "udp").lower()
    return {
        "enabled": (righe.get("syslog_enabled") or "false").lower() == "true",
        "host": (righe.get("syslog_host") or "").strip(),
        "port": port,
        "protocol": protocollo if protocollo in PROTOCOLLI else "udp",
    }


def applica_da_db(db) -> bool:
    c = leggi_config(db)
    return applica(c["enabled"], c["host"], c["port"], c["protocol"])


def stato() -> Dict[str, Any]:
    if _invio is None:
        return {"attivo": False, "inviati": 0, "errori": 0, "ultimo_errore": None, "ultimo_errore_quando": None}
    return {
        "attivo": True,
        "inviati": _invio.inviati,
        "errori": _invio.errori,
        "ultimo_errore": _invio.ultimo_errore,
        "ultimo_errore_quando": _invio.ultimo_errore_quando,
    }


def prova(host: str, port: int, protocollo: str) -> None:
    """Manda una riga di prova e solleva OSError se non parte.

    In UDP «partita» non vuol dire «arrivata»: nessuno risponde. Lo si dice
    all'utente, non lo si nasconde."""
    from services.logging_config import JSONFormatter

    h = InvioSyslog(host.strip(), port, protocollo)
    h.setFormatter(JSONFormatter())
    record = logging.LogRecord(
        "services.syslog_remoto", logging.INFO, __file__, 0,
        "Riga di prova del syslog remoto di DA-PXREPL", None, None,
    )
    try:
        h.spedisci(h.riga(record))
    finally:
        h.close()
