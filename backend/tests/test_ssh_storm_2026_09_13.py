"""Tempesta SSH verso PX-04 di DTS (13 settembre 2026).

`dts-repl` apriva ~2.000 connessioni SSH fallite l'ora verso il nodo di
destinazione: `sshd` raggiungeva `MaxStartups` e scartava a caso — anche il
proxy interno del cluster. Due cause, provate qui una per una:

1. `reconcile_pending_vm_registrations` leggeva lo stdout vuoto di un `test -f`
   FALLITO per trasporto come «la VM non è registrata», e lanciava la
   registrazione (altre decine di comandi SSH) ogni due minuti.
2. `SSHService._get_client` lasciava che N thread riaprissero insieme la stessa
   connessione caduta, senza nessuna pausa dopo un fallimento.
"""

from __future__ import annotations

import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.ssh_service import SSHResult, SSHService


# --- 1. riconciliazione ----------------------------------------------------

def _job(**kw):
    job = MagicMock()
    job.id = kw.get("id", 7)
    job.last_status = "success"
    job.register_vm = True
    job.vm_id = 101
    job.dest_vm_id = 9101
    job.dest_node_id = 3
    job.vm_type = "qemu"
    return job


@pytest.mark.asyncio
async def test_reconcile_non_registra_se_il_test_f_fallisce_per_trasporto():
    from services import sync_job_reconciliation as rec

    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [_job()]
    dest = MagicMock(); dest.hostname = "172.16.1.144"; dest.ssh_port = 22
    dest.ssh_user = "root"; dest.ssh_key_path = "/root/.ssh/id_rsa"
    db.query.return_value.filter.return_value.first.return_value = dest

    fallito = SSHResult(success=False, stdout="", stderr="Error reading SSH protocol banner", exit_code=-1)
    registra = AsyncMock()
    with patch("database.SessionLocal", return_value=db), \
         patch.object(rec, "_vm_group_sync_complete", return_value=True), \
         patch("services.ssh_service.ssh_service.execute", AsyncMock(return_value=fallito)), \
         patch.object(rec, "_try_register_vm_after_sync", registra):
        await rec.reconcile_pending_vm_registrations()

    registra.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_registra_quando_il_conf_manca_davvero():
    """Il controllo di sopra non deve spegnere il caso legittimo: comando
    riuscito, stdout vuoto → il conf non c'è → si registra."""
    from services import sync_job_reconciliation as rec

    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [_job()]
    dest = MagicMock(); dest.hostname = "172.16.1.144"; dest.ssh_port = 22
    dest.ssh_user = "root"; dest.ssh_key_path = "/root/.ssh/id_rsa"
    log = MagicMock(); log.id = 55; log.message = "ok"
    db.query.return_value.filter.return_value.first.return_value = dest
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = log

    manca = SSHResult(success=False, stdout="", stderr="", exit_code=1)  # `test -f` → 1
    registra = AsyncMock()
    with patch("database.SessionLocal", return_value=db), \
         patch.object(rec, "_vm_group_sync_complete", return_value=True), \
         patch("services.ssh_service.ssh_service.execute", AsyncMock(return_value=manca)), \
         patch.object(rec, "_try_register_vm_after_sync", registra):
        await rec.reconcile_pending_vm_registrations()

    registra.assert_awaited_once_with(7, 55)


# --- 2. ssh_service ----------------------------------------------------------

def _svc_con_connect_finto(esito):
    """SSHService con paramiko finto: `esito` è una funzione chiamata a ogni
    connect (può alzare). Ritorna (service, contatore_connect)."""
    svc = SSHService()
    conta = {"n": 0}

    def fake_client_factory():
        client = MagicMock()
        transport = MagicMock(); transport.is_active.return_value = True
        client.get_transport.return_value = transport

        def connect(**kw):
            conta["n"] += 1
            esito()
        client.connect.side_effect = connect
        return client

    return svc, conta, fake_client_factory


def test_get_client_una_sola_riconnessione_per_host_con_thread_paralleli():
    import time as _t
    # connect lento: senza, i thread non si sovrappongono e la prova è vuota
    svc, conta, factory = _svc_con_connect_finto(lambda: _t.sleep(0.05))
    partenza = threading.Barrier(6)
    clients = []

    def worker():
        partenza.wait()
        clients.append(svc._get_client("172.16.1.144", 22, "root", "/k"))

    with patch("services.ssh_service.paramiko.SSHClient", side_effect=factory), \
         patch("services.ssh_service.os.path.exists", return_value=False):
        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads: t.start()
        for t in threads: t.join()

    assert conta["n"] == 1, "sei thread, una connessione: gli altri riusano"
    assert len({id(c) for c in clients}) == 1


def test_get_client_in_quarantena_dopo_un_connect_fallito():
    def esplode():
        raise OSError("Error reading SSH protocol banner")

    svc, conta, factory = _svc_con_connect_finto(esplode)
    with patch("services.ssh_service.paramiko.SSHClient", side_effect=factory), \
         patch("services.ssh_service.os.path.exists", return_value=False):
        with pytest.raises(Exception):
            svc._get_client("172.16.1.144", 22, "root", "/k")
        for _ in range(20):
            with pytest.raises(Exception):
                svc._get_client("172.16.1.144", 22, "root", "/k")

    assert conta["n"] == 1, "dopo un fallimento l'host è in quarantena: nessun nuovo connect"


def test_get_client_la_quarantena_scade():
    def esplode():
        raise OSError("banner")

    svc, conta, factory = _svc_con_connect_finto(esplode)
    orologio = {"t": 1000.0}
    with patch("services.ssh_service.paramiko.SSHClient", side_effect=factory), \
         patch("services.ssh_service.os.path.exists", return_value=False), \
         patch("services.ssh_service.time.monotonic", side_effect=lambda: orologio["t"]):
        with pytest.raises(Exception):
            svc._get_client("h", 22, "root", "/k")
        orologio["t"] += svc.QUARANTENA_SEC + 1
        with pytest.raises(Exception):
            svc._get_client("h", 22, "root", "/k")

    assert conta["n"] == 2


def test_get_client_la_quarantena_e_per_host():
    def esplode():
        raise OSError("banner")

    svc, conta, factory = _svc_con_connect_finto(esplode)
    with patch("services.ssh_service.paramiko.SSHClient", side_effect=factory), \
         patch("services.ssh_service.os.path.exists", return_value=False):
        with pytest.raises(Exception):
            svc._get_client("h1", 22, "root", "/k")
        with pytest.raises(Exception):
            svc._get_client("h2", 22, "root", "/k")

    assert conta["n"] == 2, "la quarantena di h1 non tocca h2"
