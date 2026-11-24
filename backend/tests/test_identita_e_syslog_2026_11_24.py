"""3.25.0 — richieste di Riccardo del 24/11/2026.

- Syslog remoto: tutto il log a un collettore (Wazuh), spento di default.
- «Riallinea identita'»: a Domarc le 9 repliche registrate prima della 3.22.0
  portavano ancora l'uuid SMBIOS della sorgente.
- Guardia: una replica registrata non deve avere l'avvio automatico.
"""
import json
import logging
import socket
import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from database import Node, SyncJob
from services import syslog_remoto
from services.replica_identity import uuid_replica
from services.repliche_onboot import _AWK, comando_onboot, repliche_con_onboot
from services.ssh_service import SSHResult

UUID_SRC = "4225318c-2a81-4c99-7279-2d941d957a06"
CONFIG_SORGENTE = f"name: DA-DC01\nonboot: 1\nsmbios1: uuid={UUID_SRC}\nvmgenid: 0c1d2e3f-4a5b-6c7d-8e9f-0a1b2c3d4e5f\n"
CONFIG_REPLICA_VECCHIA = f"name: DA-DC01-replica\nonboot: 1\nsmbios1: uuid={UUID_SRC}\n"


# ---------- syslog ----------

def test_syslog_udp_manda_una_riga_json_per_record():
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv.settimeout(3)
    try:
        assert syslog_remoto.applica(True, "127.0.0.1", srv.getsockname()[1], "udp") is True
        logging.getLogger("prova.syslog").error("replica fallita su %s", "px-01")
        dati = srv.recv(65535).decode()
    finally:
        syslog_remoto.ferma()
        srv.close()
    testa, _, corpo = dati.partition("dapx-unified: ")
    assert testa.startswith("<131>")  # local0.err
    evento = json.loads(corpo)
    assert evento["message"] == "replica fallita su px-01"
    assert evento["level"] == "ERROR"
    assert syslog_remoto.stato()["attivo"] is False


def test_syslog_collettore_spento_non_rompe_e_conta_l_errore():
    libero = socket.socket()
    libero.bind(("127.0.0.1", 0))
    porta = libero.getsockname()[1]
    libero.close()
    h = syslog_remoto.InvioSyslog("127.0.0.1", porta, "tcp")
    h.setFormatter(logging.Formatter("%(message)s"))
    h.emit(logging.LogRecord("x", logging.INFO, __file__, 0, "riga", None, None))
    assert h.errori == 1 and h.inviati == 0 and h.ultimo_errore


