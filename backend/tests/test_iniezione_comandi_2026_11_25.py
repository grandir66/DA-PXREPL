"""Nessun valore arrivato da fuori entra in un comando ssh senza controllo.

Rilievo A1 della valutazione di sicurezza del 25/11/2026: un «operator»
poteva far eseguire comandi da root sui nodi mettendo `;` nel nome di uno
snapshot, di uno storage o di un job. Qui ogni rotta riceve un valore
ostile: deve rispondere 400 e non deve partire nessun comando.
"""

import pytest
from fastapi import HTTPException

from services import argomenti_sicuri
from services.ssh_service import SSHResult, ssh_service
from services.proxmox_service import proxmox_service

OSTILI = [
    "snap; touch /tmp/x",
    "snap$(id)",
    "snap`id`",
    "snap|id",
    "snap&&id",
    "snap id",
    "snap\nid",
    "snap'x",
    "-r",
    "",
]


@pytest.mark.parametrize("valore", OSTILI)
def test_validatori_rifiutano(valore):
    for f in (
        argomenti_sicuri.nome_snapshot,
        argomenti_sicuri.nome_dataset,
        argomenti_sicuri.id_storage,
        argomenti_sicuri.volume_backup,
        argomenti_sicuri.id_job_pvesr,
        argomenti_sicuri.nome_nodo,
    ):
        with pytest.raises(HTTPException) as e:
            f(valore)
        assert e.value.status_code == 400


def test_validatori_accettano_i_nomi_veri():
    for n in (
        "manual_2026-11-25_10:00:00",
        "syncoid_DA-PX-04_2026-11-25:05:00:12-GMT01:00",
        "autosnap_2026-11-25_05:00:01_hourly",
        "__replicate_103-0_1764000000__",
    ):
        assert argomenti_sicuri.nome_snapshot(n) == n
    assert argomenti_sicuri.nome_dataset("ZFS/replica/vm-103-disk-0")
    assert argomenti_sicuri.snapshot_completo("rpool/data/vm-100-disk-0@autosnap_1")
    assert argomenti_sicuri.id_storage("pbs-domarc")
    assert argomenti_sicuri.volume_backup("backup/vm/103/2026-11-24T18:30:00Z")
    assert argomenti_sicuri.id_job_pvesr("103-0")
    assert argomenti_sicuri.nome_nodo("DTS-PX-04")
    for brutto in ("pool/ds@a@b", "pool/../x@s", "@s", "pool@"):
        with pytest.raises(HTTPException):
            argomenti_sicuri.snapshot_completo(brutto)
    with pytest.raises(HTTPException):
        argomenti_sicuri.volume_backup("backup/../../etc/passwd")


@pytest.fixture
def comandi(monkeypatch):
    """Registra ogni comando che partirebbe verso un nodo."""
    partiti = []

    async def finto_execute(*args, **kwargs):
        partiti.append(kwargs.get("command") or (args[1] if len(args) > 1 else args))
        return SSHResult(success=True, stdout="", stderr="", exit_code=0)

    async def finto_dataset(*args, **kwargs):
        return ["rpool/data/vm-100-disk-0"]

    monkeypatch.setattr(ssh_service, "execute", finto_execute)
    monkeypatch.setattr(proxmox_service, "find_vm_dataset", finto_dataset)
    return partiti


CATTIVO = "s; touch /tmp/presa"


def test_rotte_rifiutano_prima_di_eseguire(client, auth_headers, sample_node, comandi):
    n = sample_node.id
    richieste = [
        ("post", f"/api/vms/node/{n}/vm/100/zfs-restore", {"json": {"snapshot_name": CATTIVO, "action": "rollback"}}),
        ("post", f"/api/vms/node/{n}/vm/100/zfs-restore", {"json": {"snapshot_name": CATTIVO, "action": "clone", "new_vmid": 900}}),
        ("post", f"/api/vms/node/{n}/vm/100/restore", {"json": {"backup_id": "backup/vm/100/x", "pbs_storage": CATTIVO}}),
        ("post", f"/api/vms/node/{n}/vm/100/restore", {"json": {"backup_id": CATTIVO, "pbs_storage": "pbs"}}),
        ("post", f"/api/vms/node/{n}/vm/100/restore", {"json": {"backup_id": "backup/vm/100/x", "pbs_storage": "pbs", "dest_storage": CATTIVO}}),
        ("post", f"/api/snapshots/node/{n}/rollback", {"params": {"full_name": f"rpool/data@{CATTIVO}"}}),
        ("post", f"/api/snapshots/node/{n}/clone", {"params": {"full_name": "rpool/data@s", "clone_name": CATTIVO}}),
        ("request", f"/api/vms/node/{n}/vm/100/zfs-snapshots", {"json": {"snapshot_name": CATTIVO}}),
        ("delete", "/api/pve-replication/100-0;id", {}),
        ("post", "/api/pve-replication/100-0;id/run", {}),
    ]
    for metodo, url, extra in richieste:
        if metodo == "request":
            r = client.request("DELETE", url, headers=auth_headers, **extra)
        else:
            r = getattr(client, metodo)(url, headers=auth_headers, **extra)
        assert r.status_code == 400, (url, extra, r.status_code, r.text)
    assert comandi == []


def test_rollback_buono_passa(client, auth_headers, sample_node, comandi):
    r = client.post(
        f"/api/vms/node/{sample_node.id}/vm/100/zfs-restore",
        headers=auth_headers,
        json={"snapshot_name": "autosnap_2026-11-25_05:00:01_hourly", "action": "rollback"},
    )
    assert r.status_code == 200, r.text
    assert comandi == ["zfs rollback -r rpool/data/vm-100-disk-0@autosnap_2026-11-25_05:00:01_hourly"]
