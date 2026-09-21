"""Il job segue la VM nel cluster (3.23.0).

Un job di replica parte dal nodo registrato alla creazione; in un cluster
la VM si sposta (migrazione, HA). Qui i tre esiti della risoluzione —
uguale / spostata / non_so — più il rifiuto motivato, e la persistenza sul
gruppo. Le risposte del cluster sono finte; il DB è quello in memoria.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from database import Node, SyncJob
from services.ssh_service import SSHResult
from services import vm_locator
from services.vm_locator import (
    MappaCluster,
    Posizione,
    parse_risorse,
    persisti_spostamento,
    risolvi_nodo_sorgente,
    senza_snapshot_in_comune,
)

RISORSE = """[
 {"type":"node","node":"px-01","status":"online"},
 {"type":"node","node":"px-02","status":"online"},
 {"type":"node","node":"px-04","status":"online"},
 {"type":"qemu","vmid":101,"node":"px-02","name":"3CX-V20","status":"running"},
 {"type":"qemu","vmid":103,"node":"px-01","name":"web","status":"running"},
 {"type":"lxc","vmid":200,"node":"px-01","name":"ct","status":"stopped"},
 {"type":"qemu","vmid":9101,"node":"px-04","name":"3CX-V20-replica","status":"stopped"},
 {"type":"storage","storage":"local-zfs","node":"px-01"}
]"""


def test_parse_risorse_nodi_e_vm():
    m = parse_risorse(RISORSE)
    assert m.nodi == ["px-01", "px-02", "px-04"]
    assert m.vm == {101: "px-02", 103: "px-01", 200: "px-01", 9101: "px-04"}
    assert m.conosce("px-02") and not m.conosce("px-09")
    assert parse_risorse("") is None and parse_risorse("{}") is None


@pytest.fixture(autouse=True)
def _cache_pulita():
    vm_locator.svuota_cache()
    yield
    vm_locator.svuota_cache()


@pytest.fixture
def cluster(db):
    n1 = Node(name="px-01", hostname="px-01", node_type="pve", is_active=True, is_online=True)
    n2 = Node(name="px-02", hostname="px-02", node_type="pve", is_active=True, is_online=True)
    n4 = Node(name="px-04", hostname="px-04", node_type="pve", is_active=True, is_online=True)
    db.add_all([n1, n2, n4])
    db.commit()
    return n1, n2, n4


def _job(db, src, dst, vm_id=101, gruppo="grp-101", dischi=("scsi0", "scsi1")):
    jobs = []
    for d in dischi:
        j = SyncJob(
            name=f"VM {vm_id} {d}", source_node_id=src.id, dest_node_id=dst.id,
            source_dataset=f"rpool/data/vm-{vm_id}-{d}", dest_dataset=f"ZFS/replica/vm-{vm_id}-{d}",
            vm_id=vm_id, dest_vm_id=9000 + vm_id, vm_group_id=gruppo, disk_name=d, register_vm=True,
        )
        db.add(j)
        jobs.append(j)
    db.commit()
    return jobs


def _ssh(risorse_per_host=None, dataset_esiste=True, dataset_exit=None):
    """execute finto: /cluster/resources per host, zfs list sul nodo nuovo."""
    risorse_per_host = risorse_per_host or {}
    chiamate = []

    async def execute(hostname, command, **kw):
        chiamate.append((hostname, command))
        if "cluster/resources" in command:
            r = risorse_per_host.get(hostname)
            if r is None:
                return SSHResult(success=False, stdout="", stderr="timeout", exit_code=-1)
            return SSHResult(success=True, stdout=r, stderr="", exit_code=0)
        if command.startswith("zfs list"):
            if dataset_exit is not None:
                return SSHResult(success=False, stdout="", stderr="ssh: no route", exit_code=dataset_exit)
            if dataset_esiste:
                return SSHResult(success=True, stdout="rpool/data/x\n", stderr="", exit_code=0)
            return SSHResult(success=False, stdout="cannot open: dataset does not exist", stderr="", exit_code=1)
        return SSHResult(success=False, stdout="", stderr=f"inatteso: {command}", exit_code=1)

    ssh = MagicMock()
    ssh.execute = AsyncMock(side_effect=execute)
    return ssh, chiamate


@pytest.mark.asyncio
async def test_uguale_quando_la_vm_e_sul_nodo_registrato(db, cluster):
    n1, n2, n4 = cluster
    job = _job(db, n1, n4, vm_id=103)[0]
    ssh, chiamate = _ssh({"px-01": RISORSE})
    pos = await risolvi_nodo_sorgente(db, job, n1, n4, ssh_service=ssh)
    assert pos.esito == "uguale" and pos.nodo is n1 and pos.nodo_pve == "px-01"
    assert not any(c.startswith("zfs list") for _, c in chiamate)


@pytest.mark.asyncio
async def test_spostata_su_nodo_censito_col_dataset(db, cluster):
    n1, n2, n4 = cluster
    job = _job(db, n1, n4, vm_id=101)[0]
    ssh, chiamate = _ssh({"px-01": RISORSE})
    pos = await risolvi_nodo_sorgente(db, job, n1, n4, ssh_service=ssh)
    assert pos.esito == "spostata" and pos.spostata
    assert pos.nodo.id == n2.id and pos.nodo_pve == "px-02"
    assert "era registrata su px-01" in pos.messaggio
    # il dataset si è controllato sul nodo NUOVO
    assert ("px-02", "zfs list -H -o name rpool/data/vm-101-scsi0 2>&1") in chiamate


@pytest.mark.asyncio
async def test_rifiutata_se_il_nodo_nuovo_non_e_censito(db, cluster):
    n1, n2, n4 = cluster
    n2.is_active = False
    db.commit()
    job = _job(db, n1, n4, vm_id=101)[0]
    ssh, _ = _ssh({"px-01": RISORSE})
    pos = await risolvi_nodo_sorgente(db, job, n1, n4, ssh_service=ssh)
    assert pos.esito == "rifiutata" and pos.nodo is None
    assert "non è censito" in pos.messaggio and "px-02" in pos.messaggio


@pytest.mark.asyncio
async def test_rifiutata_se_il_dataset_manca_sul_nodo_nuovo(db, cluster):
    n1, n2, n4 = cluster
    job = _job(db, n1, n4, vm_id=101)[0]
    ssh, _ = _ssh({"px-01": RISORSE}, dataset_esiste=False)
    pos = await risolvi_nodo_sorgente(db, job, n1, n4, ssh_service=ssh)
    assert pos.esito == "rifiutata"
    assert "non esiste su px-02" in pos.messaggio


@pytest.mark.asyncio
async def test_nodo_nuovo_che_non_risponde_non_e_dataset_assente(db, cluster):
    """`zfs list` fallito per trasporto (-1) non vale «manca» (DTS 2026-09-13)."""
    n1, n2, n4 = cluster
    job = _job(db, n1, n4, vm_id=101)[0]
    ssh, _ = _ssh({"px-01": RISORSE}, dataset_exit=-1)
    pos = await risolvi_nodo_sorgente(db, job, n1, n4, ssh_service=ssh)
    assert pos.esito == "rifiutata"
    assert "non risponde" in pos.messaggio and "non esiste" not in pos.messaggio


@pytest.mark.asyncio
async def test_rifiutata_se_la_vm_sta_sul_nodo_di_destinazione(db, cluster):
    n1, n2, n4 = cluster
    job = _job(db, n1, n4, vm_id=9101)[0]  # 9101 sta su px-04 = dest
    ssh, _ = _ssh({"px-01": RISORSE})
    pos = await risolvi_nodo_sorgente(db, job, n1, n4, ssh_service=ssh)
    assert pos.esito == "rifiutata" and "DESTINAZIONE" in pos.messaggio


@pytest.mark.asyncio
async def test_non_so_se_il_cluster_non_risponde(db, cluster):
    n1, n2, n4 = cluster
    job = _job(db, n1, n4, vm_id=101)[0]
    ssh, _ = _ssh({})  # nessuno risponde
    pos = await risolvi_nodo_sorgente(db, job, n1, n4, ssh_service=ssh)
    assert pos.esito == "non_so" and pos.nodo is n1
    assert "non risponde" in pos.messaggio


@pytest.mark.asyncio
async def test_non_so_se_la_vm_non_e_in_elenco(db, cluster):
    n1, n2, n4 = cluster
    job = _job(db, n1, n4, vm_id=777)[0]
    ssh, _ = _ssh({"px-01": RISORSE})
    pos = await risolvi_nodo_sorgente(db, job, n1, n4, ssh_service=ssh)
    assert pos.esito == "non_so" and pos.nodo is n1
    assert "non è nell'elenco" in pos.messaggio


@pytest.mark.asyncio
async def test_nodo_registrato_giu_si_chiede_a_un_altro_nodo_dello_stesso_cluster(db, cluster):
    """È il caso dell'HA: il nodo registrato è morto e la VM è ripartita altrove.
    La mappa vale solo se elenca il nodo registrato fra i membri: una mappa di
    un ALTRO cluster non deve essere scambiata per la sua."""
    n1, n2, n4 = cluster
    altro = Node(name="dom-01", hostname="dom-01", node_type="pve", is_active=True, is_online=True)
    db.add(altro)
    db.commit()
    job = _job(db, n1, n4, vm_id=101)[0]
    altro_cluster = '[{"type":"node","node":"dom-01"},{"type":"qemu","vmid":101,"node":"dom-01"}]'
    ssh, chiamate = _ssh({"dom-01": altro_cluster, "px-04": RISORSE})  # px-01 giù
    pos = await risolvi_nodo_sorgente(db, job, n1, n4, ssh_service=ssh)
    assert pos.esito == "spostata" and pos.nodo_pve == "px-02"
    interrogati = [h for h, c in chiamate if "cluster/resources" in c]
    assert interrogati[0] == "px-01" and "px-04" in interrogati


@pytest.mark.asyncio
async def test_la_mappa_si_chiede_una_volta_per_minuto(db, cluster):
    n1, n2, n4 = cluster
    jobs = _job(db, n1, n4, vm_id=101)
    ssh, chiamate = _ssh({"px-01": RISORSE})
    for j in jobs:
        await risolvi_nodo_sorgente(db, j, n1, n4, ssh_service=ssh)
    assert sum(1 for _, c in chiamate if "cluster/resources" in c) == 1


def test_persisti_spostamento_su_tutti_i_dischi_del_gruppo(db, cluster):
    n1, n2, n4 = cluster
    jobs = _job(db, n1, n4, vm_id=101)
    altro = _job(db, n1, n4, vm_id=103, gruppo="grp-103", dischi=("scsi0",))[0]
    n = persisti_spostamento(db, jobs[0], n2)
    db.commit()
    assert n == 2
    for j in jobs:
        db.refresh(j)
        assert j.source_node_id == n2.id
    db.refresh(altro)
    assert altro.source_node_id == n1.id


def test_senza_snapshot_in_comune_riconosce_il_rifiuto_di_syncoid():
    assert senza_snapshot_in_comune("CRITICAL ERROR: Target ZFS/replica/x exists but has no snapshots matching with rpool/x!")
    assert senza_snapshot_in_comune("Cowardly refusing to destroy your existing target")
    assert not senza_snapshot_in_comune("cannot open 'rpool/x': dataset does not exist")
    assert not senza_snapshot_in_comune(None)
