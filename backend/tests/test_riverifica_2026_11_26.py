"""Riverifica del 26/11/2026.

A DTS un PBS con l'indirizzo cambiato restava «in linea» e scriveva due errori
ogni 5 minuti; mancavano le intestazioni di sicurezza; tre rotte di prova
facevano partire connessioni ssh anche per un «viewer».
"""

import asyncio
from unittest.mock import AsyncMock, patch

from database import Node
from services.cache_service import GIRI_MUTI_PER_OFFLINE, CacheService
from services.host_info_service import ha_risposto
from services.intestazioni import IntestazioniSicurezza

VUOTO = {"cpu": {}, "kernel_version": "unknown", "proxmox_version": "Unknown"}
BUONO = {"cpu": {"cores": 2}, "kernel_version": "7.0.14-5-pve"}


def test_ha_risposto():
    assert ha_risposto(BUONO)
    assert not ha_risposto(VUOTO)
    assert not ha_risposto(None)


def _pbs(db, in_linea=True):
    n = Node(name="pbs-x", hostname="pbs.x", ssh_port=22, ssh_user="root", node_type="pbs", is_online=in_linea)
    db.add(n)
    db.commit()
    return n


def _giri(db, nodo, dettagli, porta=True, quanti=GIRI_MUTI_PER_OFFLINE):
    svc = CacheService()
    raccolta = AsyncMock(return_value=dettagli)
    with patch("services.host_info_service.HostInfoService.update_host_details", raccolta), \
         patch("services.cache_service.CacheService._porta_aperta", AsyncMock(return_value=porta)):
        for _ in range(quanti):
            asyncio.run(svc.refresh_node_vms(db, nodo))
    db.refresh(nodo)
    return raccolta


def test_pbs_muto_va_fuori_linea_e_poi_non_si_riprova(db):
    nodo = _pbs(db)
    _giri(db, nodo, VUOTO)
    assert nodo.is_online is False
    raccolta = _giri(db, nodo, VUOTO, porta=False, quanti=2)
    assert raccolta.await_count == 0


def test_pbs_che_torna_viene_rimesso_in_linea(db):
    nodo = _pbs(db, in_linea=False)
    _giri(db, nodo, BUONO, porta=True, quanti=1)
    assert nodo.is_online is True and nodo.last_check is not None


def test_intestazioni_di_sicurezza():
    inviati = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"x-frame-options", b"SAMEORIGIN")]})

    async def send(msg):
        inviati.append(msg)

    asyncio.run(IntestazioniSicurezza(app)({"type": "http", "scheme": "https"}, None, send))
    h = dict(inviati[0]["headers"])
    assert h[b"x-content-type-options"] == b"nosniff"
    assert h[b"x-frame-options"] == b"SAMEORIGIN"      # non si sovrascrive chi l'ha già messa
    assert b"strict-transport-security" in h

    inviati.clear()
    asyncio.run(IntestazioniSicurezza(app)({"type": "http", "scheme": "http"}, None, send))
    assert b"strict-transport-security" not in dict(inviati[0]["headers"])


def test_ripristino_pbs_antepone_lo_storage_al_percorso_nudo():
    """Prova dal vivo a Domarc, 26/11/2026: dal pannello PBS `qmrestore`
    riceveva `vm/9801/…` senza storage e rispondeva «can't find file»."""
    from services.pbs_service import pbs_service
    from services.ssh_service import SSHResult

    comandi = []

    async def finto(hostname, command, **kw):
        comandi.append(command)
        return SSHResult(success=True, stdout="", stderr="", exit_code=0 if "qmrestore" in command else 1)

    with patch("services.pbs_service.ssh_service.execute", finto), \
         patch.object(pbs_service, "_ensure_pbs_storage", AsyncMock(return_value=(True, "PBS-BACK"))):
        esito = asyncio.run(pbs_service.run_restore(
            dest_node_hostname="px", vm_id=9802, pbs_hostname="192.0.2.1", datastore="Synology",
            backup_id="vm/9801/2026-11-26T01:12:56Z", pbs_user="backup@pbs", pbs_password="x",
            dest_vm_id=9802, dest_storage="zfs", vm_type="qemu", overwrite=True, unique=True))
    assert esito["success"], esito
    finale = [c for c in comandi if c.startswith("qmrestore")][0]
    assert finale.startswith("qmrestore PBS-BACK:backup/vm/9801/2026-11-26T01:12:56Z 9802")