def test_syslog_api_nasce_spento_e_rifiuta_acceso_senza_indirizzo(client, auth_headers):
    r = client.get("/api/settings/syslog", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is False and r.json()["port"] == 514
    r = client.put("/api/settings/syslog", headers=auth_headers, json={"enabled": True, "host": ""})
    assert r.status_code == 400
    try:
        r = client.put("/api/settings/syslog", headers=auth_headers,
                       json={"enabled": True, "host": "127.0.0.1", "port": 5514, "protocol": "udp"})
        assert r.status_code == 200, r.text
        assert r.json()["stato"]["attivo"] is True
    finally:
        syslog_remoto.ferma()


# ---------- guardia onboot ----------

def test_awk_guarda_solo_la_sezione_principale_e_salta_il_dr_attivato(tmp_path):
    casi = {
        "101": "name: a\nonboot: 1\n",
        "102": "name: b\nonboot: 0\n\n[snap1]\nonboot: 1\n",
        "103": "name: c\nonboot: 1\ndescription: dapx-replica | DR ATTIVATO 2026-11-01 da x\n",
    }
    trovati = []
    for nome, testo in casi.items():
        f = tmp_path / f"{nome}.conf"
        f.write_text(testo)
        trovati.append(subprocess.run(f"{_AWK} {f}", shell=True, capture_output=True, text=True).stdout)
    assert repliche_con_onboot("".join(trovati)) == [101]
    assert "for i in 9101 9103;" in comando_onboot({9103, 9101})


# ---------- riallinea identita' ----------

@pytest.fixture
def replica(db):
    src = Node(name="DA-PX-01", hostname="px-01.da", ssh_port=22, ssh_user="root")
    dst = Node(name="PX-NAS", hostname="px-nas.da", ssh_port=22, ssh_user="root")
    db.add_all([src, dst])
    db.commit()
    db.add(SyncJob(
        name="VM-401", source_node_id=src.id, dest_node_id=dst.id,
        source_dataset="zfs/vm-401-disk-0", dest_dataset="ZFS-LARGE/replica/vm-401-disk-0",
        register_vm=True, vm_id=401, dest_vm_id=20002, vm_group_id="g401", vm_type="qemu",
    ))
    db.commit()
    return src, dst


def _ssh(config_replica, stato="status: stopped", sorgente_ok=True):
    comandi = []

    async def execute(hostname, command, **kw):
        comandi.append((hostname, command))
        if command.startswith("qm status"):
            return SSHResult(success=True, stdout=stato + "\n", stderr="", exit_code=0)
        if command.startswith("qm config"):
            if hostname == "px-01.da":
                if not sorgente_ok:
                    return SSHResult(success=False, stdout="", stderr="No route to host", exit_code=255)
                return SSHResult(success=True, stdout=CONFIG_SORGENTE, stderr="", exit_code=0)
            return SSHResult(success=True, stdout=config_replica, stderr="", exit_code=0)
        if command.startswith("qm set"):
            return SSHResult(success=True, stdout="update VM", stderr="", exit_code=0)
        return SSHResult(success=False, stdout="", stderr="inatteso", exit_code=1)

    return AsyncMock(side_effect=execute), comandi


def _riallinea(client, token, dst, finto):
    with patch("routers.vms.ssh_service.execute", finto), \
         patch("services.proxmox_service.ssh_service.execute", finto):
        return client.post(f"/api/vms/node/{dst.id}/vm/20002/riallinea-identita",
                           headers={"Authorization": f"Bearer {token}"})


def test_riallinea_scrive_uuid_derivato_e_spegne_onboot(client, operator_user, operator_token, db, replica):
    src, dst = replica
    finto, comandi = _ssh(CONFIG_REPLICA_VECCHIA)
    r = _riallinea(client, operator_token, dst, finto)
    assert r.status_code == 200, r.text
    assert r.json()["uuid_dopo"] == uuid_replica(UUID_SRC) != UUID_SRC
    qm_set = [c for h, c in comandi if c.startswith("qm set")]
    assert len(qm_set) == 1 and "--onboot 0" in qm_set[0] and uuid_replica(UUID_SRC) in qm_set[0]
    assert f"smbios1 originale: uuid={UUID_SRC}" in qm_set[0]
    assert all(h == "px-nas.da" for h, c in comandi if c.startswith("qm set"))
    db.expire_all()
    assert db.query(SyncJob).first().replica_smbios_uuid == uuid_replica(UUID_SRC)


@pytest.mark.parametrize("config,stato,sorgente_ok,atteso", [
    (CONFIG_REPLICA_VECCHIA, "status: running", True, 409),
    (CONFIG_REPLICA_VECCHIA + "description: x | DR ATTIVATO 2026-11-01 da y\n", "status: stopped", True, 409),
    (CONFIG_REPLICA_VECCHIA, "status: stopped", False, 502),
])
def test_riallinea_non_scrive_se_accesa_dr_attivo_o_sorgente_muta(
    client, operator_user, operator_token, replica, config, stato, sorgente_ok, atteso
):
    src, dst = replica
    finto, comandi = _ssh(config, stato=stato, sorgente_ok=sorgente_ok)
    r = _riallinea(client, operator_token, dst, finto)
    assert r.status_code == atteso, r.text
    assert not [c for h, c in comandi if c.startswith("qm set")]
