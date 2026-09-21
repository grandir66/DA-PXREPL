"""«Attiva DR»: ripristina sulla replica l'uuid SMBIOS della sorgente.

Specifica: docs/2026-09-21-replica-identita-vm-spec.md §2.2. La rotta non
avvia la VM; rifiuta senza conferma scritta, rifiuta se la sorgente e' ancora
accesa (salvo force), e legge l'originale dalla description della replica —
cosi' funziona anche sulle 12 repliche di DTS corrette a mano il 21/09.
"""

from unittest.mock import AsyncMock, patch

import pytest

from database import Node, SyncJob
from services.ssh_service import SSHResult

UUID_ORIG = "6f5d9e1a-2b3c-4d5e-8f90-1a2b3c4d5e6f"
UUID_REPL = "0d7a3a3d-1a8b-5c1f-9d2e-2b3c4d5e6f70"
VMGENID_ORIG = "0c1d2e3f-4a5b-6c7d-8e9f-0a1b2c3d4e5f"

CONFIG_REPLICA = f"""name: 3CX-V20-replica
onboot: 0
smbios1: uuid={UUID_REPL},base64=1
vmgenid: 11111111-2222-3333-4444-555555555555
description: dapx-replica di VM 101 da px-01 | smbios1 originale: uuid={UUID_ORIG} | vmgenid originale: {VMGENID_ORIG} | attivazione DR: ripristinare smbios1 prima dello start
tags: REPL
"""

CONFIG_A_MANO = f"""name: 3CX-V20-replica
onboot: 0
smbios1: uuid={UUID_REPL}
description: dapx-replica di VM 101 | smbios1 originale: uuid={UUID_ORIG} | per attivare il DR: qm set 9101 --smbios1 uuid={UUID_ORIG} (poi start)
"""


@pytest.fixture
def nodi(db):
    src = Node(name="px-01", hostname="px-01.dts", ssh_port=22, ssh_user="root")
    dst = Node(name="px-04", hostname="px-04.dts", ssh_port=22, ssh_user="root")
    db.add_all([src, dst])
    db.commit()
    return src, dst


@pytest.fixture
def job(db, nodi):
    src, dst = nodi
    j = SyncJob(
        name="VM 101", source_node_id=src.id, dest_node_id=dst.id,
        source_dataset="rpool/data/vm-101-disk-0", dest_dataset="ZFS/replica/vm-101-disk-0",
        register_vm=True, vm_id=101, dest_vm_id=9101, vm_group_id="grp-101",
    )
    db.add(j)
    db.commit()
    return j


def _ssh(config_replica: str, stato_sorgente: str = "status: stopped", sorgente_giu: bool = False):
    """Un finto ssh_service.execute: config della replica, stato della sorgente, qm set."""
    comandi: list[tuple[str, str]] = []

    async def execute(hostname, command, **kw):
        comandi.append((hostname, command))
        if command.startswith("qm config"):
            return SSHResult(success=True, stdout=config_replica, stderr="", exit_code=0)
        if command.startswith("qm status"):
            if sorgente_giu:
                return SSHResult(success=False, stdout="", stderr="ssh: connect: No route to host", exit_code=-1)
            return SSHResult(success=True, stdout=stato_sorgente + "\n", stderr="", exit_code=0)
        if command.startswith("qm set"):
            return SSHResult(success=True, stdout="update VM 9101: -smbios1 ...", stderr="", exit_code=0)
        return SSHResult(success=False, stdout="", stderr=f"comando inatteso: {command}", exit_code=1)

    return AsyncMock(side_effect=execute), comandi


def _post(client, token, dst_id, body):
    return client.post(
        f"/api/vms/node/{dst_id}/vm/9101/activate-dr",
        json=body, headers={"Authorization": f"Bearer {token}"},
    )


