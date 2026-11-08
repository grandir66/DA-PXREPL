"""Due messaggi del riepilogo che a DTS (8 novembre 2026) dicevano il falso.

1. «Non partito» sui dischi secondari di una VM: la catena del gruppo si
   ferma al primo disco fallito, quindi gli altri non partono. Il riepilogo
   li chiamava «non partito» senza dire perché, e sembravano un guasto
   dello scheduler (VM 114, disco 0 fermo dal 27/10).
2. «Registrazione VM fallita: VMID 9114 già in uso» quando la 9114 era
   proprio la replica, già registrata con quel disco.
"""

from __future__ import annotations

from services.notification_summary import _stato, segna_dischi_saltati
from services.sync_job_execution import nota_registrazione_vm


def _job(id_, gruppo, **kw):
    base = {"id": id_, "type": "sync", "vm_group_id": gruppo, "failed_24h": 0,
            "success_24h": 0, "runs_24h": 0, "in_ritardo": False, "last_status": "success"}
    base.update(kw)
    return base


def test_disco_dopo_un_disco_fallito_e_saltato_non_fermo():
    jobs = [
        _job(13, "g114", failed_24h=1, runs_24h=1, last_status="failed", name="VM-114 scsi1"),
        _job(14, "g114", in_ritardo=True, name="VM-114 scsi2"),
        _job(20, "g112", in_ritardo=True),            # fermo vero: nessuno prima
    ]
    segna_dischi_saltati(jobs)
    assert _stato(jobs[1]) == "saltato"
    assert jobs[1]["saltato_dopo"] == "VM-114 scsi1"
    assert _stato(jobs[2]) == "fermo"
    assert _stato(jobs[0]) == "failed"


def test_anche_dopo_un_disco_fermo_il_successivo_e_saltato():
    jobs = [_job(5, "g101", in_ritardo=True, name="a"), _job(6, "g101", in_ritardo=True, name="b")]
    segna_dischi_saltati(jobs)
    assert _stato(jobs[0]) == "fermo"
    assert _stato(jobs[1]) == "saltato"


def test_senza_gruppo_niente_cambia():
    jobs = [_job(1, None, failed_24h=1, last_status="failed"), _job(2, None, in_ritardo=True)]
    segna_dischi_saltati(jobs)
    assert _stato(jobs[1]) == "fermo"


CONFIG_9114 = """name: SRV-WIN2025-replica
scsi1: ZFS-replica:vm-114-disk-1,discard=on,iothread=1,size=100G
scsi2: ZFS-replica:vm-114-disk-0,discard=on,iothread=1,size=150G
"""


def test_vmid_in_uso_dalla_replica_stessa_non_e_un_fallimento():
    nota = nota_registrazione_vm(
        "VMID 9114 già in uso su questo nodo", 9114, CONFIG_9114,
        "ZFS/replica/vm-114-disk-1", "DTS-PX-04",
    )
    assert "fallita" not in nota.lower()
    assert "9114" in nota and "già registrata" in nota


def test_vmid_in_uso_da_un_altra_vm_resta_un_errore():
    nota = nota_registrazione_vm(
        "VMID 9114 già in uso su questo nodo", 9114,
        "name: altra\nscsi0: local-zfs:vm-9114-disk-0,size=32G\n",
        "ZFS/replica/vm-114-disk-1", "DTS-PX-04",
    )
    assert "Registrazione VM fallita" in nota
    assert "un'altra VM" in nota


def test_altri_errori_restano_come_prima():
    nota = nota_registrazione_vm("storage mancante", 9114, None, "ZFS/replica/vm-114-disk-1", "DTS-PX-04")
    assert nota == " | Registrazione VM fallita: storage mancante"