def test_attiva_dr_ripristina_uuid_originale_e_non_avvia(client, operator_user, operator_token, db, nodi, job):
    src, dst = nodi
    finto, comandi = _ssh(CONFIG_REPLICA)
    with patch("routers.vms.ssh_service.execute", finto), \
         patch("services.proxmox_service.ssh_service.execute", finto):
        r = _post(client, operator_token, dst.id, {"confirm": "ATTIVA"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["smbios1_dopo"] == f"uuid={UUID_ORIG},base64=1"
    assert body["smbios1_prima"] == f"uuid={UUID_REPL},base64=1"
    assert body["vmgenid_ripristinato"] is False
    assert body["stato_sorgente"] == "stopped"

    qm_set = [c for h, c in comandi if c.startswith("qm set")]
    assert len(qm_set) == 1
    assert f"uuid={UUID_ORIG},base64=1" in qm_set[0]
    assert "--vmgenid" not in qm_set[0]
    assert "DR ATTIVATO" in qm_set[0]
    # nessuno start, e lo stato della sorgente si e' chiesto al NODO SORGENTE
    assert not any("qm start" in c for _, c in comandi)
    assert any(h == "px-01.dts" and c.startswith("qm status 101") for h, c in comandi)

    from database import JobLog, AuditLog
    log = db.query(JobLog).filter(JobLog.job_type == "activate_dr").one()
    assert log.status == "success" and "NON e' stata avviata" in log.message
    assert db.query(AuditLog).filter(AuditLog.action == "vm_dr_activated").count() == 1


def test_attiva_dr_senza_conferma_400(client, operator_token, nodi, job):
    _, dst = nodi
    finto, comandi = _ssh(CONFIG_REPLICA)
    with patch("routers.vms.ssh_service.execute", finto), \
         patch("services.proxmox_service.ssh_service.execute", finto):
        r = _post(client, operator_token, dst.id, {"confirm": "si"})
    assert r.status_code == 400
    assert comandi == []  # non ha nemmeno letto la config


def test_attiva_dr_sorgente_accesa_409_e_force_passa(client, operator_token, nodi, job):
    _, dst = nodi
    finto, comandi = _ssh(CONFIG_REPLICA, stato_sorgente="status: running")
    with patch("routers.vms.ssh_service.execute", finto), \
         patch("services.proxmox_service.ssh_service.execute", finto):
        r = _post(client, operator_token, dst.id, {"confirm": "ATTIVA"})
        assert r.status_code == 409, r.text
        assert "ancora accesa" in r.json()["detail"]
        assert not any(c.startswith("qm set") for _, c in comandi)

        r = _post(client, operator_token, dst.id, {"confirm": "ATTIVA", "force": True})
    assert r.status_code == 200, r.text
    assert r.json()["forzato"] is True
    assert r.json()["stato_sorgente"] == "running"


def test_attiva_dr_nodo_sorgente_irraggiungibile_e_lo_scenario_dr(client, operator_token, nodi, job):
    _, dst = nodi
    finto, _ = _ssh(CONFIG_REPLICA, sorgente_giu=True)
    with patch("routers.vms.ssh_service.execute", finto), \
         patch("services.proxmox_service.ssh_service.execute", finto):
        r = _post(client, operator_token, dst.id, {"confirm": "ATTIVA"})
    assert r.status_code == 200, r.text
    assert r.json()["stato_sorgente"] == "irraggiungibile"


def test_attiva_dr_legge_la_description_scritta_a_mano_senza_job(client, operator_token, nodi):
    """Replica corretta a mano su PX-04 (nessun job in DB): l'originale sta
    nella description; senza job non si puo' guardare la sorgente → serve force."""
    _, dst = nodi
    finto, comandi = _ssh(CONFIG_A_MANO)
    with patch("routers.vms.ssh_service.execute", finto), \
         patch("services.proxmox_service.ssh_service.execute", finto):
        r = _post(client, operator_token, dst.id, {"confirm": "ATTIVA"})
        assert r.status_code == 409
        assert "Nessun job" in r.json()["detail"]
        r = _post(client, operator_token, dst.id, {"confirm": "ATTIVA", "force": True})
    assert r.status_code == 200, r.text
    assert r.json()["smbios1_dopo"] == f"uuid={UUID_ORIG}"
    assert r.json()["stato_sorgente"] == "sconosciuto"


def test_attiva_dr_ripristina_vmgenid_se_richiesto(client, operator_token, nodi, job):
    _, dst = nodi
    finto, comandi = _ssh(CONFIG_REPLICA)
    with patch("routers.vms.ssh_service.execute", finto), \
         patch("services.proxmox_service.ssh_service.execute", finto):
        r = _post(client, operator_token, dst.id, {"confirm": "ATTIVA", "ripristina_vmgenid": True})
    assert r.status_code == 200, r.text
    assert r.json()["vmgenid_ripristinato"] is True
    qm_set = [c for _, c in comandi if c.startswith("qm set")][0]
    assert f"--vmgenid {VMGENID_ORIG}" in qm_set


def test_attiva_dr_su_vm_che_non_e_una_replica_404(client, operator_token, nodi, job):
    _, dst = nodi
    finto, comandi = _ssh("name: produzione\nsmbios1: uuid=" + UUID_ORIG + "\n")
    with patch("routers.vms.ssh_service.execute", finto), \
         patch("services.proxmox_service.ssh_service.execute", finto):
        r = _post(client, operator_token, dst.id, {"confirm": "ATTIVA", "force": True})
    assert r.status_code == 404
    assert not any(c.startswith("qm set") for _, c in comandi)


def test_attiva_dr_gia_attivato_409(client, operator_token, nodi, job):
    _, dst = nodi
    gia = CONFIG_REPLICA.replace(f"smbios1: uuid={UUID_REPL}", f"smbios1: uuid={UUID_ORIG}")
    finto, comandi = _ssh(gia)
    with patch("routers.vms.ssh_service.execute", finto), \
         patch("services.proxmox_service.ssh_service.execute", finto):
        r = _post(client, operator_token, dst.id, {"confirm": "ATTIVA"})
    assert r.status_code == 409
    assert "gia'" in r.json()["detail"]


def test_attiva_dr_richiede_operatore(client, viewer_user, nodi, job):
    from services.auth_service import auth_service
    token = auth_service.create_access_token(data={
        "sub": str(viewer_user.id), "username": viewer_user.username,
        "role": viewer_user.role, "auth_method": viewer_user.auth_method,
    })
    _, dst = nodi
    r = _post(client, token, dst.id, {"confirm": "ATTIVA"})
    assert r.status_code == 403


def test_full_details_porta_l_identita_della_replica(client, admin_user, admin_token, nodi):
    _, dst = nodi
    dettagli = {
        "vmid": 9101, "config": {
            "name": "3CX-V20-replica",
            "smbios1": f"uuid={UUID_REPL}",
            "description": f"dapx-replica di VM 101 da px-01 | smbios1 originale: uuid={UUID_ORIG}",
        },
    }
    with patch("routers.vms.proxmox_service.get_vm_full_details", AsyncMock(return_value=dettagli)):
        r = client.get(
            f"/api/vms/node/{dst.id}/vm/9101/full-details",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    assert r.status_code == 200
    ident = r.json()["replica_identity"]
    assert ident["is_replica"] is True
    assert ident["source_smbios_uuid"] == UUID_ORIG
    assert ident["current_smbios_uuid"] == UUID_REPL
    assert ident["dr_attivo"] is False
    assert ident["source_vmid"] == 101 and ident["source_hostname"] == "px-01"


def test_full_details_vm_normale_non_e_replica(client, admin_user, admin_token, nodi):
    _, dst = nodi
    dettagli = {"vmid": 101, "config": {"name": "prod", "smbios1": f"uuid={UUID_ORIG}"}}
    with patch("routers.vms.proxmox_service.get_vm_full_details", AsyncMock(return_value=dettagli)):
        r = client.get(
            f"/api/vms/node/{dst.id}/vm/101/full-details",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    assert r.json()["replica_identity"] == {"is_replica": False}
